from django.urls import path

from . import views


app_name = "administration"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("system/", views.system, name="system"),
    path("system/master-reset/", views.master_reset, name="master_reset"),
    path(
        "test-environment/",
        views.professional_test_environment,
        name="professional_test_environment",
    ),
    path(
        "test-environment/patients/create/",
        views.test_create_patient,
        name="test_create_patient",
    ),
    path(
        "test-environment/patients/archived/",
        views.test_archived_patients,
        name="test_archived_patients",
    ),
    path(
        "test-environment/patients/<int:patient_id>/archive/",
        views.test_archive_patient,
        name="test_archive_patient",
    ),
    path(
        "test-environment/patients/<int:patient_id>/restore/",
        views.test_restore_patient,
        name="test_restore_patient",
    ),
    path(
        "test-environment/patients/<int:patient_id>/submissions/",
        views.test_patient_submissions,
        name="test_patient_submissions",
    ),
    path(
        "test-environment/patients/<int:patient_id>/new-questionnaire/",
        views.test_new_questionnaire,
        name="test_new_questionnaire",
    ),
    path(
        "test-environment/submissions/<int:submission_id>/answers/",
        views.test_patient_answers,
        name="test_patient_answers",
    ),
    path(
        "test-environment/reports/<int:submission_id>/preview/",
        views.test_report_preview,
        name="test_report_preview",
    ),
    path(
        "test-environment/reports/<int:submission_id>/export/docx/",
        views.test_export_report_docx,
        name="test_export_report_docx",
    ),
    path("audit/", views.audit, name="audit"),
    path(
        "questionnaires/",
        views.questionnaire_monitoring,
        name="questionnaire_monitoring",
    ),
    path("system-health/", views.system_health, name="system_health"),
    path("questionnaire-map/", views.questionnaire_map, name="questionnaire_map"),
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
    path("normative/test/create/", views.create_test_normative_version, name="create_test_normative_version"),
    path("normative/test/clear/", views.clear_test_normative_environment, name="clear_test_normative_environment"),
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
