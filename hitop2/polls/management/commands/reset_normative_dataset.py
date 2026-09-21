from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from polls.models import (
    NormativeDatasetVersion,
    NormativeScaleScore,
    NormativeSpectrumScore,
)
from polls.normative_versions import (
    activate_normative_version,
    create_normative_version,
    prepare_normative_version,
)


class Command(BaseCommand):
    help = (
        "Reconstrói excecionalmente a única v1 a partir de um CSV, apenas quando "
        "a versão ainda não foi usada por nenhum relatório."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=str,
            help="Caminho para o ficheiro CSV que substituirá integralmente a v1.",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Confirma a eliminação e reconstrução integral da v1 atual.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError(
                "Operação não confirmada. Use --confirm depois de criar um backup."
            )

        csv_path = Path(options["csv_file"]).expanduser().resolve()
        if not csv_path.is_file():
            raise CommandError(f"Ficheiro CSV não encontrado: {csv_path}")

        versions = list(
            NormativeDatasetVersion.objects.select_for_update().order_by("pk")
        )
        if len(versions) != 1:
            raise CommandError(
                "O reset só é permitido quando existe exatamente uma versão normativa."
            )

        version = versions[0]
        if (
            version.name != "v1"
            or version.status != NormativeDatasetVersion.Status.ACTIVE
        ):
            raise CommandError(
                "O reset só é permitido para a única versão ativa chamada v1."
            )

        report_count = version.report_submissions.count()
        if report_count:
            raise CommandError(
                "O reset foi recusado: a v1 já está associada a "
                f"{report_count} relatório(s). Crie uma nova versão em vez de "
                "alterar o histórico."
            )

        previous_participant_count = version.participant_count

        # This is the sole exceptional path that dismantles an unused active
        # v1. Returning it to an unprepared draft satisfies lifecycle database
        # constraints and lets the normal deletion protections remain enabled.
        NormativeDatasetVersion.objects.filter(pk=version.pk).update(
            status=NormativeDatasetVersion.Status.DRAFT,
            prepared_at=None,
            activated_at=None,
        )
        NormativeScaleScore.objects.filter(version_id=version.pk).delete()
        NormativeSpectrumScore.objects.filter(version_id=version.pk).delete()
        version.refresh_from_db()
        version.delete()

        # Reuse the existing importer inside this outer transaction. Any CSV,
        # scoring, or activation error restores the complete previous v1.
        call_command(
            "import_normative_data",
            str(csv_path),
            stdout=self.stdout,
            stderr=self.stderr,
        )

        new_version = create_normative_version("v1")
        result = prepare_normative_version(new_version)
        new_version = activate_normative_version(new_version)

        self.stdout.write(
            self.style.SUCCESS(
                "v1 reconstruída com sucesso: "
                f"{previous_participant_count} participantes substituídos por "
                f"{result.participant_count}; "
                f"{result.scale_score_count} scores de escalas e "
                f"{result.spectrum_score_count} scores de espectros calculados. "
                f"Versão ativa: {new_version.name} (id={new_version.pk})."
            )
        )
