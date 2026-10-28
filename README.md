# MyProgress

A developer platform that combines Git hosting with verified portfolios, recruiter search, rankings, and learning content.

- **Developers** push code over HTTPS, publish "how I built this" posts, and get a public portfolio with languages measured from their code.
- **Recruiters** search developers by verified languages and activity, keep shortlists, and send contact requests.

## Requirements

| Tool | Version | Why |
|---|---|---|
| Python | 3.12 or newer (developed on 3.13) | Django 6.0 needs 3.12+ |
| PostgreSQL | 14 or newer | The only supported database |
| Git | 2.38 or newer, on `PATH` | Repository hosting, diffs and merges; the tests push to a live server |

Every Python package is pinned in [requirements.txt](requirements.txt). Nothing else needs installing: no Node.js, no ffmpeg, no Redis for local work.

## Initial setup

### 1. Create the database

In `psql` as a superuser:

```sql
CREATE USER myprogress WITH PASSWORD 'choose-a-password' CREATEDB;
CREATE DATABASE myprogress OWNER myprogress;
```

`CREATEDB` lets `manage.py test` create and drop its own `test_myprogress` database.

### 2. Install the packages

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure `.env`

Copy `.env.example` to `.env`. It's written for production, so change these lines for local work:

```ini
SECRET_KEY=<output of: python -c "import secrets; print(secrets.token_urlsafe(64))">
DEBUG=true
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
SITE_URL=http://localhost:8000
DB_PASSWORD=<the password from step 1>
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

Delete the `GIT_REPOSITORY_ROOT` and `MEDIA_ROOT` lines so that repositories and uploads go to `repositories/` and `media/` in the project folder. Git ignores both folders. Leave every other value as it is. With the console email backend, confirmation and password-reset emails print in the terminal that runs the server.

Never commit `.env`.

### 4. Create the tables and an admin account

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 5. Run it

```bash
python manage.py runserver
```

Open http://localhost:8000. The Django admin is at `/admin/`. With `DEBUG=true` the development server serves static files and uploads itself, so you don't need `collectstatic`.

## Optional features

| Feature | How to turn it on |
|---|---|
| AI-written drafts in the learning studio | Set `ANTHROPIC_API_KEY` in `.env`. Without it, the studio writes starter drafts from the branch. |
| Finance console (`/finance/`) | `python manage.py create_finance_admin you@example.com` |
| Rankings | `python manage.py refresh_scores` (daily in production) |
| Two-way video calls in live classes | A self-hosted Jitsi Meet server; see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#two-way-video-calls-optional) |
| Creator payouts through RazorpayX | The four `RAZORPAYX_*` settings |

You don't need cron for local work. Class reminders and scheduled posts, lectures and tasks also run while people use the site, at most once a minute. To try the other scheduled jobs, run them by hand: `run_organization_jobs`, `send_parent_digests`, and `run_payment_cycle`.

## Tests

```bash
python manage.py test
```

`manage.py test` uses `config/settings/test.py` automatically. Repositories and uploads go to a temporary folder, and the AI key is blanked. The tests need PostgreSQL (with `CREATEDB`, see step 1) and Git on `PATH`.

After you change the app's stylesheets, run `python manage.py build_ide_css` to regenerate the developer-mode theme (`ide-auto.css`). A test fails if that file is out of date.

## What's in requirements.txt

| Package | Used for |
|---|---|
| Django | The web framework |
| djangorestframework, djangorestframework_simplejwt, django-filter, drf-spectacular, django-cors-headers | REST API, JWT sign-in, filtering, API schema, CORS |
| psycopg2-binary | PostgreSQL driver |
| python-decouple | Reads settings from `.env` |
| whitenoise | Serves static files in production |
| argon2-cffi | Password hashing |
| pillow | Profile pictures, thumbnails and other images |
| segno | QR codes for two-step sign-in |
| PyJWT | Room passes for a token-protected Jitsi server |
| anthropic | Claude API for learning studio drafts |
| gunicorn | Production app server (Linux and macOS; it installs on Windows but can't run there) |
| redis | Shared rate-limit cache when `REDIS_URL` is set |

Every other line is a dependency of these packages, pinned so that every install matches. After you add a package, run `pip freeze > requirements.txt` from a clean virtual environment.

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
