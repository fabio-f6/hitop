from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_http_methods

from polls.normative_versions import (
    get_active_normative_version,
    get_normative_participant_counts,
)
from website.models import UserProfile

from .permissions import administrator_required
from .services import (
    ProfessionalStateError,
    approve_professional as approve_professional_service,
    withdraw_professional_access,
)


PROFESSIONALS_PER_PAGE = 10


def _professional_queryset():
    return UserProfile.objects.filter(
        user_type="professional",
    ).select_related("user")


@administrator_required
def dashboard(request):
    professionals = _professional_queryset()
    active_normative_version = get_active_normative_version()
    normative_participant_counts = get_normative_participant_counts()

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
        },
    )


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
        professional, changed = approve_professional_service(professional_id)
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
            professional, changed = withdraw_professional_access(professional.pk)
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
