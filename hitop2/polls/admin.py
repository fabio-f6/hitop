from django.contrib import admin
from .models import Question, UserAnswer

admin.site.register(Question)
admin.site.register(UserAnswer)