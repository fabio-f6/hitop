from contextlib import contextmanager
from contextvars import ContextVar

from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db.models.signals import m2m_changed, pre_delete, pre_save
from django.dispatch import receiver
import uuid


_normative_test_cleanup = ContextVar("normative_test_cleanup", default=False)


@contextmanager
def normative_test_cleanup_boundary():
    """Permit TEST snapshot deletion only inside its explicit cleanup service."""
    token = _normative_test_cleanup.set(True)
    try:
        yield
    finally:
        _normative_test_cleanup.reset(token)

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

    is_attention_check = models.BooleanField(default=False)

    expected_answer = models.CharField(
        max_length=1,
        blank=True,
        default=""
    )

    ANSWER_CHOICES = [
        ("1", "Nunca"),
        ("2", "Raramente"),
        ("3", "Às vezes"),
        ("4", "Sempre"),
        ("5", "Não sei / Prefiro não responder"),
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

    class NormativeStatus(models.TextChoices):
        PENDING = "pending", "Pendente"
        INELIGIBLE = "ineligible", "Não elegível"
        EXPORTED = "exported", "Exportada"

    SIMULATION_MODES = [
        ("normal", "Aplicação normal"),
        ("simulated", "Simular respostas"),
        ("simulated_nulls", "Simular respostas com omissões"),
    ]

    class SociodemographicSimulationMode(models.TextChoices):
        NORMAL = "normal", "Não simular"
        ELIGIBLE = "eligible", "Elegível para base normativa"
        INELIGIBLE_LANGUAGE = (
            "ineligible_language",
            "Não elegível: Português-Europeu",
        )
        INELIGIBLE_MENTAL_HEALTH = (
            "ineligible_mental_health",
            "Não elegível: saúde mental",
        )
        INELIGIBLE_BOTH = "ineligible_both", "Não elegível: ambos"
        PENDING_MISSING = (
            "pending_missing",
            "Indeterminado / resposta normativa em falta",
        )

    class SimulationAttentionMode(models.TextChoices):
        ALL_CORRECT = "all_correct", "Todos corretos"
        ONE_FAILURE = "one_failure", "Uma falha"
        MULTIPLE_FAILURES = "multiple_failures", "Múltiplas falhas"

    class SimulationResponseProfile(models.TextChoices):
        RANDOM = "random", "Aleatório"
        LOW = "low", "Baixo"
        MEDIUM = "medium", "Médio"
        HIGH = "high", "Alto"

    SIMULATION_MISSING_PERCENTAGES = (
        (0, "0%"),
        (10, "10%"),
        (25, "25%"),
        (30, "30%"),
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    access_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    title = models.CharField(
        max_length=255,
        blank=True
    )

    questionnaire_type = models.CharField(
        max_length=50,
        default="hitop"
    )

    completed = models.BooleanField(
        default=False
    )

    sociodemographic_completed = models.BooleanField(default=False)
    sociodemographic_step = models.PositiveIntegerField(default=0)

    started_at = models.DateTimeField(
        auto_now_add=True
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    normative_status = models.CharField(
        max_length=10,
        choices=NormativeStatus.choices,
        default=NormativeStatus.PENDING,
    )

    normative_exported_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    report_normative_version = models.ForeignKey(
        "NormativeDatasetVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="report_submissions",
    )

    report_normative_version_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    report_normative_version_environment = models.CharField(
        max_length=12,
        choices=(
            ("production", "Produção"),
            ("test", "Teste"),
        ),
        blank=True,
        default="",
    )

    is_open = models.BooleanField(
        default=True
    )

    simulation_mode = models.CharField(
        max_length=20,
        choices=SIMULATION_MODES,
        default="normal",
    )

    sociodemographic_simulation_mode = models.CharField(
        max_length=32,
        choices=SociodemographicSimulationMode.choices,
        default=SociodemographicSimulationMode.NORMAL,
    )

    simulation_attention_mode = models.CharField(
        max_length=24,
        choices=SimulationAttentionMode.choices,
        default=SimulationAttentionMode.ALL_CORRECT,
    )

    simulation_missing_percentage = models.PositiveSmallIntegerField(
        choices=SIMULATION_MISSING_PERCENTAGES,
        default=0,
    )

    simulation_response_profile = models.CharField(
        max_length=10,
        choices=SimulationResponseProfile.choices,
        default=SimulationResponseProfile.RANDOM,
    )

    simulation_seed = models.IntegerField(
        null=True,
        blank=True,
    )

    is_test_data = models.BooleanField(
        default=False,
        db_index=True,
    )

    spectra = models.ManyToManyField(
        Spectra,
        blank=True
    )

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "report_normative_version" in update_fields:
            kwargs["update_fields"] = set(update_fields) | {
                "report_normative_version_name",
                "report_normative_version_environment",
            }
        return super().save(*args, **kwargs)

    @property
    def effective_simulation_missing_percentage(self):
        """Return the configured rate, preserving legacy null simulations."""
        if (
            self.simulation_mode == "simulated_nulls"
            and self.simulation_missing_percentage == 0
        ):
            return 10
        return self.simulation_missing_percentage

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
    answer_value = models.CharField(max_length=255)
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

    is_active = models.BooleanField(default=True)

    order = models.PositiveIntegerField(default=0)

    description = models.TextField(
        blank=True,
        null=True
    )

    group_intro = models.TextField(blank=True)

    section = models.CharField(max_length=100, blank=True)
    show_if_question = models.CharField(max_length=100, blank=True)
    show_if_values = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.question_id

class DynamicChoice(models.Model):

    question = models.ForeignKey(
        DynamicQuestion,
        on_delete=models.CASCADE,
        related_name="choices"
    )

    value = models.CharField(max_length=20)

    label = models.TextField()

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


class NormativeDatasetVersion(models.Model):

    class Environment(models.TextChoices):
        PRODUCTION = "production", "Produção"
        TEST = "test", "Teste"

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        ACTIVE = "active", "Ativa"
        RETIRED = "retired", "Histórica"

    name = models.CharField(
        max_length=100,
        unique=True,
    )

    environment = models.CharField(
        max_length=12,
        choices=Environment.choices,
        default=Environment.PRODUCTION,
        db_index=True,
    )

    baseline_version = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True,
        related_name="test_derivatives",
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    prepared_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    activated_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    participants = models.ManyToManyField(
        "NormativeParticipant",
        through="NormativeDatasetMembership",
        related_name="dataset_versions",
    )

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = (
            models.UniqueConstraint(
                fields=("environment",),
                condition=Q(status="active"),
                name="polls_one_active_normative_version_per_environment",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="draft", activated_at__isnull=True)
                    | Q(status__in=("active", "retired"), activated_at__isnull=False)
                ),
                name="polls_normative_activation_timestamp",
            ),
        )

    def clean(self):
        super().clean()
        if self.baseline_version_id:
            if self.environment != self.Environment.TEST:
                raise ValidationError({"baseline_version": "Apenas versões de teste têm baseline."})
            if self.baseline_version.environment not in {
                self.Environment.PRODUCTION,
                self.Environment.TEST,
            }:
                raise ValidationError({
                    "baseline_version": "O baseline deve ser uma versão de produção ou de teste."
                })
        if self.status == self.Status.DRAFT and self.activated_at is not None:
            raise ValidationError({
                "activated_at": "Uma versão draft não pode ter data de ativação."
            })
        if self.status != self.Status.DRAFT and self.activated_at is None:
            raise ValidationError({
                "activated_at": "Uma versão ativa ou histórica requer data de ativação."
            })

    def save(self, *args, **kwargs):
        if self._state.adding and self.status != self.Status.DRAFT:
            raise ValidationError(
                "As versões devem ser criadas como draft e ativadas pelo serviço normativo."
            )
        if not self._state.adding:
            previous = type(self).objects.get(pk=self.pk)
            if previous.status != self.status:
                raise ValidationError(
                    "O estado da versão só pode ser alterado pelo serviço normativo."
                )
            if previous.status != self.Status.DRAFT:
                immutable_fields = ("name", "environment", "baseline_version_id", "prepared_at", "activated_at")
                if any(
                    getattr(previous, field) != getattr(self, field)
                    for field in immutable_fields
                ):
                    raise ValidationError("Uma versão normativa histórica é imutável.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if _version_status(self.pk) != self.Status.DRAFT:
            raise ValidationError("Uma versão normativa histórica não pode ser eliminada.")
        return super().delete(*args, **kwargs)

    @property
    def participant_count(self):
        if hasattr(self, "snapshot_participant_count"):
            return self.snapshot_participant_count
        return self.participants.count()

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

class NormativeParticipant(models.Model):

    class Source(models.TextChoices):
        REAL = "real", "Real"
        SYNTHETIC = "synthetic", "Sintético"

    source = models.CharField(
        max_length=12, choices=Source.choices, default=Source.REAL, db_index=True,
    )

    source_submission = models.OneToOneField(
        QuestionnaireSubmission, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="synthetic_normative_participant",
    )

    sex = models.CharField(
        max_length=20,
        blank=True
    )

    age = models.IntegerField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"Participante {self.id}"


class NormativeDatasetMembership(models.Model):

    version = models.ForeignKey(
        NormativeDatasetVersion,
        on_delete=models.CASCADE,
        related_name="memberships",
    )

    participant = models.ForeignKey(
        NormativeParticipant,
        on_delete=models.PROTECT,
        related_name="version_memberships",
    )

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("version", "participant"),
                name="polls_unique_normative_version_participant",
            ),
        )

    def clean(self):
        super().clean()
        if (
            self.version_id
            and self.participant_id
            and self.version.environment == NormativeDatasetVersion.Environment.PRODUCTION
            and self.participant.source == NormativeParticipant.Source.SYNTHETIC
        ):
            raise ValidationError(
                "Participantes sintéticos não podem integrar versões de produção."
            )
        if self.version_id and _version_is_immutable(self.version_id):
            raise ValidationError(
                "Os participantes desta versão normativa já não podem ser alterados."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.clean()
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.version.name} - {self.participant}"


class NormativeAnswer(models.Model):

    participant = models.ForeignKey(
        NormativeParticipant,
        on_delete=models.CASCADE,
        related_name="answers"
    )

    question = models.ForeignKey(
        Question,
        on_delete=models.PROTECT
    )

    answer = models.CharField(
        max_length=1,
        choices=Question.ANSWER_CHOICES
    )

    def __str__(self):
        return f"P{self.participant.id} - {self.question.item_code}: {self.answer}"

class NormativeScaleScore(models.Model):

    version = models.ForeignKey(
        NormativeDatasetVersion,
        on_delete=models.PROTECT,
        related_name="scale_scores",
    )

    participant = models.ForeignKey(
        NormativeParticipant,
        on_delete=models.PROTECT,
        related_name="scale_scores"
    )

    scale = models.ForeignKey(
        Scale,
        on_delete=models.PROTECT
    )

    raw_score = models.FloatField()

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("version", "participant", "scale"),
                name="polls_unique_version_participant_scale",
            ),
        )

    def clean(self):
        super().clean()
        if self.version_id:
            if _version_status(self.version_id) != NormativeDatasetVersion.Status.DRAFT:
                raise ValidationError("Os scores de uma versão histórica são imutáveis.")
            if self.participant_id and not NormativeDatasetMembership.objects.filter(
                version_id=self.version_id,
                participant_id=self.participant_id,
            ).exists():
                raise ValidationError(
                    "O participante não pertence ao snapshot desta versão normativa."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if _version_status(self.version_id) != NormativeDatasetVersion.Status.DRAFT:
            raise ValidationError("Os scores de uma versão histórica são imutáveis.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.participant} - "
            f"{self.scale}: "
            f"{self.raw_score:.2f}"
        )

class NormativeSpectrumScore(models.Model):

    version = models.ForeignKey(
        NormativeDatasetVersion,
        on_delete=models.PROTECT,
        related_name="spectrum_scores",
    )

    participant = models.ForeignKey(
        NormativeParticipant,
        on_delete=models.PROTECT,
        related_name="spectrum_scores",
    )

    spectrum = models.ForeignKey(
        Spectra,
        on_delete=models.PROTECT,
    )

    raw_score = models.FloatField()

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("version", "participant", "spectrum"),
                name="polls_unique_version_participant_spectrum",
            ),
        )

    def clean(self):
        super().clean()
        if self.version_id:
            if _version_status(self.version_id) != NormativeDatasetVersion.Status.DRAFT:
                raise ValidationError("Os scores de uma versão histórica são imutáveis.")
            if self.participant_id and not NormativeDatasetMembership.objects.filter(
                version_id=self.version_id,
                participant_id=self.participant_id,
            ).exists():
                raise ValidationError(
                    "O participante não pertence ao snapshot desta versão normativa."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if _version_status(self.version_id) != NormativeDatasetVersion.Status.DRAFT:
            raise ValidationError("Os scores de uma versão histórica são imutáveis.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.participant} - "
            f"{self.spectrum}: "
            f"{self.raw_score:.2f}"
        )


def _version_lifecycle(version_or_id):
    version_id = getattr(version_or_id, "pk", version_or_id)
    return NormativeDatasetVersion.objects.values_list(
        "status",
        "prepared_at",
    ).get(pk=version_id)


def _version_status(version_or_id):
    return _version_lifecycle(version_or_id)[0]


def _version_is_immutable(version_or_id):
    status, prepared_at = _version_lifecycle(version_or_id)
    return status != NormativeDatasetVersion.Status.DRAFT or prepared_at is not None


@receiver(pre_save, sender=QuestionnaireSubmission)
def protect_report_normative_environment(sender, instance, **kwargs):
    if not instance.report_normative_version_id:
        return
    name, environment = NormativeDatasetVersion.objects.values_list(
        "name", "environment"
    ).get(pk=instance.report_normative_version_id)
    is_test_submission = instance.is_test_data or instance.simulation_mode != "normal"
    if not is_test_submission and environment != NormativeDatasetVersion.Environment.PRODUCTION:
        raise ValidationError(
            "Uma submissão clínica real não pode usar uma versão normativa de teste."
        )
    instance.report_normative_version_name = name
    instance.report_normative_version_environment = environment


@receiver(m2m_changed, sender=NormativeDatasetMembership)
def protect_normative_snapshot(sender, instance, action, reverse, pk_set, **kwargs):
    if action not in {"pre_add", "pre_remove", "pre_clear"}:
        return

    if reverse:
        versions = NormativeDatasetVersion.objects.filter(participants=instance)
        if pk_set is not None:
            versions = NormativeDatasetVersion.objects.filter(pk__in=pk_set)
        if versions.filter(
            Q(status__in=("active", "retired")) | Q(prepared_at__isnull=False)
        ).exists():
            raise ValidationError(
                "Os participantes desta versão normativa já não podem ser alterados."
            )
    elif _version_is_immutable(instance.pk):
        raise ValidationError(
            "Os participantes desta versão normativa já não podem ser alterados."
        )


@receiver(pre_delete, sender=NormativeDatasetVersion)
def protect_historical_normative_version_deletion(sender, instance, **kwargs):
    if (
        _normative_test_cleanup.get()
        and instance.environment == NormativeDatasetVersion.Environment.TEST
    ):
        return
    if _version_status(instance.pk) != NormativeDatasetVersion.Status.DRAFT:
        raise ValidationError("Uma versão normativa histórica não pode ser eliminada.")


@receiver(pre_delete, sender=NormativeDatasetMembership)
def protect_normative_membership_deletion(sender, instance, **kwargs):
    if (
        _normative_test_cleanup.get()
        and instance.version.environment == NormativeDatasetVersion.Environment.TEST
    ):
        return
    if _version_is_immutable(instance.version_id):
        raise ValidationError(
            "Os participantes desta versão normativa já não podem ser alterados."
        )


@receiver(pre_delete, sender=NormativeScaleScore)
@receiver(pre_delete, sender=NormativeSpectrumScore)
def protect_historical_normative_score_deletion(sender, instance, **kwargs):
    if (
        _normative_test_cleanup.get()
        and instance.version.environment == NormativeDatasetVersion.Environment.TEST
    ):
        return
    if _version_status(instance.version_id) != NormativeDatasetVersion.Status.DRAFT:
        raise ValidationError("Os scores de uma versão histórica são imutáveis.")
