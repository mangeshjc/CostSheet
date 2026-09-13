# Dashboard

A Django admin dashboard with a sidebar. Includes an **Upload ERP File** page that
accepts an Excel file (`.xlsx` / `.xls`) and writes its rows into a Google Sheet —
one new worksheet tab per upload, so nothing is ever overwritten.

## Run

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open http://localhost:8000/. The sidebar links to Dashboard, Analytics, Orders,
Customers, **Upload ERP File**, and Settings.

## Google Drive setup (required for the ERP upload)

Each uploaded Excel file is uploaded into a Google **Drive folder** and converted
to a native **Google Sheet** there. It authenticates with **OAuth** as your own
Google account, so the created Sheet is owned by you.

The client id/secret, Drive folder id, and token path are configured in
`dashboard_project/settings.py` (they can also be overridden with environment
variables). One-time setup in the [Google Cloud Console](https://console.cloud.google.com/):

1. In your project, enable the **Google Drive API** (APIs & Services → Library).
2. Configure the **OAuth consent screen**. While it is in **Testing** mode, add
   your own Google account under **Test users** (otherwise sign-in is blocked).
3. Under **Credentials**, create/pick an **OAuth client ID** and make its
   redirect URI match the sign-in flow, which uses a fixed port:

   ```
   http://localhost:8080/
   ```

   - **Web application** client — add that URI, *exactly* as shown (with the
     port and the trailing slash), under **Authorized redirect URIs**. Anything
     else gives `Error 400: redirect_uri_mismatch`. Changes can take a few
     minutes to take effect.
   - **Desktop app** client — nothing to register; Google accepts any
     `http://localhost` port for these.

   To use a different port, set `GOOGLE_OAUTH_REDIRECT_PORT` (or edit it in
   `settings.py`) and register the matching `http://localhost:<port>/`.
4. Make sure `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, and
   `GOOGLE_DRIVE_FOLDER_ID` in `settings.py` match your client and target folder.
5. Sign in once (opens a browser to grant access):

   ```bash
   python manage.py google_auth
   ```

   This caches a refresh token to `google_token.json` (git-ignored). Re-run it if
   the token is ever revoked.

Now upload an Excel file from the **Upload ERP File** page. On success you'll see a
link to open the newly created Google Sheet in your Drive folder.

> **Security:** the client secret is sensitive. If it has been shared anywhere,
> rotate it in the Cloud Console and update `settings.py` (or set it via the
> `GOOGLE_OAUTH_CLIENT_SECRET` environment variable instead of hardcoding it).

## Deploying

See [DEPLOY.md](DEPLOY.md) for hosting on Render. In short: sign in locally,
run `python manage.py google_token_env`, and set the output as the
`GOOGLE_TOKEN_JSON` environment variable on the host -- there is no browser on
the server to run the sign-in flow, and its filesystem does not survive a
deploy.

## Notes

- Only `.xlsx` and `.xls` files pass validation (configurable via
  `ALLOWED_EXCEL_EXTENSIONS` in settings).
- The Excel reader uses the workbook's **active sheet** and writes every row,
  including the header row, as-is.
- Dashboard stats and the recent-orders table are sample data — wire them to real
  models when you're ready.
