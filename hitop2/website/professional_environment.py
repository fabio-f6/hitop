from dataclasses import dataclass

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from polls.models import NormativeParticipant, QuestionnaireSubmission, UserAnswer
from polls.normative_export import evaluate_normative_eligibility
from polls.normative_versions import (
    NormativeVersionError,
    get_or_assign_report_normative_version,
)
from polls.simulation import SimulationConfigurationError, simulate_submission_batch
from administration.audit import record_admin_action
from administration.models import AdministrativeAuditLog

from .forms import CreatePatientForm, NewQuestionnaireForm
from .models import UserProfile


TEST_ENVIRONMENT_NOTICE = (
    "Ambiente de Teste Profissional — os dados criados nesta área destinam-se "
    "exclusivamente a simulação."
)


@dataclass(frozen=True)
class ProfessionalEnvironment:
    owner: object
    is_test_environment: bool
    dashboard_url_name: str
    create_patient_url_name: str
    archived_patients_url_name: str
    archive_patient_url_name: str
    restore_patient_url_name: str
    patient_submissions_url_name: str
    new_questionnaire_url_name: str
    patient_answers_url_name: str
    report_preview_url_name: str
    export_report_url_name: str

    @classmethod
    def clinical(cls, owner):
        return cls(
            owner=owner,
            is_test_environment=False,
            dashboard_url_name="website:dashboard",
            create_patient_url_name="website:create_patient",
            archived_patients_url_name="website:archived_patients",
            archive_patient_url_name="website:archive_patient",
            restore_patient_url_name="website:restore_patient",
            patient_submissions_url_name="website:patient_submissions",
            new_questionnaire_url_name="website:new_questionnaire",
            patient_answers_url_name="website:patient_answers",
            report_preview_url_name="website:report_preview",
            export_report_url_name="website:export_report_docx",
        )

    @classmethod
    def test(cls, owner):
        return cls(
            owner=owner,
            is_test_environment=True,
            dashboard_url_name="administration:professional_test_environment",
            create_patient_url_name="administration:test_create_patient",
            archived_patients_url_name="administration:test_archived_patients",
            archive_patient_url_name="administration:test_archive_patient",
            restore_patient_url_name="administration:test_restore_patient",
            patient_submissions_url_name="administration:test_patient_submissions",
            new_questionnaire_url_name="administration:test_new_questionnaire",
            patient_answers_url_name="administration:test_patient_answers",
            report_preview_url_name="administration:test_report_preview",
            export_report_url_name="administration:test_export_report_docx",
        )

    @property
    def temporary_credentials_key(self):
        if self.is_test_environment:
            return "test_environment_temp_credentials"
        return "temp_credentials"

    def patient_profiles(self):
        if self.is_test_environment:
            return UserProfile.objects.filter(
                user_type="patient",
                is_test_data=True,
                professional__isnull=True,
                test_environment_owner=self.owner,
            )
        return UserProfile.objects.filter(
            user_type="patient",
            is_test_data=False,
            professional=self.owner,
            test_environment_owner__isnull=True,
        )

    def get_patient_profile(self, profile_id):
        return get_object_or_404(self.patient_profiles(), pk=profile_id)

    def get_patient_by_user_id(self, user_id):
        profile = get_object_or_404(
            self.patient_profiles().select_related("user"),
            user_id=user_id,
        )
        return profile.user

    def submission_queryset(self):
        submissions = QuestionnaireSubmission.objects.filter(
            user__userprofile__in=self.patient_profiles(),
        )
        if self.is_test_environment:
            # Include legacy test submissions created before the submission-level
            # marker was consistently set, while remaining scoped to this owner's
            # test patient profiles.
            submissions = submissions.filter(
                Q(is_test_data=True)
                | Q(user__userprofile__is_test_data=True)
                | ~Q(simulation_mode="normal")
            )
        else:
            # Legacy simulated records are structurally identifiable through
            # simulation_mode even though they predate the is_test_data field.
            submissions = submissions.filter(
                is_test_data=False,
                simulation_mode="normal",
            )
        return submissions

    def get_submission(self, submission_id):
        return get_object_or_404(
            self.submission_queryset().select_related("user__userprofile"),
            pk=submission_id,
        )

    def template_context(self):
        return {
            "is_test_environment": self.is_test_environment,
            "test_environment_notice": (
                TEST_ENVIRONMENT_NOTICE if self.is_test_environment else ""
            ),
            "dashboard_url_name": self.dashboard_url_name,
            "create_patient_url_name": self.create_patient_url_name,
            "archived_patients_url_name": self.archived_patients_url_name,
            "archive_patient_url_name": self.archive_patient_url_name,
            "restore_patient_url_name": self.restore_patient_url_name,
            "patient_submissions_url_name": self.patient_submissions_url_name,
            "new_questionnaire_url_name": self.new_questionnaire_url_name,
            "patient_answers_url_name": self.patient_answers_url_name,
            "report_preview_url_name": self.report_preview_url_name,
            "export_report_url_name": self.export_report_url_name,
        }


def _safe_simulation_configuration(form, *, is_test_data):
    if is_test_data:
        configuration = form.simulation_configuration()
    else:
        # This backend normalization is intentional even though the clinical form
        # does not expose or bind simulation fields.
        configuration = form.simulation_defaults.copy()
    return {
        key: value for key, value in configuration.items()
        if key not in {"simulation_quantity", "include_in_normative_test"}
    }


@transaction.atomic
def _create_patient_and_first_submission(form, environment):
    user = form.save()
    profile = user.userprofile
    profile.user_type = "patient"
    profile.is_test_data = environment.is_test_environment
    profile.professional = None if environment.is_test_environment else environment.owner
    profile.test_environment_owner = (
        environment.owner if environment.is_test_environment else None
    )
    profile.save(update_fields=[
        "user_type",
        "is_test_data",
        "professional",
        "test_environment_owner",
    ])

    submission = _create_submission(form, profile, environment)
    return user, submission


@transaction.atomic
def _create_submission(form, patient_profile, environment):
    configuration = _safe_simulation_configuration(
        form, is_test_data=environment.is_test_environment,
    )
    quantity = form.cleaned_data.get("simulation_quantity", 1)
    if configuration["simulation_mode"] == "normal":
        quantity = 1
    submissions = []
    for index in range(quantity):
        title = form.cleaned_data["title"]
        if quantity > 1:
            title = f"{title} ({index + 1}/{quantity})"
        submission = QuestionnaireSubmission.objects.create(
            user=patient_profile.user, questionnaire_type="hitop", title=title,
            completed=False, is_open=True,
            is_test_data=environment.is_test_environment, **configuration,
        )
        if get_or_assign_report_normative_version(submission) is None:
            raise NormativeVersionError(
                "Não existe uma versão normativa ativa aplicável. "
                "Ative uma versão antes de criar novas submissões."
            )
        submission.spectra.set(form.cleaned_data["spectra"])
        submissions.append(submission)

    if configuration["simulation_mode"] != "normal":
        summary = simulate_submission_batch(
            submissions,
            base_seed=configuration["simulation_seed"],
            export_to_normative_test=form.cleaned_data.get("include_in_normative_test", False),
        )
        record_admin_action(
            actor=environment.owner,
            action=AdministrativeAuditLog.Action.NORMATIVE_TEST_SYNTHETIC_BATCH_CREATED,
            object_type=AdministrativeAuditLog.ObjectType.NORMATIVE_TEST,
            object_id=f"batch-{submissions[0].pk}", object_label="Batch de simulação normativa",
            metadata={
                "quantity_requested": quantity, "quantity_eligible": summary["eligible"],
                "quantity_exported": summary["exported"], "base_seed": configuration["simulation_seed"],
                "response_profile": configuration["simulation_response_profile"],
            },
        )
        submissions[0].simulation_batch_summary = summary
    return submissions[0]


def dashboard_response(request, environment):
    all_patients = environment.patient_profiles()
    active_patients = all_patients.filter(
        archived_at__isnull=True,
    ).select_related("user").order_by("user__username", "id")
    patient_page = Paginator(active_patients, 10).get_page(request.GET.get("page"))

    patient_cards = []
    for patient in patient_page:
        submissions = environment.submission_queryset().filter(
            user=patient.user,
        ).order_by("-started_at")
        last_submission = submissions.first()
        patient_cards.append({
            "profile": patient,
            "submission_count": submissions.count(),
            "open_count": submissions.filter(is_open=True).count(),
            "last_submission": last_submission,
            "spectra": last_submission.spectra.all() if last_submission else [],
        })

    submissions = environment.submission_queryset()
    context = {
        "patients": patient_cards,
        "patient_page": patient_page,
        "total_patients": active_patients.count(),
        "archived_patient_count": all_patients.filter(
            archived_at__isnull=False
        ).count(),
        "total_submissions": submissions.count(),
        "open_submissions": submissions.filter(is_open=True).count(),
        **environment.template_context(),
    }
    return render(request, "website/dashboard.html", context)


def create_patient_response(request, environment):
    form_kwargs = {"allow_simulation": environment.is_test_environment}
    if request.method == "POST":
        temporary_credentials = request.session.get(
            environment.temporary_credentials_key
        )
        form = CreatePatientForm(request.POST, **form_kwargs)
        if temporary_credentials:
            form.generated_username = temporary_credentials["username"]
            form.generated_password = temporary_credentials["password"]

        if form.is_valid():
            try:
                user, submission = _create_patient_and_first_submission(
                    form,
                    environment,
                )
            except (SimulationConfigurationError, NormativeVersionError) as error:
                message = error.messages[0] if isinstance(error, NormativeVersionError) else str(error)
                form.add_error(None, message)
            else:
                summary = getattr(submission, "simulation_batch_summary", None)
                if summary:
                    messages.success(
                        request,
                        "Simulações criadas: {created}; elegíveis: {eligible}; "
                        "exportadas para normativa de teste: {exported}; "
                        "ineligíveis: {ineligible}; pendentes: {pending}.".format(**summary),
                    )
                request.session.pop(environment.temporary_credentials_key, None)
                return redirect(
                    environment.patient_submissions_url_name,
                    patient_id=user.id,
                )
    else:
        form = CreatePatientForm(**form_kwargs)
        request.session[environment.temporary_credentials_key] = {
            "username": form.generated_username,
            "password": form.generated_password,
        }

    return render(request, "website/create_patient.html", {
        "form": form,
        **environment.template_context(),
    })


def new_questionnaire_response(request, environment, patient_id):
    patient_profile = environment.get_patient_profile(patient_id)
    form_kwargs = {"allow_simulation": environment.is_test_environment}
    if request.method == "POST":
        form = NewQuestionnaireForm(request.POST, **form_kwargs)
        if form.is_valid():
            try:
                submission = _create_submission(form, patient_profile, environment)
            except (SimulationConfigurationError, NormativeVersionError) as error:
                message = error.messages[0] if isinstance(error, NormativeVersionError) else str(error)
                form.add_error(None, message)
            else:
                summary = getattr(submission, "simulation_batch_summary", None)
                if summary:
                    messages.success(
                        request,
                        "Simulações criadas: {created}; elegíveis: {eligible}; "
                        "exportadas para normativa de teste: {exported}; "
                        "ineligíveis: {ineligible}; pendentes: {pending}.".format(**summary),
                    )
                else:
                    messages.success(request, "Novo questionário criado com sucesso.")
                return redirect(environment.dashboard_url_name)
    else:
        form = NewQuestionnaireForm(**form_kwargs)

    return render(request, "website/new_questionnaire.html", {
        "patient": patient_profile,
        "form": form,
        **environment.template_context(),
    })


def archived_patients_response(request, environment):
    patients = environment.patient_profiles().filter(
        archived_at__isnull=False,
    ).select_related("user").order_by("-archived_at", "user__username", "id")
    patient_page = Paginator(patients, 10).get_page(request.GET.get("page"))
    return render(request, "website/archived_patients.html", {
        "patients": patient_page,
        "patient_page": patient_page,
        "allow_permanent_deletion": not environment.is_test_environment,
        **environment.template_context(),
    })


def archive_patient_response(request, environment, patient_id):
    patient = environment.get_patient_profile(patient_id)
    patient.archived_at = timezone.now()
    patient.save(update_fields=["archived_at"])
    messages.success(request, "Paciente arquivado com sucesso.")
    return redirect(environment.dashboard_url_name)


def restore_patient_response(request, environment, patient_id):
    patient = environment.get_patient_profile(patient_id)
    patient.archived_at = None
    patient.save(update_fields=["archived_at"])
    messages.success(request, "Paciente restaurado com sucesso.")
    return redirect(environment.archived_patients_url_name)


def patient_submissions_response(request, environment, patient_id):
    patient = environment.get_patient_by_user_id(patient_id)
    submissions = list(
        environment.submission_queryset().filter(
            user=patient,
            questionnaire_type="hitop",
        ).select_related("report_normative_version").order_by("-started_at")
    )
    for submission in submissions:
        pinned_version = submission.report_normative_version
        submission.normative_version_name = (
            submission.report_normative_version_name
            or (pinned_version.name if pinned_version else "")
        )
        submission.normative_version_environment = (
            submission.report_normative_version_environment
            or (pinned_version.environment if pinned_version else "")
        )
        submission.normative_version_environment_display = {
            "production": "Produção",
            "test": "Teste",
        }.get(submission.normative_version_environment, "")
        submission.normative_version_was_removed = bool(
            submission.normative_version_name and pinned_version is None
        )
        submission.can_export_to_test_normative = False
        submission.access_link = request.build_absolute_uri(
            reverse("polls:questionnaire_by_token", args=[submission.access_token])
        )
        submission.spectra_list = submission.spectra.all()
        if environment.is_test_environment and submission.completed:
            eligibility = evaluate_normative_eligibility(submission)
            submission.normative_eligibility = eligibility
            if eligibility["eligible"] is True:
                submission.normative_eligibility_state = "eligible"
                submission.can_export_to_test_normative = not (
                    NormativeParticipant.objects.filter(
                        source_submission=submission,
                    ).exists()
                )
            elif eligibility["eligible"] is False:
                submission.normative_eligibility_state = "ineligible"
            else:
                submission.normative_eligibility_state = "pending"

    return render(request, "website/patient_submissions.html", {
        "patient": patient,
        "submissions": submissions,
        "has_open_submission": any(item.is_open for item in submissions),
        **environment.template_context(),
    })


def patient_answers_response(request, environment, submission_id):
    submission = environment.get_submission(submission_id)
    answers = UserAnswer.objects.filter(submission=submission).select_related(
        "question"
    )
    return render(request, "website/patient_answers.html", {
        "patient": submission.user,
        "submission": submission,
        "answers": answers,
        **environment.template_context(),
    })
