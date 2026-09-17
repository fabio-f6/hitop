from polls.models import UserAnswer, SociodemographicAnswer, DynamicAnswer

def reset_patient_data(user):
    UserAnswer.objects.filter(user=user).delete()
    SociodemographicAnswer.objects.filter(user=user).delete()
    DynamicAnswer.objects.filter(user=user).delete()
