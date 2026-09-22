from django.shortcuts import render

from polls.normative_versions import (
    get_active_normative_version,
    get_normative_participant_counts,
)
from website.models import UserProfile

from .permissions import administrator_required


@administrator_required
def dashboard(request):
    professionals = UserProfile.objects.filter(user_type="professional")
    active_normative_version = get_active_normative_version()
    normative_participant_counts = get_normative_participant_counts()

    return render(
        request,
        "administration/dashboard.html",
        {
            "professional_count": professionals.count(),
            "pending_professional_count": professionals.filter(
                is_verified=False,
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

