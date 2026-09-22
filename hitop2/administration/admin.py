from django.contrib import admin

from .models import AdministrativeAuditLog


@admin.register(AdministrativeAuditLog)
class AdministrativeAuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "actor",
        "action",
        "object_type",
        "object_label",
        "result",
    )
    list_filter = ("action", "object_type", "result", "created_at")
    search_fields = (
        "actor__username",
        "actor__email",
        "object_id",
        "object_label",
    )
    ordering = ("-created_at", "-id")
    date_hierarchy = "created_at"
    readonly_fields = (
        "id",
        "actor",
        "action",
        "object_type",
        "object_id",
        "object_label",
        "result",
        "metadata",
        "created_at",
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
