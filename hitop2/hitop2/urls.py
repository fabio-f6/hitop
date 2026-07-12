from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),

    # Landing page / autenticação
    path("", include("website.urls", namespace="website")),

    # Questionários
    path("polls/", include("polls.urls", namespace="polls")),
]