from django.urls import path
from . import views

app_name = 'website'

urlpatterns = [
    path('', views.home, name='home'),
    path('logout/', views.logout_user, name='logout'),
    path('register/', views.register_user, name='register'),
    path("my_patients/", views.my_patients, name="my_patients"),
    path('create_patient/', views.create_patient, name='create_patient'),
    path('edit_patient/<int:patient_id>/', views.edit_patient, name='edit_patient'),
    path('reopen_questionnaire/<int:patient_id>/', views.reopen_questionnaire, name='reopen_questionnaire'),
    path('patient_credentials/', views.patient_credentials, name='patient_credentials'),
    path("patient/<int:patient_id>/submissions/", views.patient_submissions, name="patient_submissions"),
    path("submission/<int:submission_id>/answers/", views.patient_answers, name="patient_answers"),
]