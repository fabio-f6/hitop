from django.core.management.base import BaseCommand
from django.db import transaction

from polls.socio_config import SOCIO_QUESTIONS
from polls.models import (
    QuestionCategory,
    DynamicQuestion,
    DynamicChoice
)


class Command(BaseCommand):
    help = "Popula o questionário que antecede o HiTOP"

    @transaction.atomic
    def handle(self, *args, **kwargs):
        category, _ = QuestionCategory.objects.get_or_create(
            name="Dados Sociodemográficos"
        )

        for index, q in enumerate(SOCIO_QUESTIONS):
            question, _ = DynamicQuestion.objects.update_or_create(
                question_id=q["id"],
                defaults={
                    "category": category,
                    "label": q["label"],
                    "question_type": q["type"],
                    "required": q.get("required", True),
                    "order": index,
                    "description": q.get("description", ""),
                    "section": q["section"],
                    "show_if_question": q.get("show_if_question", ""),
                    "show_if_values": q.get("show_if_values", []),
                }
            )

            for choice_index, (value, label) in enumerate(q.get("choices", [])):
                DynamicChoice.objects.update_or_create(
                    question=question,
                    value=value,
                    defaults={"label": label, "order": choice_index},
                )

        self.stdout.write(
            self.style.SUCCESS(f"{len(SOCIO_QUESTIONS)} perguntas sincronizadas.")
        )
