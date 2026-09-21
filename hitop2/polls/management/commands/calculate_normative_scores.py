from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from polls.models import NormativeDatasetVersion
from polls.normative_versions import (
    NormativeVersionError,
    prepare_normative_version,
)


class Command(BaseCommand):

    help = "Calcula os valores brutos de uma versão normativa draft."

    def add_arguments(self, parser):
        parser.add_argument(
            "version",
            nargs="?",
            help="ID ou nome da versão draft (por omissão, o draft mais recente).",
        )

    def handle(self, *args, **options):

        identifier = options.get("version")
        drafts = NormativeDatasetVersion.objects.filter(
            status=NormativeDatasetVersion.Status.DRAFT,
        )
        if identifier:
            lookup = Q(name=identifier)
            if identifier.isdigit():
                lookup |= Q(pk=int(identifier))
            try:
                version = drafts.get(lookup)
            except NormativeDatasetVersion.DoesNotExist as exc:
                raise CommandError("Versão normativa draft não encontrada.") from exc
            except NormativeDatasetVersion.MultipleObjectsReturned as exc:
                raise CommandError("O identificador da versão é ambíguo.") from exc
        else:
            version = drafts.order_by("-created_at", "-pk").first()
            if version is None:
                raise CommandError("Não existe uma versão normativa draft para preparar.")

        self.stdout.write(
            f"A calcular {version.participant_count} participantes de {version.name}..."
        )
        try:
            result = prepare_normative_version(version)
        except NormativeVersionError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Foram calculados {result.scale_score_count} valores de escalas e "
                f"{result.spectrum_score_count} valores de espectros para {version.name}."
            )
        )
