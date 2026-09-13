"""Bootstrap the costing pipeline's storage + database in Google.

Creates (idempotently) the Costing root folder and the control spreadsheet that
serves as the application database, then prints the ids to put in settings.py.

    python manage.py costing_init
"""
from django.core.management.base import BaseCommand

from dashboard.costing.drive_store import get_root_folder_id
from dashboard.costing.sheet_db import SheetDB
from dashboard.google_drive import load_credentials


class Command(BaseCommand):
    help = "Create the Costing root Drive folder and the Sheets control database."

    def handle(self, *args, **options):
        creds = load_credentials()
        root_id = get_root_folder_id(creds=creds)
        self.stdout.write(self.style.SUCCESS(f"Costing root folder: {root_id}"))

        db = SheetDB.create(root_id, creds=creds)
        self.stdout.write(self.style.SUCCESS(f"Control database sheet: {db.id}"))
        self.stdout.write(
            "\nAdd these to dashboard_project/settings.py (or the environment):\n"
            f"  GOOGLE_COSTING_ROOT_FOLDER_ID = '{root_id}'\n"
            f"  GOOGLE_COSTING_DB_SHEET_ID = '{db.id}'\n"
        )
