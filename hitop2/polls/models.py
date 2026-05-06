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
        return self.name

class Scale(models.Model):
    name = models.CharField(max_length=100)
    subfactor = models.ForeignKey(Subfactor, on_delete=models.CASCADE, related_name='scales')

    def __str__(self):
        return self.name

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

class QuestionnaireSubmission(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    questionnaire_type = models.CharField(max_length=50, default="hitop")
    completed = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    is_open = models.BooleanField(default=True)

class UserAnswer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='answers')
    
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='user_answers')
    answer = models.CharField(max_length=1, choices=Question.ANSWER_CHOICES)
    answered_at = models.DateTimeField(auto_now_add=True)

    submission = models.ForeignKey(

        QuestionnaireSubmission,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    def __str__(self):
        return f"{self.user.username} - {self.question.question_text}: {self.get_answer_display()}"

class SociodemographicAnswer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    question_id = models.CharField(max_length=50)
    answer_value = models.CharField(max_length=10)
    answer_label = models.CharField(max_length=100)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.question_id}"

#Novo sistema de questões sociodemográficas:

class QuestionCategory(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class DynamicQuestion(models.Model):

    QUESTION_TYPES = [
        ("radio", "Radio"),
        ("checkbox", "Checkbox"),
        ("text", "Text"),
        ("number", "Number"),
        ("matrix", "Matrix"),
    ]

    category = models.ForeignKey(
        QuestionCategory,
        on_delete=models.CASCADE,
        related_name="questions"
    )

    question_id = models.CharField(
        max_length=100,
        unique=True
    )

    label = models.TextField()

    question_type = models.CharField(
        max_length=20,
        choices=QUESTION_TYPES
    )

    required = models.BooleanField(default=True)

    order = models.PositiveIntegerField(default=0)

    description = models.TextField(
        blank=True,
        null=True
    )

    def __str__(self):
        return self.question_id

class DynamicChoice(models.Model):

    question = models.ForeignKey(
        DynamicQuestion,
        on_delete=models.CASCADE,
        related_name="choices"
    )

    value = models.CharField(max_length=20)

    label = models.CharField(max_length=255)

    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.question.question_id} - {self.label}"

class DynamicAnswer(models.Model):

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    submission = models.ForeignKey(
        QuestionnaireSubmission,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    question = models.ForeignKey(
        DynamicQuestion,
        on_delete=models.CASCADE
    )

    answer_value = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.question.question_id}"