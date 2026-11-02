# Security hardening

This document records the application-level hardening implemented in the
repository and the items that require infrastructure or operational changes.
It is not a claim that the system is fully secure.

## Implemented controls

- Django admin is mounted only when `DJANGO_ADMIN_ENABLED=true`. It defaults to
  `DEBUG` in development and is disabled by default in production.
- Password minimum length defaults to 12 and is configurable with
  `PASSWORD_MIN_LENGTH`. Common-password and numeric-password validators remain
  enabled.
- Production startup refuses weak or incomplete security configuration:
  - `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, and `REDIS_URL` are required.
  - `PAIRING_CODE_PEPPER` is required.
  - `FCM_TOKEN_ENCRYPTION_KEY` is required when `FCM_ENABLED=true`.
  - JWT access tokens must expire within 60 minutes and refresh tokens within
    30 days.
  - Pairing codes must be at least 8 characters and allow at least 3 failed
    attempts before throttling.
- JWT refresh rotation and blacklist-after-rotation are enabled. Logout
  blacklists the refresh token.
- Production enables HTTPS redirect, secure cookies, HTTP-only session cookies,
  `SameSite=Lax` cookies, HSTS, `nosniff`, referrer policy, and a same-origin
  opener policy.
- Registration, login, pairing generation, pairing redemption, and sync have
  scoped throttles.
- Object-level permissions restrict patient/caregiver access. Caregivers must
  have an active link with `can_view`; medication editing additionally requires
  `can_edit_medications`.
- Pairing codes are short-lived, single-use, hashed, and rate limited. Raw codes
  are returned once.
- FCM tokens are encrypted at rest; API responses expose only a preview and
  fingerprint. Push payloads avoid medication names and other clinical details.
- API errors use a generic envelope and do not expose stack traces, SQL, or
  secrets. Readiness failures are logged but not returned.
- Sync writes use idempotency keys and optimistic version checks where
  applicable; client timestamps are not trusted for server ordering.

## Verification

```powershell
python manage.py test --settings=config.settings.test
python manage.py check --deploy --settings=config.settings.production
python manage.py spectacular --settings=config.settings.test --file docs/openapi.yaml --validate
```

Security-focused tests cover admin exposure, password policy, JWT settings,
throttle scopes, FCM defaults, pairing abuse, object permissions, sync
authorization, and error redaction behavior.

## Required infrastructure and operations work

These cannot be completed safely from application code alone:

- Terminate TLS at a trusted proxy/load balancer and forward
  `X-Forwarded-Proto`; only then set `SECURE_PROXY_SSL_HEADER`.
- Manage `DJANGO_SECRET_KEY`, `PAIRING_CODE_PEPPER`, database credentials,
  Redis credentials, and FCM service-account material in a secrets manager.
  Never commit them or place them in images.
- Require TLS and least-privilege credentials for PostgreSQL and Redis. Enable
  provider backups, point-in-time recovery, and restore testing.
- Restrict PostgreSQL/Redis network access to application and operations
  networks. Do not expose either service publicly.
- Restrict Django admin to a VPN, bastion, or allowlisted network if it is
  enabled. Prefer keeping it disabled.
- Add edge/WAF rate limiting and bot protection for authentication and pairing
  endpoints in addition to application throttles.
- Configure centralized log retention and access control. Avoid logging
  authorization headers, FCM tokens, pairing codes, or clinical payloads.
- Run dependency and container vulnerability scanning in CI, pin and review
  updates, and rebuild images regularly.
- Protect FCM service-account credentials and rotate them on exposure. Keep
  mobile token storage in platform secure storage.
- Define incident response, key-rotation, and account-recovery procedures.

## Residual risks

- No MFA or step-up authentication is implemented.
- Login throttling is cache-backed and depends on a healthy shared cache; a
  multi-region deployment needs a shared or edge rate-limit strategy.
- Password breach-list checking is not implemented; only Django's local common
  password list is used.
- CORS is not configured because the current clients are native mobile apps.
  Add a reviewed allowlist before exposing browser clients.
- API schema and Swagger UI are public. They document the API but do not expose
  patient data.
- Application-level controls do not replace network isolation, backups,
  monitoring, or secret management.
