from django.db import models
from django.contrib.auth.models import User

class Spectra(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class Subfactor(models.Model):
    name = models.CharField(max_length=100)
    spectra = models.ForeignKey(Spectra, on_delete=models.CASCADE, related_name='subfactors')

    def __str__(self):
        return f"{self.spectra.name} - {self.name}"

class Scale(models.Model):
    name = models.CharField(max_length=100)
    subfactor = models.ForeignKey(Subfactor, on_delete=models.CASCADE, related_name='scales')

    def __str__(self):
        return f"{self.subfactor.name} - {self.name}"

class Question(models.Model):
    scale = models.ForeignKey(Scale, on_delete=models.CASCADE, related_name='questions')
    item_code = models.CharField(max_length=20, unique=True)
    question_text = models.TextField()

    ANSWER_CHOICES = [
        ('1', 'Nunca'),
        ('2', 'Raramente'),
        ('3', 'Às vezes'),
        ('4', 'Sempre'),
    ]

    def __str__(self):
        return f"{self.scale.name} - {self.item_code}"

    @property
    def subfactor(self):
        return self.scale.subfactor

    @property
    def spectra(self):
        return self.scale.subfactor.spectra

class UserAnswer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='user_answers')
    answer = models.CharField(max_length=1, choices=Question.ANSWER_CHOICES)
    answered_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.question.question_text}: {self.get_answer_display()}"