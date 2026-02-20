from django.contrib import admin
from .models import Record, UserProfile

admin.site.register(Record)

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'user_type', 'professional')
    list_filter = ('user_type',)