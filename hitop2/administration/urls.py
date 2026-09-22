from django.urls import path

from . import views


app_name = "administration"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
]

