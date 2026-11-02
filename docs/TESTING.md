# Testing

## Commands

```powershell
python manage.py test --settings=config.settings.test
python -m coverage run --rcfile=.coveragerc manage.py test --settings=config.settings.test
python -m coverage report --rcfile=.coveragerc
```

`.coveragerc` omits migrations, test modules, admin registrations, and process
entry points, and fails below 85% total coverage.

## Current result

- **277 tests pass** on the SQLite in-memory test database with eager Celery
  and disabled throttles.
- **90% statement coverage** across `apps/` and `config/` (excluding the files
  listed above).
- `makemigrations --check --dry-run` reports no changes.
- `compileall` succeeds.
- `check --deploy` succeeds with production settings and test-only environment
  values.
- OpenAPI schema generation validates without warnings.

## Coverage by area

| Area | What is exercised |
| --- | --- |
| Authentication | Registration, login, refresh, logout, profile, password validation, throttling. |
| Pairing | Code generation, redemption, expiry, wrong codes, attempt limits, revocation, caregiver permissions. |
| Medications | CRUD, ownership rules, schedule validation, recurrence, generation, regeneration, deactivation. |
| Dose lifecycle | Confirm, skip, snooze, idempotency, conflicts, overdue escalation, audit events, patient-only actions. |
| Notifications | Device registration/deactivation, token privacy, outbox idempotency, retries, dead letters, stale processing recovery, FCM classification and payloads. |
| Water | Settings defaults/bounds, timezone boundaries, intake history, summaries, caregiver reads, sync records. |
| Sync | Cursor pagination, tombstones, permissions, duplicate events, interrupted batches, conflicts, late client timestamps, separate occurrence/event IDs. |
| Security | Admin gating, password policy, JWT settings, throttle scopes, FCM defaults, log redaction, object-level access. |
| API docs | Public schema, Swagger UI, expected paths, JWT scheme, no admin path. |
| Core | Error envelope, request IDs, health readiness/liveness, pagination, beat schedule. |

## Gaps

These are intentionally not simulated as full integration tests:

- Live Firebase delivery and credentials. Provider behavior is mocked and
  classified, but end-to-end delivery needs a staging project.
- PostgreSQL-specific behavior under concurrency and load. Tests use SQLite;
  run the suite against PostgreSQL in CI before release.
- Real Redis and Celery workers. Tests use eager mode and mocked dispatch.
- Production settings module branch coverage. It is verified with
  `check --deploy`, but not unit-tested for every invalid environment.
- Mobile offline conflict behavior and device clock skew. The server contract is
  tested; the Flutter client needs its own tests.
- Load, soak, and penetration testing.
