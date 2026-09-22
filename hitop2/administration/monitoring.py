from django.db.models import Count, Q

from polls.models import QuestionnaireSubmission


def get_questionnaire_monitoring_summary():
    """Return operational submission metrics without loading clinical rows."""
    status = QuestionnaireSubmission.NormativeStatus
    metrics = QuestionnaireSubmission.objects.aggregate(
        total=Count("id"),
        open_count=Count("id", filter=Q(is_open=True)),
        completed_count=Count("id", filter=Q(completed=True)),
        pending=Count("id", filter=Q(normative_status=status.PENDING)),
        pending_incomplete=Count(
            "id",
            filter=Q(
                normative_status=status.PENDING,
                completed=False,
            ),
        ),
        completed_pending=Count(
            "id",
            filter=Q(
                normative_status=status.PENDING,
                completed=True,
            ),
        ),
        ineligible=Count("id", filter=Q(normative_status=status.INELIGIBLE)),
        exported=Count("id", filter=Q(normative_status=status.EXPORTED)),
        completed_open=Count(
            "id",
            filter=Q(completed=True, is_open=True),
        ),
        exported_without_timestamp=Count(
            "id",
            filter=Q(
                normative_status=status.EXPORTED,
                normative_exported_at__isnull=True,
            ),
        ),
        timestamp_without_exported_status=Count(
            "id",
            filter=(
                ~Q(normative_status=status.EXPORTED)
                & Q(normative_exported_at__isnull=False)
            ),
        ),
        exported_incomplete=Count(
            "id",
            filter=Q(
                normative_status=status.EXPORTED,
                completed=False,
            ),
        ),
        ineligible_incomplete=Count(
            "id",
            filter=Q(
                normative_status=status.INELIGIBLE,
                completed=False,
            ),
        ),
    )
    metrics["open"] = metrics.pop("open_count")
    metrics["completed"] = metrics.pop("completed_count")
    return metrics


def get_questionnaire_operational_alerts(summary=None):
    """Build objective aggregate alerts from a monitoring summary."""
    summary = summary or get_questionnaire_monitoring_summary()
    alerts = []

    alert_definitions = (
        (
            "warning",
            "completed_normative_pending",
            "Questionários concluídos ainda pendentes",
            (
                "Submissões concluídas que continuam pendentes de avaliação ou "
                "exportação normativa. Este estado também pode resultar de "
                "critérios sociodemográficos ausentes ou ambíguos."
            ),
            "completed_pending",
        ),
        (
            "error",
            "completed_submission_still_open",
            "Questionários concluídos ainda abertos",
            (
                "O fluxo normal fecha a submissão quando a marca como concluída."
            ),
            "completed_open",
        ),
        (
            "error",
            "exported_without_timestamp",
            "Exportações sem data de exportação",
            (
                "Submissões marcadas como exportadas sem normative_exported_at."
            ),
            "exported_without_timestamp",
        ),
        (
            "error",
            "export_timestamp_without_exported_status",
            "Data de exportação num estado não exportado",
            (
                "Submissões com normative_exported_at preenchido cujo estado "
                "normativo não é exported."
            ),
            "timestamp_without_exported_status",
        ),
        (
            "error",
            "exported_submission_not_completed",
            "Exportações associadas a questionários não concluídos",
            (
                "A exportação normativa só deve ocorrer após a conclusão do "
                "questionário."
            ),
            "exported_incomplete",
        ),
        (
            "error",
            "ineligible_submission_not_completed",
            "Não elegíveis associados a questionários não concluídos",
            (
                "A avaliação de elegibilidade normativa só deve terminar após a "
                "conclusão do questionário."
            ),
            "ineligible_incomplete",
        ),
    )

    for severity, code, title, description, metric in alert_definitions:
        count = summary[metric]
        if count:
            alerts.append(
                {
                    "severity": severity,
                    "code": code,
                    "title": title,
                    "description": description,
                    "count": count,
                }
            )

    return alerts


def get_questionnaire_monitoring_report():
    summary = get_questionnaire_monitoring_summary()
    return {
        "summary": summary,
        "alerts": get_questionnaire_operational_alerts(summary),
        "failure_tracking_available": False,
    }
