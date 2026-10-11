# Deploying MyProgress

This guide covers a single-server production deployment: Django served by
gunicorn behind nginx, with PostgreSQL. It also lists what to add as traffic
grows.

## What runs where

| Piece | Purpose | Notes |
|---|---|---|
| nginx | TLS, static and uploaded files, proxy to gunicorn | Serves `/media/` directly |
| gunicorn | Runs Django (`config.wsgi`) | Streams Git pushes; sets `wsgi.input_terminated` |
| PostgreSQL | All application data | |
| Git ≥ 2.38 | Hosting, diffs, merges | 2.38+ is needed for pull-request conflict detection |
| Disk: `GIT_REPOSITORY_ROOT` | Bare repositories | Back up |
| Disk: `MEDIA_ROOT` | Uploaded videos and images | Back up |
| Redis (optional) | Shared cache for rate limits | Required with more than one gunicorn worker for limits to be shared |
| Claude API (optional) | AI drafts in the learning studio | Set `ANTHROPIC_API_KEY`; without it the studio writes starter drafts from the branch |

## 1. Configure

Copy `.env.example` to `.env` and fill in every value. Before going live:

- `SECRET_KEY` is long and random: `python -c "import secrets; print(secrets.token_urlsafe(64))"`
- `DEBUG=false`
- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` list your real domain (`https://…` for CSRF)
- Email settings point at a real SMTP provider (used for email confirmation and password reset)
- `TRUST_X_FORWARDED_FOR=true` only if nginx sets that header (config below does)
- `ANTHROPIC_API_KEY` is set if you want AI-written learning drafts. The studio sends the
  branch's README, dependency files, file paths, and commit messages (never source files)
  to the Claude API, and each author can request 20 drafts an hour.

Production settings refuse to start without `ALLOWED_HOSTS`.

## 2. Install and prepare

```bash
python -m venv /opt/myprogress/venv
/opt/myprogress/venv/bin/pip install -r requirements.txt gunicorn
export DJANGO_SETTINGS_MODULE=config.settings.production
python manage.py check --deploy        # should report no issues
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
python manage.py refresh_languages     # backfill languages for existing repositories
python manage.py refresh_scores
```

## 3. Run gunicorn

```bash
DJANGO_SETTINGS_MODULE=config.settings.production \
gunicorn config.wsgi --bind 127.0.0.1:8000 --workers 3 --timeout 660
```

`--timeout` must exceed `GIT_HTTP_TIMEOUT` (600 s by default) so large pushes and
clones are not cut off. Run it under systemd (or your process manager) with
restart on failure.

## 4. nginx

```nginx
server {
    listen 443 ssl http2;
    server_name myprogress.example.com;
    # ssl_certificate / ssl_certificate_key …

    # Git pushes can be large; keep this ≥ GIT_MAX_REQUEST_BYTES.
    client_max_body_size 1g;

    location /media/ {
        alias /var/lib/myprogress/media/;
        # User uploads must never run as part of the site.
        add_header Content-Security-Policy "sandbox" always;
        add_header X-Content-Type-Options "nosniff" always;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_read_timeout 660s;
        proxy_send_timeout 660s;
    }
}
```

Static files are served by WhiteNoise from `collectstatic` output, hashed and
compressed.

## 5. Scheduled jobs

| Schedule | Command | Why |
|---|---|---|
| Daily | `python manage.py refresh_scores` | Scores use a 90-day window and must decay over time; it also saves each day's ranks so Rankings can show weekly movement and climbers |
| After restores | `python manage.py refresh_languages` | Rebuilds language data from repositories |

## 6. Backups

Back up all three together so they stay consistent:

1. PostgreSQL (`pg_dump`)
2. `GIT_REPOSITORY_ROOT` (the bare repositories)
3. `MEDIA_ROOT` (uploads)

## 7. Health checks

`GET /healthz` returns `200 {"status": "ok", "database": "ok", "git": "ok"}`, or
`503` if the database or Git is unavailable. Point your load balancer or uptime
monitor at it.

## Security features to know about

- **Rate limits:** failed sign-ins lock an email for 15 minutes after 10 failures
  (30 per IP address); failed Git sign-ins are throttled per IP address; sign-ups,
  comments, issues, follows, publishing, and password-reset requests have per-user
  or per-IP limits. Limits live in the cache, so use Redis with multiple workers.
- **Recruiter verification:** recruiters who confirm an email on a company domain
  are marked verified and can send 20 contact requests a day; unverified ones
  can send 3.
- **Uploads:** videos are signature-checked MP4/WebM; raw repository files are
  served as `text/plain` or downloads with a sandboxing CSP, never as HTML.

## Not included yet, and how to add it

- **Object storage for uploads:** install `django-storages` and set
  `MEDIA_STORAGE_BACKEND` to its S3 backend (plus its bucket settings). Serve the
  bucket through a CDN with the same sandbox CSP header.
- **Background jobs:** language detection and score updates run inside the
  request and take milliseconds today. If pushes to very large repositories get
  slow, move `_record_push` in `apps/landing/views.py` to a task queue.
- **SSH Git access:** HTTPS with access tokens works everywhere. SSH needs an
  OpenSSH `AuthorizedKeysCommand` plus a wrapper that checks repository access,
  similar to Gitea or GitLab.

See also [GIT_DEPLOYMENT.md](GIT_DEPLOYMENT.md) for how MyProgress calls Git.
