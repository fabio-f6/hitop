from django.db import models
from django.contrib.auth.models import User

class Question(models.Model):
    question_text = models.CharField(max_length=255)

    ANSWER_CHOICES = [
        ('1', 'Nunca'),
        ('2', 'Raramente'),
        ('3', 'Às vezes'),
        ('4', 'Sempre'),
    ]

    def __str__(self):
        return self.question_text

class UserAnswer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    answer = models.CharField(max_length=1, choices=Question.ANSWER_CHOICES)
    answered_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.question.question_text}: {self.get_answer_display()}"
