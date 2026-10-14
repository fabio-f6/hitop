from django.contrib import admin

from .models import EmailNotification, EmailNotificationPreferences


@admin.register(EmailNotificationPreferences)
class EmailNotificationPreferencesAdmin(admin.ModelAdmin):
    list_display = ("user", "email_notifications_enabled", "updated_at")
    search_fields = ("user__username", "user__email")


@admin.register(EmailNotification)
class EmailNotificationAdmin(admin.ModelAdmin):
    list_display = ("notification_type", "recipient_email", "status", "attempts", "created_at")
    list_filter = ("notification_type", "status")
    search_fields = ("logical_key", "recipient_email")
    readonly_fields = tuple(field.name for field in EmailNotification._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
