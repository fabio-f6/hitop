import logging
import re
import traceback
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from polls.models import NormativeDatasetVersion, NormativeParticipant, QuestionnaireSubmission
from polls.normative_test import clear_normative_test_environment
from polls.normative_export import (
    NormativeExportError,
    export_eligible_submissions_to_test_normative,
    export_submission_to_test_normative,
)
from polls.normative_versions import (
    activate_normative_version as activate_normative_version_service,
    create_normative_version as create_normative_version_service,
    get_active_normative_version,
    get_active_normative_participant_count,
    get_normative_participant_counts,
    get_normative_version_details,
    get_normative_versions,
    get_total_normative_participant_count,
    get_unversioned_normative_participant_count,
    prepare_normative_version as prepare_normative_version_service,
)
from website.models import UserProfile
from website.professional_environment import (
    ProfessionalEnvironment,
    archive_patient_response,
    archived_patients_response,
    create_patient_response,
    dashboard_response,
    new_questionnaire_response,
    patient_answers_response,
    patient_submissions_response,
    restore_patient_response,
)
from website.views import (
    export_report_docx_response,
    report_preview_response,
)

from .audit import record_admin_action
from .forms import (MasterResetConfirmationForm, NormativeVersionCreateForm,
                    NormativeTestVersionCreateForm, NormativeTestCleanupForm,
                    ProfessionalTestEnvironmentCleanupForm)
from .health_checks import get_system_health_report
from .models import AdministrativeAuditLog, MASTER_RESET_ACTION
from .monitoring import get_questionnaire_monitoring_report
from .master_reset import (
    MasterResetError,
    get_master_reset_preview,
    perform_master_reset,
)
from .professional_test_cleanup import (
    clear_professional_test_environment,
    get_professional_test_cleanup_preview,
)
from .permissions import administrator_required, can_master_reset, master_reset_required
from .questionnaire_map import build_questionnaire_structure
from .services import (
    ProfessionalStateError,
    approve_professional as approve_professional_service,
    withdraw_professional_access,
)


logger = logging.getLogger(__name__)


def _log_master_reset_failure(exception):
    # Exception messages (including ProtectedError reprs) can contain clinical
    # values. Record types and stack locations only, without request or locals.
    diagnostics = []
    seen = set()
    while exception is not None and id(exception) not in seen:
        seen.add(id(exception))
        frames = traceback.extract_tb(exception.__traceback__)
        diagnostics.append("%s: %s" % (
            type(exception).__name__,
            " -> ".join(f"{frame.filename}:{frame.lineno} ({frame.name})" for frame in frames),
        ))
        exception = exception.__cause__ or exception.__context__
    logger.error("Master Reset abortado; rollback efetuado. %s", " | ".join(diagnostics))


PROFESSIONALS_PER_PAGE = 10
NORMATIVE_VERSIONS_PER_PAGE = 10
AUDIT_LOGS_PER_PAGE = 20
AUDIT_PERIOD_CHOICES = (
    ("", "Qualquer data"),
    ("7", "Últimos 7 dias"),
    ("30", "Últimos 30 dias"),
    ("90", "Últimos 90 dias"),
)


def _professional_queryset():
    return UserProfile.objects.filter(
        user_type="professional",
    ).select_related("user")


def _professional_audit_label(professional):
    return (
        professional.user.get_full_name().strip()
        or professional.user.email
        or professional.user.username
    )


def _normative_version_or_404(version_id):
    try:
        return get_normative_version_details(version_id)
    except NormativeDatasetVersion.DoesNotExist as exception:
        raise Http404 from exception


def _suggest_next_normative_version_name(versions):
    version_numbers = []
    for version in versions:
        match = re.fullmatch(r"v(\d+)", version.name, flags=re.IGNORECASE)
        if match:
            version_numbers.append(int(match.group(1)))
    return f"v{max(version_numbers, default=0) + 1}"


def _validation_error_message(exception):
    return " ".join(exception.messages)


def _normative_version_name_error(exception):
    name_errors = getattr(exception, "error_dict", {}).get("name", ())
    if any(error.code == "unique" for error in name_errors):
        return "Já existe uma versão normativa com este nome."
    return _validation_error_message(exception)


@administrator_required
def dashboard(request):
    professionals = _professional_queryset()
    active_normative_version = get_active_normative_version()
    normative_participant_counts = get_normative_participant_counts()
    questionnaire_monitoring = get_questionnaire_monitoring_report()
    system_health = get_system_health_report(
        active_normative_version=active_normative_version,
        normative_participant_counts=normative_participant_counts,
    )
    return render(
        request,
        "administration/dashboard.html",
        {
            "professional_count": professionals.count(),
            "pending_professional_count": professionals.filter(
                is_verified=False,
                user__is_active=True,
            ).count(),
            "active_normative_version": active_normative_version,
            "active_normative_participant_count": (
                normative_participant_counts["active_version"]
            ),
            "total_normative_participant_count": (
                normative_participant_counts["total"]
            ),
            "unversioned_normative_participant_count": (
                normative_participant_counts["not_in_active_version"]
            ),
            "questionnaire_monitoring": questionnaire_monitoring,
            "system_health": system_health,
            "can_master_reset": can_master_reset(request.user),
        },
    )


@master_reset_required
def system(request):
    return render(request, "administration/system.html")


@master_reset_required
@require_http_methods(["GET", "POST"])
def master_reset(request):
    preview = get_master_reset_preview(request.user)
    form = MasterResetConfirmationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        # check_password uses the configured Django password hasher. The raw
        # password is not retained or passed to the destructive service.
        if not request.user.check_password(form.cleaned_data["password"]):
            form.add_error("password", "A password atual está incorreta.")
        else:
            try:
                perform_master_reset(request.user)
            except MasterResetError as exception:
                _log_master_reset_failure(exception)
                messages.error(request, f"Master Reset abortado: {exception} Nenhuma alteração foi aplicada.")
            except Exception as exception:
                _log_master_reset_failure(exception)
                messages.error(
                    request,
                    "Não foi possível executar o Master Reset. Nenhuma alteração foi aplicada.",
                )
            else:
                messages.success(
                    request,
                    "Master Reset concluído com sucesso. Todos os outros utilizadores "
                    "e aplicações de questionários foram eliminados. A versão normativa "
                    "ativa foi reposta para v1. O histórico de auditoria foi preservado.",
                )
                return redirect("administration:system")

    return render(
        request,
        "administration/master_reset_confirm.html",
        {"form": form, "preview": preview},
    )


@administrator_required
def professional_test_environment(request):
    return dashboard_response(
        request,
        ProfessionalEnvironment.test(request.user),
    )


@administrator_required
@require_POST
def test_export_all_submissions_to_normative(request):
    environment = ProfessionalEnvironment.test(request.user)
    submissions = environment.submission_queryset().filter(
        questionnaire_type="hitop",
        completed=True,
    )
    with transaction.atomic():
        result = export_eligible_submissions_to_test_normative(submissions)
        if result.exported:
            record_admin_action(
                actor=request.user,
                action=(
                    AdministrativeAuditLog.Action
                    .NORMATIVE_TEST_SUBMISSIONS_BULK_EXPORTED
                ),
                object_type=AdministrativeAuditLog.ObjectType.NORMATIVE_TEST,
                object_id=f"owner-{request.user.pk}",
                object_label="Reexportação em lote do Ambiente Profissional de Teste",
                metadata={
                    "submissions_exported": result.exported,
                    "submissions_skipped": result.skipped,
                },
            )
    if result.exported:
        messages.success(
            request,
            f"{result.exported} submissão(ões) adicionada(s) à base normativa de teste; "
            f"{result.skipped} ignorada(s) por não estar(em) elegível(eis) ou já exportada(s).",
        )
    else:
        messages.info(
            request,
            "Não há submissões elegíveis novas para adicionar à base normativa de teste.",
        )
    return redirect("administration:professional_test_environment")


@administrator_required
def test_create_patient(request):
    return create_patient_response(
        request,
        ProfessionalEnvironment.test(request.user),
    )


@administrator_required
def test_archived_patients(request):
    return archived_patients_response(
        request,
        ProfessionalEnvironment.test(request.user),
    )


@administrator_required
@require_POST
def test_archive_patient(request, patient_id):
    return archive_patient_response(
        request,
        ProfessionalEnvironment.test(request.user),
        patient_id,
    )


@administrator_required
@require_POST
def test_restore_patient(request, patient_id):
    return restore_patient_response(
        request,
        ProfessionalEnvironment.test(request.user),
        patient_id,
    )


@administrator_required
def test_patient_submissions(request, patient_id):
    return patient_submissions_response(
        request,
        ProfessionalEnvironment.test(request.user),
        patient_id,
    )


@administrator_required
def test_new_questionnaire(request, patient_id):
    return new_questionnaire_response(
        request,
        ProfessionalEnvironment.test(request.user),
        patient_id,
    )


@administrator_required
def test_patient_answers(request, submission_id):
    return patient_answers_response(
        request,
        ProfessionalEnvironment.test(request.user),
        submission_id,
    )


@administrator_required
def test_report_preview(request, submission_id):
    environment = ProfessionalEnvironment.test(request.user)
    submission = environment.get_submission(submission_id)
    return report_preview_response(request, submission, environment)


@administrator_required
def test_export_report_docx(request, submission_id):
    environment = ProfessionalEnvironment.test(request.user)
    submission = environment.get_submission(submission_id)
    return export_report_docx_response(submission, environment)


@administrator_required
def professionals(request):
    professional_queryset = _professional_queryset()
    selected_status = request.GET.get("status", "all")
    search_query = request.GET.get("q", "").strip()

    if selected_status == "pending":
        professional_queryset = professional_queryset.filter(
            is_verified=False,
            user__is_active=True,
        )
    elif selected_status == "verified":
        professional_queryset = professional_queryset.filter(
            is_verified=True,
            user__is_active=True,
        )
    elif selected_status == "inactive":
        professional_queryset = professional_queryset.filter(
            user__is_active=False,
        )
    else:
        selected_status = "all"

    if search_query:
        for search_term in search_query.split():
            professional_queryset = professional_queryset.filter(
                Q(user__first_name__icontains=search_term)
                | Q(user__last_name__icontains=search_term)
                | Q(user__email__icontains=search_term)
                | Q(user__username__icontains=search_term)
                | Q(cedula_profissional__icontains=search_term)
            )

    professional_queryset = professional_queryset.order_by(
        "-user__date_joined",
        "-pk",
    )
    page_obj = Paginator(
        professional_queryset,
        PROFESSIONALS_PER_PAGE,
    ).get_page(request.GET.get("page"))

    query_parameters = request.GET.copy()
    query_parameters.pop("page", None)

    all_professionals = _professional_queryset()
    return render(
        request,
        "administration/professionals.html",
        {
            "page_obj": page_obj,
            "professionals": page_obj,
            "selected_status": selected_status,
            "search_query": search_query,
            "pagination_query": query_parameters.urlencode(),
            "all_count": all_professionals.count(),
            "pending_count": all_professionals.filter(
                is_verified=False,
                user__is_active=True,
            ).count(),
            "verified_count": all_professionals.filter(
                is_verified=True,
                user__is_active=True,
            ).count(),
            "inactive_count": all_professionals.filter(
                user__is_active=False,
            ).count(),
        },
    )


@administrator_required
def professional_detail(request, professional_id):
    professional = get_object_or_404(
        _professional_queryset(),
        pk=professional_id,
    )
    return render(
        request,
        "administration/professional_detail.html",
        {"professional": professional},
    )


@administrator_required
@require_POST
def approve_professional(request, professional_id):
    try:
        with transaction.atomic():
            professional, changed = approve_professional_service(professional_id)
            if changed:
                record_admin_action(
                    actor=request.user,
                    action=AdministrativeAuditLog.Action.PROFESSIONAL_APPROVED,
                    object_type=AdministrativeAuditLog.ObjectType.PROFESSIONAL,
                    object_id=professional.pk,
                    object_label=_professional_audit_label(professional),
                    metadata={
                        "previous_is_verified": False,
                        "new_is_verified": True,
                    },
                )
    except UserProfile.DoesNotExist as exception:
        raise Http404 from exception
    except ProfessionalStateError as exception:
        messages.error(request, str(exception))
        return redirect(
            "administration:professional_detail",
            professional_id=professional_id,
        )

    if changed:
        messages.success(request, "Profissional aprovado com sucesso.")
    else:
        messages.info(request, "Este profissional já se encontra aprovado.")

    return redirect(
        "administration:professional_detail",
        professional_id=professional.pk,
    )


@administrator_required
@require_http_methods(["GET", "POST"])
def deactivate_professional(request, professional_id):
    professional = get_object_or_404(
        _professional_queryset(),
        pk=professional_id,
    )

    if not professional.is_verified:
        messages.error(
            request,
            "A retirada de acesso aplica-se apenas a profissionais já aprovados.",
        )
        return redirect(
            "administration:professional_detail",
            professional_id=professional.pk,
        )

    if not professional.user.is_active:
        messages.info(request, "Este profissional já tem o acesso retirado.")
        return redirect(
            "administration:professional_detail",
            professional_id=professional.pk,
        )

    if request.method == "POST":
        try:
            with transaction.atomic():
                professional, changed = withdraw_professional_access(professional.pk)
                if changed:
                    record_admin_action(
                        actor=request.user,
                        action=(
                            AdministrativeAuditLog.Action.PROFESSIONAL_ACCESS_REVOKED
                        ),
                        object_type=(
                            AdministrativeAuditLog.ObjectType.PROFESSIONAL
                        ),
                        object_id=professional.pk,
                        object_label=_professional_audit_label(professional),
                        metadata={
                            "previous_is_active": True,
                            "new_is_active": False,
                        },
                    )
        except UserProfile.DoesNotExist as exception:
            raise Http404 from exception
        except ProfessionalStateError as exception:
            messages.error(request, str(exception))
        else:
            if changed:
                messages.success(
                    request,
                    "O acesso do profissional foi retirado.",
                )
        return redirect(
            "administration:professional_detail",
            professional_id=professional.pk,
        )

    return render(
        request,
        "administration/confirm_professional_deactivation.html",
        {"professional": professional},
    )


@administrator_required
def normative(request):
    active_version = get_active_normative_version()
    active_test_version = NormativeDatasetVersion.objects.filter(
        environment=NormativeDatasetVersion.Environment.TEST,
        status=NormativeDatasetVersion.Status.ACTIVE,
    ).first()
    return render(
        request,
        "administration/normative.html",
        {
            "active_version": active_version,
            "total_participant_count": (
                get_total_normative_participant_count()
            ),
            "active_participant_count": (
                get_active_normative_participant_count()
            ),
            "unversioned_participant_count": (
                get_unversioned_normative_participant_count(active_version)
            ),
            "active_test_version": active_test_version,
            "synthetic_participant_count": NormativeParticipant.objects.filter(
                source=NormativeParticipant.Source.SYNTHETIC
            ).count(),
            "test_versions": get_normative_versions(
                NormativeDatasetVersion.Environment.TEST
            ).order_by("-created_at", "-id")[:10],
            "can_clear_professional_test_environment": can_master_reset(request.user),
        },
    )


@administrator_required
@require_http_methods(["GET", "POST"])
def create_test_normative_version(request):
    form = NormativeTestVersionCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                version = create_normative_version_service(
                    form.cleaned_data["name"],
                    environment=NormativeDatasetVersion.Environment.TEST,
                    baseline_version=form.cleaned_data["baseline_version"],
                )
                record_admin_action(
                    actor=request.user,
                    action=AdministrativeAuditLog.Action.NORMATIVE_VERSION_CREATED,
                    object_type=AdministrativeAuditLog.ObjectType.NORMATIVE_VERSION,
                    object_id=version.pk, object_label=version.name,
                    metadata={"environment": "test", "baseline_version": version.baseline_version.name,
                              "participant_count": version.participant_count},
                )
        except ValidationError as exception:
            form.add_error("name", _validation_error_message(exception))
        except IntegrityError:
            form.add_error("name", "Já existe uma versão normativa com este nome.")
        else:
            return redirect("administration:normative_version_detail", version_id=version.pk)
    synthetic_count = NormativeParticipant.objects.filter(
        source=NormativeParticipant.Source.SYNTHETIC
    ).count()
    baseline = form["baseline_version"].value()
    baseline_participant_ids = set()
    if baseline:
        candidate = NormativeDatasetVersion.objects.filter(pk=baseline).first()
        if candidate:
            baseline_participant_ids = set(
                candidate.memberships.values_list("participant_id", flat=True)
            )
    synthetic_participant_ids = set(
        NormativeParticipant.objects.filter(
            source=NormativeParticipant.Source.SYNTHETIC
        ).values_list("pk", flat=True)
    )
    return render(request, "administration/normative_test_version_create.html", {
        "form": form, "synthetic_count": synthetic_count,
        "resulting_count": len(baseline_participant_ids | synthetic_participant_ids),
    })


@administrator_required
@require_http_methods(["GET", "POST"])
def clear_test_normative_environment(request):
    form = NormativeTestCleanupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            result = clear_normative_test_environment()
            record_admin_action(
                actor=request.user,
                action=AdministrativeAuditLog.Action.NORMATIVE_TEST_CLEARED,
                object_type=AdministrativeAuditLog.ObjectType.NORMATIVE_TEST,
                object_id="environment", object_label="Ambiente normativo de teste",
                metadata={"versions_deleted": result.versions,
                          "synthetic_participants_deleted": result.participants,
                          "submissions_reset_for_reexport": result.submissions_reset},
            )
        messages.success(
            request,
            "Base normativa de teste limpa. Pacientes e respostas foram preservados; "
            f"{result.submissions_reset} submissão(ões) exportada(s) pode(m) ser "
            "reintroduzida(s) se continuar(em) elegível(eis).",
        )
        return redirect("administration:normative")
    return render(request, "administration/normative_test_cleanup.html", {"form": form})


@master_reset_required
@require_http_methods(["GET", "POST"])
def clear_professional_test_environment_view(request):
    preview = get_professional_test_cleanup_preview()
    form = ProfessionalTestEnvironmentCleanupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not request.user.check_password(form.cleaned_data["password"]):
            form.add_error("password", "A password atual está incorreta.")
        else:
            try:
                with transaction.atomic():
                    result = clear_professional_test_environment(request.user)
                    record_admin_action(
                        actor=request.user,
                        action=(
                            AdministrativeAuditLog.Action
                            .PROFESSIONAL_TEST_ENVIRONMENT_CLEARED
                        ),
                        object_type=AdministrativeAuditLog.ObjectType.NORMATIVE_TEST,
                        object_id="professional-test-environment",
                        object_label="Ambiente Profissional de Teste",
                        metadata={
                            "patients_deleted": result.patients,
                            "submissions_deleted": result.submissions,
                            "test_versions_deleted": result.normative_test_versions,
                            "synthetic_participants_deleted": result.synthetic_participants,
                        },
                    )
            except Exception:
                messages.error(
                    request,
                    "Não foi possível apagar o Ambiente Profissional de Teste. "
                    "Nenhuma alteração foi aplicada.",
                )
            else:
                messages.success(
                    request,
                    "Ambiente Profissional de Teste apagado. Os dados de produção "
                    "e o histórico de auditoria foram preservados.",
                )
                return redirect("administration:normative")
    return render(request, "administration/professional_test_cleanup.html", {
        "form": form,
        "preview": preview,
    })


@administrator_required
@require_POST
def test_export_submission_to_normative(request, submission_id):
    environment = ProfessionalEnvironment.test(request.user)
    submission = environment.get_submission(submission_id)
    try:
        with transaction.atomic():
            locked_submission = QuestionnaireSubmission.objects.select_for_update().get(
                pk=submission.pk,
            )
            already_exported = NormativeParticipant.objects.filter(
                source_submission=locked_submission,
            ).exists()
            export_submission_to_test_normative(locked_submission)
            if not already_exported:
                record_admin_action(
                    actor=request.user,
                    action=(
                        AdministrativeAuditLog.Action
                        .NORMATIVE_TEST_SUBMISSION_EXPORTED
                    ),
                    object_type=AdministrativeAuditLog.ObjectType.NORMATIVE_TEST,
                    object_id=locked_submission.pk,
                    object_label="Submission exportada para normativa de teste",
                )
    except NormativeExportError as exception:
        messages.error(request, str(exception))
    else:
        messages.success(request, "Submissão reintroduzida na base normativa de teste.")
    return redirect(
        "administration:test_patient_submissions",
        patient_id=submission.user_id,
    )


@administrator_required
def normative_versions(request):
    versions = get_normative_versions().order_by("-created_at", "-id")
    page_obj = Paginator(
        versions,
        NORMATIVE_VERSIONS_PER_PAGE,
    ).get_page(request.GET.get("page"))
    return render(
        request,
        "administration/normative_versions.html",
        {
            "page_obj": page_obj,
            "versions": page_obj,
        },
    )


@administrator_required
def normative_version_detail(request, version_id):
    version = _normative_version_or_404(version_id)
    return render(
        request,
        "administration/normative_version_detail.html",
        {
            "version": version,
            "unversioned_participant_count": (
                get_unversioned_normative_participant_count(version)
            ),
        },
    )


@administrator_required
@require_http_methods(["GET", "POST"])
def create_normative_version(request):
    existing_versions = list(get_normative_versions())
    suggested_name = _suggest_next_normative_version_name(existing_versions)

    if request.method == "POST":
        form = NormativeVersionCreateForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    version = create_normative_version_service(
                        form.cleaned_data["name"]
                    )
                    record_admin_action(
                        actor=request.user,
                        action=(
                            AdministrativeAuditLog.Action.NORMATIVE_VERSION_CREATED
                        ),
                        object_type=(
                            AdministrativeAuditLog.ObjectType.NORMATIVE_VERSION
                        ),
                        object_id=version.pk,
                        object_label=version.name,
                        metadata={
                            "new_status": version.status,
                            "participant_count": version.participant_count,
                        },
                    )
            except ValidationError as exception:
                form.add_error(
                    "name",
                    _normative_version_name_error(exception),
                )
            except IntegrityError:
                form.add_error(
                    "name",
                    "Já existe uma versão normativa com este nome.",
                )
            else:
                messages.success(
                    request,
                    "Versão normativa criada como rascunho.",
                )
                return redirect(
                    "administration:normative_version_detail",
                    version_id=version.pk,
                )
    else:
        form = NormativeVersionCreateForm(initial={"name": suggested_name})

    return render(
        request,
        "administration/normative_version_create.html",
        {
            "form": form,
            "suggested_name": suggested_name,
        },
    )


@administrator_required
@require_http_methods(["GET", "POST"])
def prepare_normative_version(request, version_id):
    version = _normative_version_or_404(version_id)

    if request.method == "POST":
        try:
            with transaction.atomic():
                previously_prepared = version.prepared_at is not None
                result = prepare_normative_version_service(version)
                version.refresh_from_db(fields=["status", "prepared_at"])
                record_admin_action(
                    actor=request.user,
                    action=(
                        AdministrativeAuditLog.Action.NORMATIVE_VERSION_PREPARED
                    ),
                    object_type=(
                        AdministrativeAuditLog.ObjectType.NORMATIVE_VERSION
                    ),
                    object_id=version.pk,
                    object_label=version.name,
                    metadata={
                        "previously_prepared": previously_prepared,
                        "new_status": version.status,
                        "participant_count": result.participant_count,
                        "scale_score_count": result.scale_score_count,
                        "spectrum_score_count": result.spectrum_score_count,
                    },
                )
        except ValidationError as exception:
            messages.error(request, _validation_error_message(exception))
        else:
            messages.success(
                request,
                "Versão preparada com sucesso: "
                f"{result.participant_count} participantes, "
                f"{result.scale_score_count} scores de escalas e "
                f"{result.spectrum_score_count} scores de espectros.",
            )
        return redirect(
            "administration:normative_version_detail",
            version_id=version.pk,
        )

    if version.status != NormativeDatasetVersion.Status.DRAFT:
        messages.error(
            request,
            "Apenas uma versão em rascunho pode ser preparada.",
        )
        return redirect(
            "administration:normative_version_detail",
            version_id=version.pk,
        )

    return render(
        request,
        "administration/confirm_normative_version_preparation.html",
        {"version": version},
    )


@administrator_required
@require_http_methods(["GET", "POST"])
def activate_normative_version(request, version_id):
    version = _normative_version_or_404(version_id)

    if request.method == "POST":
        try:
            with transaction.atomic():
                previous_status = version.status
                previous_active_version = get_active_normative_version()
                activated_version = activate_normative_version_service(version)
                if previous_status != NormativeDatasetVersion.Status.ACTIVE:
                    record_admin_action(
                        actor=request.user,
                        action=(
                            AdministrativeAuditLog.Action.NORMATIVE_VERSION_ACTIVATED
                        ),
                        object_type=(
                            AdministrativeAuditLog.ObjectType.NORMATIVE_VERSION
                        ),
                        object_id=activated_version.pk,
                        object_label=activated_version.name,
                        metadata={
                            "previous_status": previous_status,
                            "new_status": activated_version.status,
                            "participant_count": (
                                activated_version.participant_count
                            ),
                            "previous_active_version_id": (
                                previous_active_version.pk
                                if previous_active_version is not None
                                else None
                            ),
                            "previous_active_version_label": (
                                previous_active_version.name
                                if previous_active_version is not None
                                else None
                            ),
                        },
                    )
        except ValidationError as exception:
            messages.error(request, _validation_error_message(exception))
        else:
            messages.success(
                request,
                f"A versão {activated_version.name} está agora ativa.",
            )
        return redirect(
            "administration:normative_version_detail",
            version_id=version.pk,
        )

    can_activate = (
        version.status == NormativeDatasetVersion.Status.DRAFT
        and version.prepared_at is not None
    )
    if not can_activate:
        messages.error(
            request,
            "A versão deve estar preparada e em rascunho antes da ativação.",
        )
        return redirect(
            "administration:normative_version_detail",
            version_id=version.pk,
        )

    return render(
        request,
        "administration/confirm_normative_version_activation.html",
        {
            "version": version,
            "active_version": get_active_normative_version(),
        },
    )


@administrator_required
@require_http_methods(["GET"])
def audit(request):
    logs = AdministrativeAuditLog.objects.select_related("actor")
    selected_action = request.GET.get("action", "").strip()
    selected_actor = request.GET.get("actor", "").strip()
    selected_period = request.GET.get("period", "").strip()
    search_query = request.GET.get("q", "").strip()

    allowed_actions = {*AdministrativeAuditLog.Action.values, MASTER_RESET_ACTION}
    if selected_action in allowed_actions:
        logs = logs.filter(action=selected_action)
    else:
        selected_action = ""

    if selected_actor.isdigit():
        selected_actor = int(selected_actor)
        logs = logs.filter(actor_id=selected_actor)
    else:
        selected_actor = ""

    valid_periods = {value for value, _label in AUDIT_PERIOD_CHOICES if value}
    if selected_period in valid_periods:
        logs = logs.filter(
            created_at__gte=timezone.now() - timedelta(days=int(selected_period))
        )
    else:
        selected_period = ""

    if search_query:
        logs = logs.filter(object_label__icontains=search_query)

    logs = logs.order_by("-created_at", "-id")
    page_obj = Paginator(logs, AUDIT_LOGS_PER_PAGE).get_page(
        request.GET.get("page")
    )
    query_parameters = request.GET.copy()
    query_parameters.pop("page", None)

    actor_options = (
        get_user_model()
        .objects.filter(administrative_audit_logs__isnull=False)
        .distinct()
        .order_by("first_name", "last_name", "username")
    )

    return render(
        request,
        "administration/audit.html",
        {
            "page_obj": page_obj,
            "audit_logs": page_obj,
            "action_choices": (
                *AdministrativeAuditLog.Action.choices,
                (MASTER_RESET_ACTION, "Master Reset"),
            ),
            "actor_options": actor_options,
            "period_choices": AUDIT_PERIOD_CHOICES,
            "selected_action": selected_action,
            "selected_actor": selected_actor,
            "selected_period": selected_period,
            "search_query": search_query,
            "pagination_query": query_parameters.urlencode(),
        },
    )


@administrator_required
@require_http_methods(["GET"])
def questionnaire_monitoring(request):
    return render(
        request,
        "administration/questionnaire_monitoring.html",
        get_questionnaire_monitoring_report(),
    )


@administrator_required
@require_http_methods(["GET"])
def system_health(request):
    return render(
        request,
        "administration/system_health.html",
        get_system_health_report(),
    )


@administrator_required
@require_http_methods(["GET"])
def questionnaire_map(request):
    return render(
        request,
        "administration/questionnaire_map.html",
        {"questionnaire_map": build_questionnaire_structure()},
    )
