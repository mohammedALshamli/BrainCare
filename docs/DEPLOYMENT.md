# Deployment

The application is a Django API with a Celery worker and a single Celery beat
scheduler. PostgreSQL is the source of truth; Redis backs the cache, Celery
broker, and result backend. Static files are collected at image build time and
must be served by the edge proxy or a CDN.

## Local container stack

```powershell
Copy-Item .env.docker.example .env.docker
docker compose up --build
```

The local stack uses `config.settings.development`, applies migrations once in
the `web` container, and exposes the API at `http://localhost:8000/`. It is not
a production configuration.

Smoke test:

```powershell
Invoke-RestMethod http://localhost:8000/health/live/
Invoke-RestMethod http://localhost:8000/health/ready/
Invoke-WebRequest http://localhost:8000/api/docs/
```

## Production image

```powershell
docker build -t braincare-api:<git-sha> .
```

The image runs as an unprivileged user, uses Gunicorn, and expects
`DJANGO_SETTINGS_MODULE=config.settings.production` (the image default). It
does not run migrations unless `RUN_MIGRATIONS=1` is set.

Required production configuration includes:

- `DJANGO_SECRET_KEY` (at least 50 characters, not a development value)
- `DJANGO_ALLOWED_HOSTS`
- `DATABASE_URL` or the `POSTGRES_*` variables
- `REDIS_URL`
- `PAIRING_CODE_PEPPER`
- `FCM_TOKEN_ENCRYPTION_KEY` when `FCM_ENABLED=true`
- `DJANGO_CSRF_TRUSTED_ORIGINS` for browser-facing origins
- Firebase credentials (`FIREBASE_CREDENTIALS_JSON` or
  `FIREBASE_CREDENTIALS_PATH`) when FCM is enabled

Keep all of these in a secrets manager and inject them at runtime. Do not bake
them into the image or commit them.

## Release procedure

1. Back up PostgreSQL and confirm the restore procedure is usable.
2. Run migrations as a single one-off job, not from every web replica:

   ```powershell
   docker run --rm --env-file .env.production `
     braincare-api:<git-sha> python manage.py migrate --noinput
   ```

3. Start or roll the web containers. Keep at least two replicas behind a
   TLS-terminating load balancer.
4. Run exactly one worker deployment and exactly one beat scheduler. Multiple
   beat schedulers duplicate periodic work.

   > **Warning — single Celery Beat instance.** The default file-based or
   > database-backed Celery Beat scheduler does **not** coordinate across
   > replicas. Running more than one Beat process causes every periodic task
   > (overdue-dose checks, stale-worker recovery, water reminders) to execute
   > once per replica per interval, producing duplicate notifications and
   > unnecessary database load.
   >
   > If you need high-availability Beat scheduling, adopt a distributed
   > scheduler such as `django-celery-beat` with a database-backed schedule
   > and a `redbeat` or `celery-singleton` lock, and verify that each periodic
   > task is executed exactly once per interval. Do not simply scale the Beat
   > deployment to multiple replicas without such a mechanism.
5. Verify `/health/live/` and `/health/ready/` from inside the network. The
   readiness probe checks both the database and cache.
6. Run the smoke tests below and monitor error rate, latency, queue depth, and
   notification dead letters.

```powershell
Invoke-RestMethod https://api.example.com/health/live/
Invoke-RestMethod https://api.example.com/health/ready/
Invoke-WebRequest https://api.example.com/api/docs/
```

## Reverse proxy and TLS

Terminate TLS at the proxy and forward `X-Forwarded-Proto: https`. The
production settings trust that header, so only expose the app through a trusted
proxy. Serve `staticfiles/` from the proxy or CDN; do not route static traffic
to Gunicorn. Restrict `/admin/` to a VPN or allowlist, or leave
`DJANGO_ADMIN_ENABLED=false`.

## Backups and restore

- Take scheduled PostgreSQL backups with `pg_dump -Fc` or the provider's
  managed backup feature. Retain backups according to the privacy policy.
- Test restore into an isolated database before relying on a backup.
- Redis is not the source of truth. Losing Redis loses cache entries and
  in-flight Celery messages; the notification outbox remains in PostgreSQL and
  can be dispatched again. Beat schedule state is in the beat volume.
- Never delete the PostgreSQL volume or run destructive migrations without a
  verified backup.

## Rollback

- Roll back by deploying the previous image tag.
- Database migrations are forward-only. Prefer expand/contract migrations so
  the previous application version can run during a rollback window.
- If a migration is not backward compatible, restore the pre-release backup
  and accept the associated data-loss window; record the decision.
- Roll back web, worker, and beat together so task payloads and schema changes
  stay compatible.

## Operational checks

- Confirm one beat scheduler and the expected periodic tasks are registered.
- Confirm workers can reach Redis and PostgreSQL.
- Confirm FCM credentials are valid and dead-letter volume is understood.
- Confirm logs are centralized, redacted, and retained per policy.
- Confirm dependency and container image scanning runs in CI.
- Review [`SECURITY.md`](SECURITY.md) before exposing the service publicly.
