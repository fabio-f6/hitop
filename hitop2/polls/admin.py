from django.contrib import admin
from .models import Question, QuestionnaireSubmission, UserAnswer


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
