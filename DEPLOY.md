# Deploying to Render

The repo is ready to deploy as-is. The only thing Render cannot work out for
itself is the Google credentials, because the sign-in flow needs a browser and
Render has none — so you sign in **once on your own machine** and hand the
resulting token to Render as an environment variable.

## Before you push

**Use a private repo, or rotate the client secret first.** `settings.py` still
carries a hardcoded `GOOGLE_OAUTH_CLIENT_SECRET` as a development fallback. If
you push this to a *public* GitHub repo, that secret is public too. Either keep
the repo private, or rotate the secret in the Cloud Console and supply it only
through the environment.

`google_token.json`, `db.sqlite3`, `staticfiles/` and `.env` are git-ignored, so
those will not be committed.

## 1. Get the token value

On your machine, with the app already signed in (`google_token.json` present):

```bash
python manage.py google_token_env
```

That prints the one-line JSON to use as `GOOGLE_TOKEN_JSON`. If you have never
signed in, run `python manage.py google_auth` first — and see the OAuth client
notes in [README.md](README.md), because the redirect URI has to be registered.

Treat this value like a password: it grants full Drive access to the account
that signed in.

## 2. Create the service

Push the repo to GitHub, then in Render: **New → Blueprint** and point it at the
repo. [`render.yaml`](render.yaml) sets the build command, the start command and
the safe defaults.

Prefer clicking through by hand instead? Create a **Web Service** with:

- Build command:
  ```
  pip install --upgrade pip && pip install -r requirements.txt && python manage.py collectstatic --no-input && python manage.py migrate
  ```
- Start command:
  ```
  gunicorn dashboard_project.wsgi:application --threads 4 --timeout 300 --access-logfile -
  ```

## 3. Set the environment variable

In the service's **Environment** tab there is exactly one value to fill in:

| Variable | Value |
| --- | --- |
| `GOOGLE_TOKEN_JSON` | output of `python manage.py google_token_env` |

That token already carries the client id and secret inside it, so those do not
need to be set separately. `DJANGO_SECRET_KEY` and `DJANGO_DEBUG` are handled by
`render.yaml`.

**Leave the Drive folder and Sheet ids alone** unless this deployment should
point at different files. They already have working values in `settings.py`, and
the deployed app shows the same data as your local one because of that.

> Adding one of those keys with an empty value is *not* the same as not adding
> it — an empty variable means "no folder configured" to most Django projects,
> which is the classic reason a deployed copy shows nothing while the local one
> works. Here `settings.py` treats a blank variable as unset and falls back to
> the committed id, so it is safe either way, but the simplest thing is not to
> add keys you are not filling in.

[`.env.example`](.env.example) lists everything the app can read.

Deploy. The app will be at `https://<service-name>.onrender.com`, showing the
same Drive folders, ERP files, cost sheet and sales data as it does locally —
it reads them live from the same Google account, so there is no data to migrate.

## What to know about the hosting

**The filesystem is not durable.** Render rebuilds the container on every deploy
and restart. Two consequences, both already handled:

- Credentials are read from `GOOGLE_TOKEN_JSON`, not from a file, so they
  survive deploys. A refreshed access token is *not* written back to disk when
  the env var is in use — the refresh token in the variable keeps working.
- The worksheet-title cache moves to the system temp directory on Render. It
  just repopulates itself after a restart.

**The database is sqlite and also not durable.** This app defines no models of
its own — the database only holds sessions, messages and admin logins — so
losing it on deploy costs nothing beyond re-logging into `/admin/`. If you want
it durable, add a Render Postgres instance and set `DATABASE_URL`; `settings.py`
picks it up automatically and `psycopg` is already in `requirements.txt`.

**Requests can be slow.** Reading a large workbook goes through the Sheets API
with a 180-second socket timeout, so the gunicorn worker timeout is set to 300s.
Do not lower it below the socket timeout or workers get killed mid-request.

**The free plan sleeps** after inactivity, so the first request after a quiet
period takes ~30s to wake. It also has 512 MB of RAM, which the larger workbooks
can exhaust — move to the `starter` plan if you see out-of-memory restarts.

## Anyone can reach it

There is no login on any page. Once deployed, the URL is public and exposes your
ERP data and Drive contents to anyone who has it. If that is not what you want,
put the views behind `login_required` before sharing the link.
