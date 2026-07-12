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

    # Pacientes
    path(
        "patients/create/",
        views.create_patient,
        name="create_patient",
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
]