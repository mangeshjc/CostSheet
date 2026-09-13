"""Create a new costing period: Drive folder tree + database row.

    python manage.py costing_new_period "2. Jun 26 YTD"
"""
from django.core.management.base import BaseCommand, CommandError

from dashboard.costing.orchestrator import new_period


class Command(BaseCommand):
    help = "Create the Drive folder tree and DB record for a new costing period."

    def add_arguments(self, parser):
        parser.add_argument("name", help='Period name, e.g. "2. Jun 26 YTD"')

    def handle(self, *args, **options):
        name = options["name"]
        try:
            period = new_period(name)
        except Exception as exc:  # noqa: BLE001
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Period '{name}' ready (folder {period['period_id']})."))
        self.stdout.write("Folders created:")
        for path, fid in period["folders"].items():
            self.stdout.write(f"  {path}  ->  {fid}")
