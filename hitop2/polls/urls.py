from django.urls import path
from . import views

app_name = "polls"

urlpatterns = [
    path("", views.index, name="index"),
    path("questionnaire/", views.questionnaire, name="questionnaire"),
	path("thank-you/", views.thank_you, name="thank_you"),
]