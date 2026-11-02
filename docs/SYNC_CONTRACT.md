# BrainCare Offline Synchronization Contract

This document is the contract for the Flutter patient application. The server is
authoritative. Clients may queue actions while offline, but they must not assume
that a queued action will overwrite a newer server state.

## Base endpoints

All endpoints require `Authorization: Bearer <access-token>`.

| Method | URL | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/sync/changes/` | Download changed records using a cursor |
| `POST` | `/api/v1/sync/push/` | Upload client-generated offline events |

Patients may upload dose and water actions. A caregiver may download changes for
a linked patient with `can_view=true`. Caregivers may upload `dose.confirm`,
`dose.skip`, and `dose.snooze` only while their active link has
`can_confirm_doses=true`; water writes by caregivers are rejected. The server
derives the actor and source from the authenticated user.

## Download: cursor-based change feed

### Request

```http
GET /api/v1/sync/changes/?cursor=0&limit=50
```

Optional parameters:

| Parameter | Meaning |
| --- | --- |
| `cursor` | Last successfully applied server cursor. Start at `0`. |
| `limit` | Page size, 1–200. Defaults to the server `SYNC_PAGE_SIZE`. |
| `patient` | Patient id for a caregiver. The patient must be actively linked and viewable. |

The cursor is the monotonic `sequence` of a `SyncChange` row. It is **not** a
timestamp. Two changes written in the same clock tick still receive different
sequences. Never use `updated_at` as the download cursor.

Sequence allocation takes a database row lock and the lock is held until the
change transaction commits. A higher cursor is therefore never visible before
every lower cursor has committed, including when concurrent requests write
changes for different patients. A rolled-back change does not advance the
cursor. Requests may briefly block on this lock; clients should keep retries
idempotent rather than assume the cursor is gap-free under manual intervention.

### Response

```json
{
  "changes": [
    {
      "cursor": 41,
      "entity_type": "dose_occurrence",
      "object_id": "f13f1e1d-2d4f-4e73-a2f5-3c1e5b7a9d10",
      "operation": "upsert",
      "data": {
        "occurrence_id": "f13f1e1d-2d4f-4e73-a2f5-3c1e5b7a9d10",
        "patient_id": 7,
        "medication_id": "5a7b9c0d-1e2f-4a3b-8c9d-0e1f2a3b4c5d",
        "schedule_id": "9b8c7d6e-5f4a-3b2c-1d0e-9f8a7b6c5d4e",
        "scheduled_at": "2026-11-01T08:00:00+00:00",
        "scheduled_date": "2026-11-01",
        "status": "taken",
        "alert_status": "none",
        "taken_at": "2026-11-01T08:04:00+00:00",
        "skipped_at": null,
        "snoozed_until": null,
        "snooze_count": 0,
        "cancelled_at": null,
        "cancellation_reason": null,
        "superseded_by_id": null,
        "created_at": "2026-10-30T12:00:00+00:00",
        "updated_at": "2026-11-01T08:04:00+00:00"
      },
      "patient": 7,
      "changed_at": "2026-11-01T08:04:00.123456+00:00"
    }
  ],
  "next_cursor": 41,
  "has_more": true,
  "server_time": "2026-11-01T08:04:01.000000+00:00"
}
```

Client algorithm:

1. Read locally persisted `next_cursor`.
2. Call `GET /changes/?cursor=<next_cursor>`.
3. Apply `changes` in ascending `cursor` order inside one local transaction.
4. Persist `next_cursor` only after the local transaction commits.
5. Repeat while `has_more=true`.
6. If interrupted, retry from the last committed `next_cursor`; the server may
   return the same records again. Applying an upsert twice is safe.

`next_cursor` does not advance when no changes exist. A client may poll
periodically. Do not infer deletion from absence; only `operation="delete"` is a
tombstone.

### Entity types and data

| `entity_type` | Identity field | Notes |
| --- | --- | --- |
| `medication` | `data.id` | Medication snapshot |
| `schedule` | `data.id` | Schedule snapshot; includes `medication_id` |
| `dose_occurrence` | `data.occurrence_id` | Server-generated occurrence id |
| `dose_event` | `data.event_id` | Append-only event; includes `occurrence_id` |
| `water_intake` | `data.water_intake_id` | Includes `client_event_id` when supplied |
| `water_settings` | `data.water_settings_id` | Patient reminder settings |

Dose occurrences and dose events have **separate UUIDs**. An event always carries
the `occurrence_id` it belongs to. Do not use an event id as an occurrence id.

### Cancellation and superseding

The API does not hard-delete medications, schedules, or dose occurrences.
Deactivating a medication or schedule is an `upsert` with `is_active=false`.
Generated future pending dose occurrences that are no longer required are
soft-cancelled with an `upsert`, not a tombstone:

```json
{
  "cursor": 42,
  "entity_type": "dose_occurrence",
  "object_id": "cancelled-occurrence-uuid",
  "operation": "upsert",
  "data": {
    "occurrence_id": "cancelled-occurrence-uuid",
    "status": "cancelled",
    "cancelled_at": "2026-11-01T08:10:00+00:00",
    "cancellation_reason": "schedule_changed",
    "superseded_by_id": "replacement-occurrence-uuid"
  },
  "patient": 7,
  "changed_at": "2026-11-01T08:10:00+00:00"
}
```

`cancellation_reason` is one of `schedule_changed`,
`schedule_deactivated`, or `medication_deactivated`. `superseded_by_id` points to
the nearest same-day replacement when one exists. The client must retain the
row, mark it cancelled, and hide it from the active dose list. Historical
completed/overdue/snoozed occurrences are never cancelled by regeneration.

A late offline `dose.confirm` or `dose.skip` against a cancelled occurrence is
still accepted. The server applies the event, records
`confirmed_after_cancellation` or `skipped_after_cancellation`, and returns
`recorded_against_superseded` plus `superseded_by_id` so the client can explain
that the action applied to an older schedule version.

## Upload: idempotent offline events

### Request

```http
POST /api/v1/sync/push/
Content-Type: application/json
```

```json
{
  "batch_id": "0f2f6c1e-6f1d-4a5f-9f2b-3f1c2d3e4f50",
  "device_identifier": "pixel-8",
  "changes": [
    {
      "client_event_id": "a4c4d8f8-3a9b-4e4f-8c1e-1a2b3c4d5e6f",
      "type": "dose.confirm",
      "occurrence_id": "f13f1e1d-2d4f-4e73-a2f5-3c1e5b7a9d10",
      "client_recorded_at": "2026-11-01T08:03:30+00:00",
      "expected_version": 12
    },
    {
      "client_event_id": "b5d5e9f9-4b0c-4f5a-9d2e-2b3c4d5e6f70",
      "type": "water.intake.create",
      "amount_ml": 250,
      "consumed_at": "2026-11-01T08:02:00+00:00",
      "source": "cup",
      "notes": "offline entry"
    }
  ]
}
```

`batch_id` and `device_identifier` are optional and are echoed/stored for
diagnostics. A batch may contain at most `SYNC_MAX_BATCH_SIZE` items (default
100).

### Item types

| Type | Required fields | Server behavior |
| --- | --- | --- |
| `dose.confirm` | `client_event_id`, `occurrence_id` | Confirms an accessible occurrence; marks late if server grace period has passed; accepts cancelled rows with `confirmed_after_cancellation` |
| `dose.skip` | `client_event_id`, `occurrence_id` | Skips a pending/overdue/cancelled occurrence; accepts cancelled rows with `skipped_after_cancellation` |
| `dose.snooze` | `client_event_id`, `occurrence_id`, `minutes` | Snoozes a non-terminal, non-cancelled occurrence |
| `water.intake.create` | `client_event_id`, `amount_ml` | Creates one water log; `consumed_at` defaults to server time |

`client_event_id` must be a client-generated UUID and is globally unique. It is
the idempotency key. If the same item is retried, the server returns
`status="duplicate"` and does not create a second event or log.

For caregiver dose actions, the active link must have `can_view=true` and
`can_confirm_doses=true`. The server records the caregiver as the dose event
actor and forces `source="caregiver_app"`; client-supplied actor or role fields
are ignored. Caregivers without the permission receive a per-item `forbidden`
result, while unrelated caregivers receive `not_found` to avoid leaking patient
existence.

`client_recorded_at` is stored for audit but is **not** used to overwrite server
state. A late-arriving confirmation of an old dose is recorded as
`confirmed_late`; it does not rewind a newer status. `server_received_at` is
always server clock time.

`expected_version` is optional. It is the last `cursor` the client saw for that
dose occurrence. If the server has a newer occurrence change, the item returns a
`version_conflict` and the current server snapshot. Omit it if the client wants
the state machine to decide, but conflicts are still possible.

### Response

The HTTP status is `200` when the batch was parsed. Individual items can fail.
Do not infer overall success from HTTP 200.

```json
{
  "batch_id": "0f2f6c1e-6f1d-4a5f-9f2b-3f1c2d3e4f50",
  "results": [
    {
      "client_event_id": "a4c4d8f8-3a9b-4e4f-8c1e-1a2b3c4d5e6f",
      "type": "dose.confirm",
      "status": "applied",
      "occurrence_id": "f13f1e1d-2d4f-4e73-a2f5-3c1e5b7a9d10",
      "event_id": "c6e6f0a0-5c1d-4a6b-8e3f-3c4d5e6f7081",
      "server": {
        "occurrence": {"occurrence_id": "...", "status": "taken"},
        "event": {
          "event_id": "...",
          "occurrence_id": "...",
          "event_type": "confirmed_late",
          "payload": {
            "confirmed_after_cancellation": false,
            "recorded_against_superseded": false
          }
        }
      }
    },
    {
      "client_event_id": "b5d5e9f9-4b0c-4f5a-9d2e-2b3c4d5e6f70",
      "type": "water.intake.create",
      "status": "duplicate",
      "water_intake_id": "d7f7a1b1-6d2e-4b7c-9f4a-4d5e6f708192",
      "server": {"water_intake": {"water_intake_id": "...", "amount_ml": 250}}
    }
  ],
  "counts": {
    "applied": 1,
    "duplicate": 1,
    "conflict": 0,
    "error": 0
  }
}
```

### Item statuses

| Status | Meaning | Client action |
| --- | --- | --- |
| `applied` | New server state committed | Mark local item synced; update local state from `server` |
| `duplicate` | Idempotency key already applied | Mark local item synced; use returned ids/server state |
| `conflict` | Server state does not permit this action, or version changed | Do not retry blindly; show/resolve using `code` and `server` |
| `not_found` | Record does not exist or is not visible to this user | Remove/quarantine local item; do not retry |
| `forbidden` | Authenticated but not allowed to perform this action | Do not retry; re-authenticate/check role |
| `error` | Validation or internal item failure | Retry only transient/internal errors with backoff |

Conflict codes currently include:

- `state_conflict`: e.g. skipping an already taken dose.
- `version_conflict`: optional `expected_version` no longer matches.
- `client_event_id_reused`: the UUID was already used for a different record.
- `validation_error`: item-level validation failed.

## Retry and interruption rules

1. Persist queued items locally with their `client_event_id`.
2. Send items in a batch. Successful and failed items are reported individually.
3. Mark only `applied` and `duplicate` items as synced.
4. Keep `conflict`, `not_found`, `forbidden`, and validation errors in a
   quarantine/manual-resolution state. Do not resend them forever.
5. For `error` with `code="internal_error"`, retry the item with exponential
   backoff and jitter.
6. Retrying an entire batch after a network interruption is safe because
   `client_event_id` is idempotent.
7. After pushing, download from the last known cursor. The server response is the
   authoritative state, including any concurrent changes made by another device.

## Permissions and privacy

- A patient can read and push only their own records.
- A caregiver can read a linked patient's changes only while the link is active
  and `can_view=true`.
- A caregiver can push dose confirm/skip/snooze only while the link is active,
  `can_view=true`, and `can_confirm_doses=true`. Caregivers cannot push water
  actions through this contract.
- Revocation is checked on every request; an existing JWT does not preserve
  access after the link is revoked.
- A `not_found` response is used instead of revealing whether another patient's
  record exists.
- Do not log raw access tokens, FCM tokens, or full medical payloads.

## Limits and validation

- `limit`: 1–200; default 50.
- Push batch: 1–100 items; empty batches are rejected.
- `client_event_id`: UUID.
- `amount_ml`: 1–5000.
- Snooze `minutes`: 1 to `DOSE_SNOOZE_MAX_MINUTES` (default 1440).
- `client_recorded_at` may not be more than
  `SYNC_MAX_CLIENT_CLOCK_SKEW_SECONDS` (default 300) in the future.
- Medication and schedule edits are not accepted as offline push items in this
  contract. They must be performed through the regular authenticated endpoints.

## Flutter implementation checklist

- Generate a UUID v4 for every queued action; persist it before sending.
- Store server `next_cursor` transactionally with applied changes.
- Never use local wall-clock time as a cursor.
- Treat `operation="delete"` as a tombstone for entities that use it. Dose
  cancellation is an `upsert` with `status="cancelled"`, not a tombstone.
- Keep occurrence and event IDs separate.
- Apply changes in cursor order.
- Resolve conflicts using the server snapshot rather than retrying the same
  overwrite.
- Use `expected_version` when editing a record whose version matters.
- Use HTTPS in every non-local environment.
