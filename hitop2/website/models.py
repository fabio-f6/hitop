from django.db import models
from django.contrib.auth.models import User
from django.db.models import Q

class UserProfile(models.Model):
    USER_TYPES = [
        ('patient', 'Paciente'),
        ('professional', 'Profissional'),
        ('admin', 'Admin'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    user_type = models.CharField(max_length=20, choices=USER_TYPES)

    is_verified = models.BooleanField(
        default=False,
        verbose_name="Verificado",
    )

    professional = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="patients"
    )

    is_test_data = models.BooleanField(default=False, db_index=True)

    test_environment_owner = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="test_environment_patients",
    )

    archived_at = models.DateTimeField(null=True, blank=True)
    
    area_formacao = models.CharField(max_length=50, choices=[
        ('Psicologia', 'Psicologia'),
        ('Medicina', 'Medicina'),
        ('Outros', 'Outros')
    ])
    objetivo_uso = models.CharField(max_length=50, choices=[
        ('clinico', 'Avaliação em contexto clínico'),
        ('forense', 'Avaliação em contexto forense'),
        ('investigacao', 'Avaliação em contexto de investigação')
    ])
    cedula_profissional = models.CharField(max_length=50)

    class Meta:
        constraints = (
            models.CheckConstraint(
                condition=(
                    Q(is_test_data=False, test_environment_owner__isnull=True)
                    | Q(
                        is_test_data=True,
                        user_type="patient",
                        professional__isnull=True,
                        test_environment_owner__isnull=False,
                    )
                ),
                name="website_valid_test_patient_ownership",
            ),
        )

    def __str__(self):
        return f"{self.user.username} ({self.user_type})"
