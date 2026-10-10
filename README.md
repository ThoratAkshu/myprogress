# MyProgress

A developer platform that combines Git hosting with verified portfolios, recruiter search, rankings, and learning content.

- **Developers** push code over HTTPS, publish "how I built this" posts, and get a public portfolio with languages measured from their code.
- **Recruiters** search developers by verified languages and activity, keep shortlists, and send contact requests.

## Local development

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows; use source .venv/bin/activate elsewhere
pip install -r requirements.txt
cp .env.example .env              # then fill in SECRET_KEY and the database settings
python manage.py migrate
python manage.py runserver
```

Run the tests with `python manage.py test`. Git must be installed.

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
