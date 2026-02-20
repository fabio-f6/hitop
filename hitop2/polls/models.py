from django.db import models
from django.contrib.auth.models import User

class Scale(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class Subscale(models.Model):
    name = models.CharField(max_length=100)
    scale = models.ForeignKey(Scale, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.scale.name} - {self.name}"

class Question(models.Model):
    scale = models.ForeignKey(Scale, on_delete=models.CASCADE)
    subscale = models.ForeignKey(Subscale, on_delete=models.CASCADE)

    item_code = models.CharField(max_length=20, unique=True)
    rk = models.BooleanField(default=False)

    question_text = models.CharField(max_length=255)

    ANSWER_CHOICES = [
        ('1', 'Nunca'),
        ('2', 'Raramente'),
        ('3', 'Às vezes'),
        ('4', 'Sempre'),
    ]

    def __str__(self):
        return f"{self.scale.name} - {self.item_code}"

class UserAnswer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    answer = models.CharField(max_length=1, choices=Question.ANSWER_CHOICES)
    answered_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.question.question_text}: {self.get_answer_display()}"
