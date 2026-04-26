from polls.models import UserAnswer, SociodemographicAnswer

def reset_patient_data(user):
    UserAnswer.objects.filter(user=user).delete()
    SociodemographicAnswer.objects.filter(user=user).delete()