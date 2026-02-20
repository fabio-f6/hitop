from django.urls import path
from . import views

app_name = 'website'

urlpatterns = [
    path('', views.home, name='home'),
    path('logout/', views.logout_user, name='logout'),
    path('register/', views.register_user, name='register'),
    path('record/<int:pk>', views.customer_record, name='record'),
    path('delete_record/<int:pk>', views.delete_record, name='delete_record'),
    path('update_record/<int:pk>', views.update_record, name='update_record'),
    path('add_record/', views.add_record, name='add_record'),
    path("my_patients/", views.my_patients, name="my_patients"),
    path("patient/<int:patient_id>", views.patient_answers, name="patient_answers"),
]