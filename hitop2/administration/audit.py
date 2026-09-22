from django.core.exceptions import ValidationError

from .models import AdministrativeAuditLog


_ALLOWED_METADATA_KEYS = {
    AdministrativeAuditLog.Action.PROFESSIONAL_APPROVED: {
        "previous_is_verified",
        "new_is_verified",
    },
    AdministrativeAuditLog.Action.PROFESSIONAL_ACCESS_REVOKED: {
        "previous_is_active",
        "new_is_active",
    },
    AdministrativeAuditLog.Action.NORMATIVE_VERSION_CREATED: {
        "new_status",
        "participant_count",
    },
    AdministrativeAuditLog.Action.NORMATIVE_VERSION_PREPARED: {
        "previously_prepared",
        "new_status",
        "participant_count",
        "scale_score_count",
        "spectrum_score_count",
    },
    AdministrativeAuditLog.Action.NORMATIVE_VERSION_ACTIVATED: {
        "previous_status",
        "new_status",
        "participant_count",
        "previous_active_version_id",
        "previous_active_version_label",
    },
}


def record_admin_action(
    *,
    actor,
    action,
    object_type,
    object_id,
    object_label,
    metadata=None,
    result=AdministrativeAuditLog.Result.SUCCESS,
):
    """Create one successful, deliberately minimal administrative audit entry."""
    if actor is None or not getattr(actor, "pk", None):
        raise ValidationError("A auditoria administrativa requer um administrador.")

    if action not in AdministrativeAuditLog.Action.values:
        raise ValidationError("Código de ação administrativa inválido.")

    if object_type not in AdministrativeAuditLog.ObjectType.values:
        raise ValidationError("Tipo de objeto administrativo inválido.")

    if result != AdministrativeAuditLog.Result.SUCCESS:
        raise ValidationError("Apenas ações administrativas concluídas são registadas.")

    metadata = dict(metadata or {})
    unexpected_keys = set(metadata) - _ALLOWED_METADATA_KEYS[action]
    if unexpected_keys:
        raise ValidationError(
            "A metadata contém campos não permitidos para esta ação: "
            + ", ".join(sorted(unexpected_keys))
        )

    entry = AdministrativeAuditLog(
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        object_label=str(object_label).strip(),
        result=result,
        metadata=metadata,
    )
    entry.full_clean()
    entry.save()
    return entry
