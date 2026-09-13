"""Print the cached Google token as a single line, for pasting into hosting.

A hosted deployment has no browser to run `google_auth` in and no filesystem
that survives a deploy, so it reads the credentials from the GOOGLE_TOKEN_JSON
environment variable instead. This prints exactly what that variable needs.

    python manage.py google_token_env
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Print google_token.json as one line, to paste into GOOGLE_TOKEN_JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--raw",
            action="store_true",
            help="Print only the JSON, with no surrounding explanation.",
        )

    def handle(self, *args, **options):
        token_file = Path(settings.GOOGLE_TOKEN_FILE)
        if not token_file.exists():
            self.stderr.write(
                f"No token at {token_file}. Run 'python manage.py google_auth' first."
            )
            return

        try:
            data = json.loads(token_file.read_text())
        except ValueError as exc:
            self.stderr.write(f"{token_file} is not valid JSON: {exc}")
            return

        if not data.get("refresh_token"):
            self.stderr.write(
                "This token has no refresh_token, so it will stop working within "
                "the hour. Re-run 'python manage.py google_auth' to get one."
            )
            return

        one_line = json.dumps(data, separators=(",", ":"))

        if options["raw"]:
            self.stdout.write(one_line)
            return

        self.stdout.write("Set this as GOOGLE_TOKEN_JSON in your host's environment:")
        self.stdout.write("")
        self.stdout.write(one_line)
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                "This grants full access to the Drive of the account that signed "
                "in. Treat it like a password: paste it only into the host's "
                "secret/environment settings, never into the repo."
            )
        )
