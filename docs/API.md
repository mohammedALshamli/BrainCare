# BrainCare API

Interactive documentation is generated from the running code:

- OpenAPI schema: `GET /api/schema/`
- Swagger UI: `GET /api/docs/`
- Machine-readable schema: `docs/openapi.yaml`

The schema is generated with `drf-spectacular`; do not hand-edit
`docs/openapi.yaml`. Regenerate it after API changes:

```powershell
python manage.py spectacular --settings=config.settings.test --file docs/openapi.yaml --validate
```

## Base URLs

- API: `/api/v1/`
- Health: `/health/` (readiness), `/health/live/`, `/health/ready/`
- API docs: `/api/docs/`

## Authentication

All endpoints except registration, login, token refresh, health checks, and the
documentation pages require a JWT access token:

```http
Authorization: Bearer <access_token>
```

Access tokens expire after 15 minutes and refresh tokens after 7 days. Refresh
tokens rotate and old refresh tokens are blacklisted. Logout blacklists the
supplied refresh token.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/register/` | Public | Create a patient or caregiver account. |
| POST | `/api/v1/auth/login/` | Public | Return access/refresh tokens and user profile. |
| POST | `/api/v1/auth/refresh/` | Public | Rotate a refresh token. |
| POST | `/api/v1/auth/logout/` | JWT | Blacklist a refresh token. |
| GET | `/api/v1/auth/me/` | JWT | Return the current user. |

Registration and login are throttled. Repeated failed logins and pairing-code
attempts are rate limited.

## Pairing

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/v1/pairing/codes/` | Patient | Create a short-lived one-time pairing code and QR payload. |
| POST | `/api/v1/pairing/redeem/` | Caregiver | Redeem a code and create an active relationship. |
| GET | `/api/v1/pairing/relationships/` | JWT | List relationships involving the current user. |
| GET | `/api/v1/pairing/relationships/{id}/` | Participant | Retrieve a relationship. |
| PUT/PATCH | `/api/v1/pairing/relationships/{id}/` | Patient | Update caregiver permissions. |
| POST | `/api/v1/pairing/relationships/{id}/revoke/` | Participant | Revoke the relationship. |

Caregivers only see linked patients with `is_active=true` and `can_view=true`.
Medication editing additionally requires `can_edit_medications=true`. Dose
confirmation and skipping require `can_confirm_doses=true`, which defaults to
`false` for newly linked caregivers and cannot be granted without `can_view`.

## Medications, schedules, and doses

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET/POST | `/api/v1/medications/` | JWT / Patient | List accessible medications or create one. |
| GET/PUT/PATCH | `/api/v1/medications/{id}/` | JWT / editor | Read or update a medication. |
| POST | `/api/v1/medications/{id}/deactivate/` | JWT / editor | Deactivate a medication and its schedules. |
| GET/POST | `/api/v1/medications/{medication_id}/schedules/` | JWT / editor | List or create schedules. |
| GET/PUT/PATCH | `/api/v1/schedules/{id}/` | JWT / editor | Read or update a schedule. |
| POST | `/api/v1/schedules/{id}/deactivate/` | JWT / editor | Deactivate a schedule and soft-cancel future pending doses. |
| GET | `/api/v1/doses/` | JWT | List accessible dose occurrences. Cancelled doses are hidden unless `status=cancelled` is requested. |
| GET | `/api/v1/doses/{id}/` | JWT | Retrieve a dose occurrence, including cancelled rows. |
| POST | `/api/v1/doses/{id}/confirm/` | Patient / dose confirmer | Mark a dose as taken. |
| POST | `/api/v1/doses/{id}/skip/` | Patient / dose confirmer | Mark a dose as skipped. |
| POST | `/api/v1/doses/{id}/snooze/` | Patient / dose confirmer | Snooze a non-terminal dose. |
| GET | `/api/v1/doses/{id}/events/` | JWT | List immutable audit events for a dose. |

Dose actions require a `client_event_id` idempotency key. Replaying the same
key returns the original outcome and does not create a duplicate event.
Caregiver actions are attributed to the caregiver in `DoseEvent.actor` and use
`source="caregiver_app"`.

Schedule regeneration and deactivation never hard-delete future pending doses.
They set `status="cancelled"`, `cancelled_at`, `cancellation_reason`, and
`superseded_by` when a same-day replacement exists. A late offline confirmation
or skip is still accepted against the cancelled row and is flagged with
`confirmed_after_cancellation` or `skipped_after_cancellation`; the response
also exposes `recorded_against_superseded` and `superseded_by_id`.

### Dose action body

```json
{
  "client_event_id": "8f14e45f-ea0e-4f5f-9f0e-0d6f0f6f0f6f",
  "client_recorded_at": "2026-11-01T08:30:00Z",
  "source": "patient_app",
  "minutes": 15
}
```

`minutes` is accepted only by `snooze` and is capped by
`DOSE_SNOOZE_MAX_MINUTES`.

## Water

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/water/settings/` | JWT | Read reminder settings for the patient. |
| PUT/PATCH | `/api/v1/water/settings/` | Patient | Update reminder settings. |
| GET/POST | `/api/v1/water/intake/` | JWT / Patient | List or record water intake. |
| GET | `/api/v1/water/intake/{id}/` | JWT | Retrieve a water intake log. |
| GET | `/api/v1/water/summary/` | JWT | Daily total, goal, and remaining amount. |

Caregivers pass `?patient=<user_id>` for patient-scoped reads. Water intake
amounts must be between 1 and 5000 ml. Settings allow an interval of 15–720
minutes, an optional daily goal of 100–20000 ml (send `null` to clear it), and a
cup size of 50–2000 ml. When no goal is set, the summary returns `goal_ml`,
`remaining_ml`, `progress_percentage`, and `goal_reached` as `null`.

## Notifications

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET/POST | `/api/v1/devices/` | JWT | List devices or register/update an FCM token. |
| GET/DELETE | `/api/v1/devices/{id}/` | JWT | Retrieve or deactivate a device. |

FCM tokens are write-only on registration and are stored encrypted. Device
responses expose only a token preview and fingerprint.

## Offline synchronization

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/sync/changes/` | JWT | Cursor-based change feed. |
| POST | `/api/v1/sync/push/` | JWT | Idempotent batch push of offline events. |

The cursor is a monotonic server sequence, not a timestamp. The full client
contract, conflict handling, and examples are in
[`SYNC_CONTRACT.md`](SYNC_CONTRACT.md).

## Pagination, filtering, and errors

List endpoints are paginated with `page` and `page_size` query parameters.
Medication, dose, water, and relationship lists support the filters declared by
their filtersets; medication and dose lists also support `search` and
`ordering` where documented in the schema.

Errors use one envelope:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": {
      "amount_ml": ["Ensure this value is less than or equal to 5000."]
    },
    "request_id": "..."
  }
}
```

Common status codes are `400`, `401`, `403`, `404`, `409`, `429`, and `500`.
`409` is used for state/version conflicts. Throttled responses include `429`
and the standard `Retry-After` header where applicable.

## Example

```powershell
$login = Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8000/api/v1/auth/login/" `
  -ContentType "application/json" `
  -Body '{"email":"patient@example.com","password":"correct-horse-battery"}'

$headers = @{ Authorization = "Bearer $($login.access)" }
Invoke-RestMethod -Method Get `
  -Uri "http://localhost:8000/api/v1/doses/" `
  -Headers $headers
```
