from django.core.management.base import BaseCommand

from polls.models import (
    QuestionCategory,
    DynamicQuestion,
    DynamicChoice
)


class Command(BaseCommand):

    help = "Popula perguntas de consumo de substâncias"


    def handle(self, *args, **kwargs):

        category, created = QuestionCategory.objects.get_or_create(
            name="Consumo de substâncias"
        )

        SHARED_DESCRIPTION = (
            "No último ano, selecione a frequência com que consumiu "
            "as seguintes substâncias. Por favor, considere apenas "
            "substâncias que NÃO lhe foram prescritas por um profissional "
            "de saúde OU que utilizou de uma forma DIFERENTE da prescrita."
        )

        SUBSTANCE_CHOICES = [

            ("0", "Nunca"),

            ("1", "Ocasionalmente (1-10 vezes em todo o ano)"),

            ("2", "Uso mensal (pelo menos 1 vez por mês)"),

            ("3", "Uso semanal (pelo menos 1 vez por semana)"),

            ("4", "Uso diário ou quase diário"),

            ("5", "Uso diário ou quase diário, várias vezes por dia"),

            ("9", "Prefiro não responder"),
        ]


        SUBSTANCE_QUESTIONS = [

            {
                "id": "subs_use_lastyear_alc",
                "label": "Álcool (etanol)",
            },

            {
                "id": "subs_use_lastyear_can",
                "label": "Cannabis (erva, marijuana, haxixe, ganza, óleo, etc)",
            },

            {
                "id": "subs_use_lastyear_nic",
                "label": "Nicotina/Tabaco (cigarros, vaporizadores/cigarros eletrónicos, adesivos ou pastilhas de nicotina, medicação para deixar de fumar)",
            },

            {
                "id": "subs_use_lastyear_stimulant",
                "label": "Estimulantes (cocaína, crack, catinonas/khat, metanfetaminas ou anfetaminas, como: speed, cristal, crystal meth, ice).",
            },

            {
                "id": "subs_use_lastyear_inal",
                "label": "Inalantes (óxido nitroso, cola, combustível, diluentes, etc)",
            },

            {
                "id": "subs_use_lastyear_aluc",
                "label": "Alucinogénios (LSD, ácido, cogumelos mágicos, psilocibina, PCP/pó de anjo, Cetamina/Keta, ecstasy, etc)",
            },

            {
                "id": "subs_use_lastyear_opiod",
                "label": "Opióides (heroína, ópio, fentanil, etc)",
            },

            {
                "id": "subs_use_lastyear_medicines",
                "label": "Medicamentos não prescritos por médicos ou utilizados em quantidade fora do prescrito (ex: sedativos/ansiolíticos/benzodiazepinas/sonoríparos como Valium, Diazepam, etc; Estimulantes como Ritalina ou Concerta, etc; Opióides como Oxicodona, Metadona, Buprenorfina, etc)",
            },
        ]


        for index, q in enumerate(SUBSTANCE_QUESTIONS):

            question, created = DynamicQuestion.objects.get_or_create(

                question_id=q["id"].strip(),

                defaults={

                    "category": category,

                    "label": q["label"],

                    "description": SHARED_DESCRIPTION,

                    "question_type": "radio",

                    "required": True,

                    "order": index
                }
            )

            for choice_index, choice in enumerate(SUBSTANCE_CHOICES):

                DynamicChoice.objects.get_or_create(

                    question=question,

                    value=choice[0].strip(),

                    defaults={

                        "label": choice[1],

                        "order": choice_index
                    }
                )

        self.stdout.write(
            self.style.SUCCESS(
                "Perguntas de consumo de substâncias criadas."
            )
        )