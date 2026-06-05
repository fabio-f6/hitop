from django.urls import path
from . import views

app_name = "polls"

urlpatterns = [
    path("", views.index, name="index"),
    path("questionnaire/", views.questionnaire, name="questionnaire"),

    path(
        "access/<uuid:token>/",
        views.questionnaire_by_token,
        name="questionnaire_by_token"
    ),

    path("thank-you/", views.thank_you, name="thank_you"),
    path('export_pdf/<int:user_id>/', views.export_patient_pdf, name='export_patient_pdf'),
    path('sociodemographic/', views.sociodemographic_form, name='sociodemographic'),
    path("dynamic-questionnaire/<int:category_id>/", views.dynamic_questionnaire, name="dynamic_questionnaire"),
]