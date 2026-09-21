from django.contrib import admin
from .models import (
    NormativeDatasetVersion,
    Question,
    QuestionnaireSubmission,
    UserAnswer,
)


@admin.register(QuestionnaireSubmission)
class QuestionnaireSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "title",
        "completed",
        "normative_status",
        "normative_exported_at",
        "started_at",
    )
    list_filter = ("normative_status", "completed", "questionnaire_type")
    search_fields = ("user__username", "title", "access_token")
    ordering = ("-started_at",)

admin.site.register(Question)
admin.site.register(UserAnswer)


@admin.register(NormativeDatasetVersion)
class NormativeDatasetVersionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "status",
        "snapshot_participant_count",
        "created_at",
        "prepared_at",
        "activated_at",
    )
    list_filter = ("status",)
    search_fields = ("name",)
    ordering = ("-created_at", "-id")
    readonly_fields = (
        "name",
        "status",
        "created_at",
        "prepared_at",
        "activated_at",
        "snapshot_participant_count",
    )
    fields = readonly_fields

    @admin.display(description="Participantes")
    def snapshot_participant_count(self, obj):
        return obj.participant_count

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return obj is not None

    def has_delete_permission(self, request, obj=None):
        return False
