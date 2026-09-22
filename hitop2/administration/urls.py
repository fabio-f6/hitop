from django.urls import path

from . import views


app_name = "administration"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("audit/", views.audit, name="audit"),
    path(
        "questionnaires/",
        views.questionnaire_monitoring,
        name="questionnaire_monitoring",
    ),
    path("system-health/", views.system_health, name="system_health"),
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
    path("normative/", views.normative, name="normative"),
    path(
        "normative/versions/",
        views.normative_versions,
        name="normative_versions",
    ),
    path(
        "normative/versions/create/",
        views.create_normative_version,
        name="create_normative_version",
    ),
    path(
        "normative/versions/<int:version_id>/",
        views.normative_version_detail,
        name="normative_version_detail",
    ),
    path(
        "normative/versions/<int:version_id>/prepare/",
        views.prepare_normative_version,
        name="prepare_normative_version",
    ),
    path(
        "normative/versions/<int:version_id>/activate/",
        views.activate_normative_version,
        name="activate_normative_version",
    ),
]
