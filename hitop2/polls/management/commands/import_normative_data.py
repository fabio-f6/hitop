import csv

from django.core.management.base import BaseCommand
from polls.models import NormativeParticipant, Question, NormativeAnswer

class Command(BaseCommand):

    help = "Importa a base normativa HiTOP"

    def add_arguments(self, parser):

        parser.add_argument(
            "csv_file",
            type=str,
            help="Caminho para o ficheiro CSV"
        )

    def handle(self, *args, **options):

        csv_file = options["csv_file"]

        NormativeAnswer.objects.all().delete()
        NormativeParticipant.objects.all().delete()

        with open(csv_file, newline="", encoding="utf-8-sig") as file:

            reader = csv.DictReader(
                file,
                delimiter=";"
            )

            rows = list(reader)

            questions = {
                question.item_code.lower(): question
                for question in Question.objects.all()
            }

            self.stdout.write("A importar participantes...")

            for row in rows:

                age = None

                if row["Age"]:
                    age = int(row["Age"])

                sex = row["sex"].strip()

                if sex.startswith("Masculino"):
                    sex = "Masculino"
                elif sex.startswith("Feminino"):
                    sex = "Feminino"
                elif sex.startswith("Intersexo"):
                    sex = "Intersexo"
                else:
                    print(f"Sexo desconhecido: {sex}")

                participant = NormativeParticipant.objects.create(
                    age=age,
                    sex=sex,
                )

                for item_code, question in questions.items():

                    answer = row.get(item_code)

                    if not answer:
                        continue

                    NormativeAnswer.objects.create(
                        participant=participant,
                        question=question,
                        answer=answer,
                    )

        self.stdout.write(
            self.style.SUCCESS("CSV carregado com sucesso.")
        )

        self.stdout.write(
            f"Participantes encontrados: {len(rows)}"
        )

        self.stdout.write(
            f"Colunas encontradas: {len(reader.fieldnames)}"
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Foram criados {NormativeParticipant.objects.count()} participantes."
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Foram criadas {NormativeAnswer.objects.count()} respostas."
            )
        )