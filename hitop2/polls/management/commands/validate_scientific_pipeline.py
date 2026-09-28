"""Read-only audit entry point. Writes evidence files only, never database rows."""
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from validation.audit import run


class Command(BaseCommand):
    help = "Independent scientific audit (PostgreSQL REPEATABLE READ, READ ONLY)."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--csv", default=str(settings.BASE_DIR / "BD.csv"))
        parser.add_argument("--normative-version", default="v1")
        parser.add_argument("--output", default=str(settings.BASE_DIR / "validation/artifacts"))
        parser.add_argument("--simulations", type=int, default=1000)
        parser.add_argument("--seed", type=int, default=20260928)

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("This audit requires PostgreSQL read-only enforcement.")
        if options["simulations"] < 1000:
            raise CommandError("Use at least 1000 simulations per profile.")
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            result = run(Path(options["csv"]), options["normative_version"], Path(options["output"]),
                         options["simulations"], options["seed"])
        for name, status in result["checks"].items():
            self.stdout.write(f"{status}: {name}")
        self.stdout.write(f"Evidence: {options['output']}")
        if any(s == "FAIL" for s in result["checks"].values()):
            raise CommandError("Audit found unresolved failures; production was not changed.")
