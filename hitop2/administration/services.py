from django.db import transaction

from website.models import UserProfile


class ProfessionalStateError(Exception):
    """Raised when an administrative transition is not valid."""


def _get_locked_professional(professional_id):
    return (
        UserProfile.objects.select_for_update()
        .select_related("user")
        .get(pk=professional_id, user_type="professional")
    )


@transaction.atomic
def approve_professional(professional_id):
    """Verify an active pending professional, rechecking state under a lock."""
    professional = _get_locked_professional(professional_id)

    if not professional.user.is_active:
        raise ProfessionalStateError(
            "Não é possível aprovar um profissional com a conta inativa."
        )

    if professional.is_verified:
        return professional, False

    professional.is_verified = True
    professional.save(update_fields=["is_verified"])
    return professional, True


@transaction.atomic
def withdraw_professional_access(professional_id):
    """Disable login for a previously verified professional without deleting it."""
    professional = _get_locked_professional(professional_id)

    if not professional.is_verified:
        raise ProfessionalStateError(
            "Apenas profissionais anteriormente aprovados podem ter o acesso retirado."
        )

    if not professional.user.is_active:
        return professional, False

    professional.user.is_active = False
    professional.user.save(update_fields=["is_active"])
    return professional, True
