from django.urls import path

from . import views


app_name = "administration"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("professionals/", views.professionals, name="professionals"),
    path(
        "professionals/<int:professional_id>/",
        views.professional_detail,
        name="professional_detail",
    ),
    path(
        "professionals/<int:professional_id>/approve/",
        views.approve_professional,
        name="approve_professional",
    ),
    path(
        "professionals/<int:professional_id>/deactivate/",
        views.deactivate_professional,
        name="deactivate_professional",
    ),
]
