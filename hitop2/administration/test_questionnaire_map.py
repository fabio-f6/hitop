from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from polls.models import Question, Scale, Spectra, Subfactor

from .questionnaire_map import build_questionnaire_structure


class QuestionnaireMapTests(TestCase):
    password = "Uma-palavra-passe-segura-123"

    @classmethod
    def create_user(cls, username, user_type):
        user = User.objects.create_user(username=username, password=cls.password)
        user.userprofile.user_type = user_type
        user.userprofile.save(update_fields=["user_type"])
        return user

    @classmethod
    def setUpTestData(cls):
        cls.administrator = cls.create_user("map-admin", "admin")
        cls.professional = cls.create_user("map-professional", "professional")
        cls.patient = cls.create_user("map-patient", "patient")
        cls.spectrum = Spectra.objects.create(name="Internalizing")
        cls.subfactor = Subfactor.objects.create(
            name="Distress", spectra=cls.spectrum
        )
        cls.scale = Scale.objects.create(
            name="Anxious Worry", subfactor=cls.subfactor
        )
        cls.empty_scale = Scale.objects.create(
            name="Separation Insecurity", subfactor=cls.subfactor
        )
        cls.question = Question.objects.create(
            scale=cls.scale,
            item_code="HiTOP_156",
            question_text="Senti-me preocupado.",
        )
        cls.catch_spectrum = Spectra.objects.create(name="Catch")
        catch_subfactor = Subfactor.objects.create(
            name="Catch", spectra=cls.catch_spectrum
        )
        cls.catch_scale = Scale.objects.create(
            name="Catch", subfactor=catch_subfactor
        )
        cls.attention_question = Question.objects.create(
            scale=cls.catch_scale,
            item_code="catch-map-1",
            question_text="Selecione Nunca.",
            is_attention_check=True,
            expected_answer="1",
        )

    def setUp(self):
        self.client.force_login(self.administrator)

    def test_administrator_can_open_map(self):
        response = self.client.get(reverse("administration:questionnaire_map"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "administration/questionnaire_map.html")
        self.assertContains(response, "Mapa do Questionário")

    def test_professional_and_patient_cannot_open_map(self):
        for user in (self.professional, self.patient):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(
                    self.client.get(
                        reverse("administration:questionnaire_map")
                    ).status_code,
                    403,
                )

    def test_anonymous_user_is_redirected(self):
        self.client.logout()
        response = self.client.get(reverse("administration:questionnaire_map"))
        self.assertRedirects(response, reverse("website:home"))

    def test_only_get_is_accepted(self):
        response = self.client.post(reverse("administration:questionnaire_map"))
        self.assertEqual(response.status_code, 405)

    def test_structure_and_counts_follow_real_relations(self):
        structure = build_questionnaire_structure()
        spectrum = structure["roots"][0]
        subfactor = spectrum["children"][0]
        scales = {node["name"]: node for node in subfactor["children"]}
        question = scales["Anxious Worry"]["children"][0]

        self.assertEqual(spectrum["name"], "Internalizing")
        self.assertEqual(subfactor["name"], "Distress")
        self.assertEqual(question["name"], "HiTOP_156")
        self.assertEqual(scales["Anxious Worry"]["question_count"], 1)
        self.assertEqual(scales["Separation Insecurity"]["question_count"], 0)
        self.assertEqual(subfactor["question_count"], 1)
        self.assertEqual(spectrum["question_count"], 1)
        self.assertEqual(
            structure["totals"],
            {
                "spectra_count": 1,
                "subfactor_count": 1,
                "scale_count": 2,
                "question_count": 1,
            },
        )

    def test_question_has_searchable_fields_and_complete_path(self):
        question = build_questionnaire_structure()["roots"][0]["children"][0][
            "children"
        ][0]["children"][0]
        self.assertEqual(question["details"]["item_code"], "HiTOP_156")
        self.assertEqual(question["details"]["question_text"], "Senti-me preocupado.")
        self.assertEqual(
            question["path_text"],
            "Internalizing → Distress → Anxious Worry → HiTOP_156",
        )
        self.assertIn("hitop_156", question["name"].lower())
        self.assertIn("preocupado", question["details"]["question_text"].lower())

    def test_attention_only_structure_is_absent_from_scientific_map(self):
        structure = build_questionnaire_structure()
        serialized = str(structure)
        self.assertNotIn("catch-map-1", serialized)
        self.assertNotIn("'name': 'Catch'", serialized)
        self.assertEqual(structure["totals"]["spectra_count"], 1)
        self.assertEqual(structure["totals"]["subfactor_count"], 1)
        self.assertEqual(structure["totals"]["scale_count"], 2)
        self.assertEqual(structure["totals"]["question_count"], 1)

    def test_scale_without_questions_reuses_health_issue(self):
        scales = build_questionnaire_structure()["roots"][0]["children"][0][
            "children"
        ]
        empty_scale = next(node for node in scales if node["database_id"] == self.empty_scale.id)
        healthy_scale = next(node for node in scales if node["database_id"] == self.scale.id)
        self.assertEqual(empty_scale["issues"][0]["code"], "scale_without_questions")
        self.assertTrue(empty_scale["has_problem_in_branch"])
        self.assertFalse(healthy_scale["issues"])
        self.assertTrue(build_questionnaire_structure()["roots"][0]["has_problem_in_branch"])

    def test_empty_database_is_supported(self):
        Question.objects.all().delete()
        Scale.objects.all().delete()
        Subfactor.objects.all().delete()
        Spectra.objects.all().delete()
        structure = build_questionnaire_structure()
        self.assertEqual(structure["roots"], [])
        self.assertEqual(structure["totals"]["question_count"], 0)
        self.assertTrue(structure["unmapped_problems"])

    def test_builder_uses_four_queries_without_n_plus_one(self):
        with self.assertNumQueries(4):
            build_questionnaire_structure()

        Question.objects.bulk_create(
            [
                Question(
                    scale=self.scale,
                    item_code=f"HiTOP_{index:03}",
                    question_text=f"Question {index}",
                )
                for index in range(20)
            ]
        )
        with self.assertNumQueries(4):
            structure = build_questionnaire_structure()
        self.assertEqual(structure["totals"]["question_count"], 21)

    def test_map_does_not_write_to_database(self):
        before = {
            "spectra": Spectra.objects.count(),
            "subfactors": Subfactor.objects.count(),
            "scales": Scale.objects.count(),
            "questions": Question.objects.count(),
        }
        self.client.get(reverse("administration:questionnaire_map"))
        self.assertEqual(
            before,
            {
                "spectra": Spectra.objects.count(),
                "subfactors": Subfactor.objects.count(),
                "scales": Scale.objects.count(),
                "questions": Question.objects.count(),
            },
        )

    def test_payload_contains_no_clinical_or_authentication_data(self):
        response = self.client.get(reverse("administration:questionnaire_map"))
        payload = response.context["questionnaire_map"]
        serialized = str(payload).lower()
        for forbidden in (
            "access_token",
            "useranswer",
            "sociodemographic",
            "percentile",
            "score",
            "submission",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_page_exposes_required_read_only_interactions(self):
        response = self.client.get(reverse("administration:questionnaire_map"))
        for text in (
            "Expandir tudo",
            "Recolher tudo",
            "Com problemas",
            "Sem problemas",
            "Hierarquia",
            "Mapa Visual",
            "Ajustar",
            "data-visual-map",
            "aria-live",
        ):
            self.assertContains(response, text)
        for mutable_label in ("Editar", "Eliminar", "Guardar", "Mover"):
            self.assertNotContains(response, mutable_label)

    def test_dashboard_links_to_map(self):
        response = self.client.get(reverse("administration:dashboard"))
        self.assertContains(response, reverse("administration:questionnaire_map"))

    def test_d3_is_loaded_as_a_local_static_asset(self):
        response = self.client.get(reverse("administration:questionnaire_map"))
        self.assertContains(
            response,
            "/static/administration/vendor/d3/d3.v7.9.0.min.js",
        )
        self.assertNotContains(response, "cdn.jsdelivr.net/npm/d3")
        self.assertNotContains(response, "d3js.org/d3")
        self.assertIsNotNone(
            finders.find("administration/vendor/d3/d3.v7.9.0.min.js")
        )
        self.assertIsNotNone(finders.find("administration/vendor/d3/LICENSE"))

    def test_visual_renderer_uses_d3_radial_hierarchy_and_zoom(self):
        javascript_path = finders.find(
            "administration/js/questionnaire-map.js"
        )
        with open(javascript_path, encoding="utf-8") as javascript_file:
            javascript = javascript_file.read()

        for required_api in (
            "d3.hierarchy(",
            "d3.tree()",
            "d3.linkRadial()",
            "d3.zoom()",
            '.data(hierarchy.links()',
            '.data(descendants,',
        ):
            self.assertIn(required_api, javascript)

        for legacy_renderer_fragment in (
            "visualTransform",
            "pointerdown",
            "visualNodes()",
        ):
            self.assertNotIn(legacy_renderer_fragment, javascript)

    def test_visual_map_is_the_first_and_default_tab(self):
        response = self.client.get(reverse("administration:questionnaire_map"))
        content = response.content.decode()
        self.assertLess(content.index('id="visual-tab"'), content.index('id="hierarchy-tab"'))
        self.assertIn('id="visual-tab" class="map-tab active"', content)
        self.assertIn('id="hierarchy-panel" role="tabpanel" aria-labelledby="hierarchy-tab" hidden', content)
        self.assertNotIn('id="visual-panel" role="tabpanel" aria-labelledby="visual-tab" hidden', content)

    def test_visual_renderer_supports_root_reset_and_density_spacing(self):
        javascript_path = finders.find("administration/js/questionnaire-map.js")
        with open(javascript_path, encoding="utf-8") as javascript_file:
            javascript = javascript_file.read()

        for behavior in (
            "clearSelection({ collapseExpansions: true });",
            "selectedId = null;",
            "refreshSelection: updateClasses",
            "click.selection-reset",
            "collapseExpansions: true",
            "syncExpansionForSelection",
            "collapseAll: () => setExpandedScale(null)",
            "estimatedLabelWidth",
            "assignLabelLanes",
            ".separation(",
            "labelDemand",
        ):
            self.assertIn(behavior, javascript)
