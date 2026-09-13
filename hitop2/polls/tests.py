from django.test import TestCase


class QuestionnaireLinkTests(TestCase):
    def test_malformed_questionnaire_uuid_shows_invalid_link_page(self):
        session = self.client.session
        session["submission_id"] = 1
        session["anonymous_questionnaire"] = True
        session.save()

        response = self.client.get("/polls/access/not-a-valid-uuid/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Link inválido")
        self.assertNotIn("submission_id", self.client.session)
        self.assertNotIn("anonymous_questionnaire", self.client.session)
