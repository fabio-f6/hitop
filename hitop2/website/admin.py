from django.contrib import admin
from .models import UserProfile

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'user_type', 'is_verified', 'professional')
    list_filter = ('user_type', 'is_verified')
    list_editable = ('is_verified',)
