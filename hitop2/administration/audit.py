from django.core.exceptions import ValidationError

from .models import AdministrativeAuditLog, MASTER_RESET_ACTION, SYSTEM_OBJECT_TYPE


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
        "environment",
        "baseline_version",
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
    AdministrativeAuditLog.Action.NORMATIVE_TEST_SYNTHETIC_BATCH_CREATED: {
        "quantity_requested", "quantity_eligible", "quantity_exported",
        "base_seed", "response_profile",
    },
    AdministrativeAuditLog.Action.NORMATIVE_TEST_CLEARED: {
        "versions_deleted", "synthetic_participants_deleted",
        "submissions_reset_for_reexport",
    },
    AdministrativeAuditLog.Action.NORMATIVE_TEST_SUBMISSION_EXPORTED: set(),
    AdministrativeAuditLog.Action.NORMATIVE_TEST_SUBMISSIONS_BULK_EXPORTED: {
        "submissions_exported",
        "submissions_skipped",
    },
    AdministrativeAuditLog.Action.PROFESSIONAL_TEST_ENVIRONMENT_CLEARED: {
        "patients_deleted",
        "submissions_deleted",
        "test_versions_deleted",
        "synthetic_participants_deleted",
    },
    MASTER_RESET_ACTION: {
        "users_deleted",
        "submissions_deleted",
        "test_submissions_deleted",
        "previous_active_normative_version",
        "restored_normative_version",
        "restored_normative_participant_count",
        "test_versions_deleted",
        "synthetic_participants_deleted",
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

    if action not in {*AdministrativeAuditLog.Action.values, MASTER_RESET_ACTION}:
        raise ValidationError("Código de ação administrativa inválido.")

    if object_type not in {
        *AdministrativeAuditLog.ObjectType.values,
        SYSTEM_OBJECT_TYPE,
    }:
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
    # Master Reset uses stable audit codes without changing TextChoices (and
    # therefore without a schema-state-only migration). They were validated
    # explicitly above; all other model fields still receive normal validation.
    excluded_choice_fields = []
    if action == MASTER_RESET_ACTION:
        excluded_choice_fields.append("action")
    if object_type == SYSTEM_OBJECT_TYPE:
        excluded_choice_fields.append("object_type")
    entry.full_clean(exclude=excluded_choice_fields)
    entry.save()
    return entry
