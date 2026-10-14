from django.urls import path
from . import views

app_name = "website"

urlpatterns = [

    # Landing page
    path(
        "",
        views.home,
        name="home",
    ),

    # Autenticação
    path(
        "register/",
        views.register_user,
        name="register",
    ),
    path(
        "logout/",
        views.logout_user,
        name="logout",
    ),

    # Dashboard
    path(
        "dashboard/",
        views.dashboard,
        name="dashboard",
    ),
    path(
        "account/notification-preferences/",
        views.notification_preferences,
        name="notification_preferences",
    ),

    # Coletas Gerais
    path("collections/", views.collection_list, name="collection_list"),
    path("collections/create/", views.collection_create, name="collection_create"),
    path("collections/<int:collection_id>/", views.collection_detail, name="collection_detail"),
    path("collections/<int:collection_id>/toggle/", views.collection_toggle, name="collection_toggle"),
    path("collections/reports/<int:submission_id>/preview/", views.collection_report_preview, name="collection_report_preview"),
    path("collections/reports/<int:submission_id>/export/", views.collection_report_export, name="collection_report_export"),
    path("c/<uuid:token>/", views.collection_public, name="collection_public"),
    path("c/<uuid:token>/start/", views.collection_start, name="collection_start"),

    # Pacientes
    path(
        "patients/create/",
        views.create_patient,
        name="create_patient",
    ),
    path(
        "patients/archived/",
        views.archived_patients,
        name="archived_patients",
    ),
    path(
        "patients/<int:patient_id>/archive/",
        views.archive_patient,
        name="archive_patient",
    ),
    path(
        "patients/<int:patient_id>/restore/",
        views.restore_patient,
        name="restore_patient",
    ),
    path(
        "patients/<int:patient_id>/delete-permanently/",
        views.permanently_delete_patient_view,
        name="permanently_delete_patient",
    ),
    path(
        "patients/<int:patient_id>/edit/",
        views.edit_patient,
        name="edit_patient",
    ),
    path(
        "patients/<int:patient_id>/submissions/",
        views.patient_submissions,
        name="patient_submissions",
    ),
    path(
        "patients/<int:patient_id>/new-questionnaire/",
        views.new_questionnaire,
        name="new_questionnaire",
    ),

    # Submissões
    path(
        "submissions/<int:submission_id>/answers/",
        views.patient_answers,
        name="patient_answers",
    ),

    # Relatórios
    path(
        "reports/<int:submission_id>/preview/",
        views.report_preview,
        name="report_preview",
    ),
    path(
        "reports/<int:submission_id>/export/docx/",
        views.export_report_docx,
        name="export_report_docx",
    ),
]
