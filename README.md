# BrainCare

Django/DRF backend for patient medication tracking, caregiver pairing,
notifications, water intake, and offline synchronization.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements/development.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py runserver
```

Start PostgreSQL and Redis, or update `DATABASE_URL` and `REDIS_URL` in `.env`.
Use PostgreSQL for production. Development falls back to a local in-memory
cache when `REDIS_URL` is absent.

## API

- Swagger UI: `http://localhost:8000/api/docs/`
- OpenAPI schema: `http://localhost:8000/api/schema/`
- API guide: [`docs/API.md`](docs/API.md)
- Offline sync contract: [`docs/SYNC_CONTRACT.md`](docs/SYNC_CONTRACT.md)
- Security notes: [`docs/SECURITY.md`](docs/SECURITY.md)
- Testing: [`docs/TESTING.md`](docs/TESTING.md)
- Deployment: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)

## Tests and checks

```powershell
python manage.py test --settings=config.settings.test
python -m coverage run --rcfile=.coveragerc manage.py test --settings=config.settings.test
python -m coverage report --rcfile=.coveragerc
python manage.py makemigrations --check --dry-run --settings=config.settings.test
python manage.py spectacular --settings=config.settings.test --file docs/openapi.yaml --validate
```

## Docker

```powershell
Copy-Item .env.docker.example .env.docker
docker compose up --build
```

The compose stack is for local container testing. Production deployment uses
the `Dockerfile` with `config.settings.production`; see
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Layout

- `apps/accounts`: authentication, profiles, caregiver pairing.
- `apps/medications`: medications, schedules, dose occurrences, dose events.
- `apps/notifications`: FCM devices, notification outbox, Celery dispatch.
- `apps/water`: water settings, intake logs, daily summaries.
- `apps/sync`: cursor change feed and idempotent offline push.
- `apps/core`: permissions, pagination, error handling, health checks.
- `config`: settings, URLs, Celery, logging, WSGI entry point.
