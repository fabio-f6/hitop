"""Full report-context integration using an isolated test database only."""
from django.contrib.auth.models import User
from django.test import TestCase
from polls.models import (Spectra, Subfactor, Scale, Question, QuestionnaireSubmission,UserAnswer,
                          NormativeParticipant,NormativeDatasetVersion,NormativeDatasetMembership,
                          NormativeScaleScore,NormativeSpectrumScore)
from polls.normative_versions import activate_normative_version, get_or_assign_report_normative_version
from django.utils import timezone
from website.views import _build_report_context
from . import reference as ref


class ReportOracleTests(TestCase):
    def setUp(self):
        self.prof = User.objects.create_user(username="oracle-prof")
        pp = self.prof.userprofile
        pp.user_type="professional"
        pp.save()
        self.patient = User.objects.create_user(username="oracle-patient")
        p = self.patient.userprofile
        p.professional=self.prof
        p.save()
        self.spectrum=Spectra.objects.create(name="Internalizing")
        sf=Subfactor.objects.create(name="Fear",spectra=self.spectrum)
        self.scale=Scale.objects.create(name="Agoraphobia",subfactor=sf)
        self.questions=[Question.objects.create(scale=self.scale,item_code=f"oracle_{i}",question_text=f"Item {i}") for i in range(4)]
        self.version=self.make_version("oracle-v1",[1,2,2,3,4])
        self.sub=QuestionnaireSubmission.objects.create(user=self.patient,title="Oracle",completed=True)
        self.sub.spectra.add(self.spectrum)
        for q,a in zip(self.questions,[1,2,2,3]):
            UserAnswer.objects.create(user=self.patient,submission=self.sub,question=q,answer=str(a))

    def make_version(self,name,values,environment="production"):
        v=NormativeDatasetVersion.objects.create(name=name,environment=environment)
        for score in values:
            p=NormativeParticipant.objects.create(source="synthetic" if environment=="test" else "real")
            NormativeDatasetMembership.objects.create(version=v,participant=p)
            NormativeScaleScore.objects.create(version=v,participant=p,scale=self.scale,raw_score=score)
            NormativeSpectrumScore.objects.create(version=v,participant=p,spectrum=self.spectrum,raw_score=score)
        v.prepared_at=timezone.now()
        v.save()
        return activate_normative_version(v)

    def test_submission_pinning_percentile_and_report_context(self):
        expected=ref.scale([1,2,2,3])["score"]
        expected_p=ref.percentile([1,2,2,3,4],expected)
        self.assertEqual((expected,expected_p),(2,60))  # Hand-calculated: 8/4; 3/5.
        get_or_assign_report_normative_version(self.sub)
        context=_build_report_context(self.sub)
        self.assertEqual(context["scale_scores"][self.scale]["score"],expected)
        item=context["grouped_scores"]["internalizing"][0]
        self.assertEqual((item["score"],item["percentile"]),(expected,expected_p))
        self.assertEqual(context["spectrum_results"][self.spectrum]["percentile"],expected_p)
        self.make_version("oracle-v2",[4,4,4])
        self.make_version("oracle-test",[1,1,1],environment="test")
        self.sub.refresh_from_db()
        get_or_assign_report_normative_version(self.sub)
        after=_build_report_context(self.sub)
        self.assertEqual(after["normative_version"].pk,self.version.pk)
        self.assertEqual(after["grouped_scores"]["internalizing"][0]["percentile"],60)
        self.assertEqual(after["global_chart_data"]["items"][0]["percentile"],60)
        from django.test import RequestFactory
        from website.professional_environment import ProfessionalEnvironment
        from website.views import report_preview_response
        request=RequestFactory().get("/oracle-report/")
        request.user=self.prof
        response=report_preview_response(request,self.sub,ProfessionalEnvironment.clinical(self.prof))
        html=response.content.decode()
        self.assertRegex(html,r">\s*60\s*<")
        self.assertIn("oracle-v1",html)
        self.assertNotIn("oracle-v2",html)

    def test_same_version_ignores_test_distribution(self):
        from polls.percentiles import calculate_percentile
        before=calculate_percentile(self.scale,2,version=self.version)
        self.make_version("test-extra",[1,1,1],environment="test")
        self.assertEqual(calculate_percentile(self.scale,2,version=self.version),before)
