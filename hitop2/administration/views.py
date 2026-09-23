import re
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

from polls.models import NormativeDatasetVersion
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
from .forms import NormativeVersionCreateForm
from .health_checks import get_system_health_report
from .models import AdministrativeAuditLog
from .monitoring import get_questionnaire_monitoring_report
from .permissions import administrator_required
from .questionnaire_map import build_questionnaire_structure
from .services import (
    ProfessionalStateError,
    approve_professional as approve_professional_service,
    withdraw_professional_access,
)


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
        },
    )


@administrator_required
def professional_test_environment(request):
    return dashboard_response(
        request,
        ProfessionalEnvironment.test(request.user),
    )


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
        },
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

    if selected_action in AdministrativeAuditLog.Action.values:
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
            "action_choices": AdministrativeAuditLog.Action.choices,
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
