"""One-time Google sign-in for the ERP upload feature.

Run once:  python manage.py google_auth
A browser window opens; sign in and grant access. The resulting refresh token
is cached to settings.GOOGLE_TOKEN_FILE and reused by the upload page.

The sign-in server listens on a fixed port (settings.GOOGLE_OAUTH_REDIRECT_PORT)
so the redirect URI stays the same every run and can be registered once in the
Cloud Console.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from google_auth_oauthlib.flow import InstalledAppFlow

from dashboard.google_drive import SCOPES, client_config, redirect_uri


class Command(BaseCommand):
    help = "Authorize this app to access your Google Drive (one-time OAuth sign-in)."

    def handle(self, *args, **options):
        if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_CLIENT_SECRET:
            self.stderr.write(
                "GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET are not set "
                "in settings.py."
            )
            return

        uri = redirect_uri()
        flow = InstalledAppFlow.from_client_config(client_config(), SCOPES)
        self.stdout.write("Opening a browser to sign in to Google...")
        self.stdout.write(f"Redirect URI in use: {uri}")
        self.stdout.write(
            "If Google shows 'Error 400: redirect_uri_mismatch', add that exact "
            "URI to your OAuth client's Authorized redirect URIs in the Cloud "
            "Console (or use a Desktop app client)."
        )
        try:
            creds = flow.run_local_server(
                port=settings.GOOGLE_OAUTH_REDIRECT_PORT,
                prompt="consent",
            )
        except OSError as exc:
            self.stderr.write(
                f"Could not start the local sign-in server on port "
                f"{settings.GOOGLE_OAUTH_REDIRECT_PORT}: {exc}. Free that port, "
                "or set GOOGLE_OAUTH_REDIRECT_PORT to another port and register "
                "the matching http://localhost:<port>/ in the Cloud Console."
            )
            return

        token_file = Path(settings.GOOGLE_TOKEN_FILE)
        token_file.write_text(creds.to_json())
        self.stdout.write(
            self.style.SUCCESS(f"Success. Token saved to {token_file}. "
                               "You can now upload ERP files from the dashboard.")
        )
