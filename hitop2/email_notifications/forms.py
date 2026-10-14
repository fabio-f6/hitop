from django import forms

from .models import EmailNotificationPreferences


class EmailNotificationPreferencesForm(forms.ModelForm):
    class Meta:
        model = EmailNotificationPreferences
        fields = (
            "email_notifications_enabled",
            "professional_registration",
            "questionnaire_completed",
            "collection_daily_summary",
        )
        widgets = {name: forms.CheckboxInput(attrs={"class": "form-check-input"}) for name in fields}
