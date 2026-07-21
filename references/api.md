# fn2 public API — the contract this skill maps to

Base URL: `https://fn2.ai` (the CLI pins the origin to `https://fn2.ai` /
`*.fn2.ai`; `FN2_BASE_URL` overrides within that pin). All routes below are
under `/api/v1`. Authenticate with a bearer credential:

- a **device token** (`fn2d_…`) issued by the device-authorization flow below
  — the default, obtained via `fn2 auth login`; scoped, 90-day expiry,
  revocable per device; or
- a personal **API key** (`fn2_…`) created in the fn2 web app
  (Preferences → Developer) — the advanced/CI fallback.

Either is sent as `Authorization: Bearer …` and needs the **`agents`** scope
for agent routes and **`models`** for the model list.

## Device authorization (how `fn2 auth login` connects)

An RFC 8628-shaped flow: the CLI shows a short code, the user approves it in
the browser at `https://fn2.ai/start`, and the CLI polls until it receives the
credential. These routes are unauthenticated (except `logout`) and return
`Cache-Control: no-store`. Errors use `{"error": "<code>", "message": "…"}`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/skill/device-auth/start` | open a request → `device_code`, `user_code`, `verification_uri`, `interval`, `expires_in` |
| `POST` | `/skill/device-auth/poll` | poll with `{"device_code": …}` |
| `POST` | `/skill/device-auth/logout` | self-revoke the device token in `Authorization` |

### `start` body

```json
{
  "client": "fn2-skill",
  "client_version": "0.2.0",
  "harness": "claude",
  "os": "macos",
  "scopes": ["agents", "models"]
}
```

`client` must be `fn2-skill`; `harness` is one of
`claude|codex|pi|openclaw|hermes|other`, `os` one of
`macos|linux|windows|other`; `scopes` must be a non-empty subset of
`{agents, models}`. `201` returns the codes; the request lives 15 minutes.

### `poll` statuses (always `200` unless malformed)

| `status` | Meaning |
|---|---|
| `authorization_pending` | keep polling at `interval` seconds |
| `slow_down` | polled too fast — the response carries the new, larger `interval` |
| `approved` | one-time payload: `access_token` (`fn2d_…`), `token_type`, `scopes`, `device_id`, `expires_at`, `account.email_masked` |
| `denied` | the user clicked Deny |
| `expired` | the request aged out, was already redeemed, or the code is unknown |

The `approved` payload is released exactly once; any later poll returns
`expired`. Unknown device codes are indistinguishable from expired ones.

### `logout`

`POST /skill/device-auth/logout` with the device token as the bearer revokes
that device. A `401` means the credential was already revoked or expired — the
CLI treats that as success. Devices can also be revoked in the web app under
**Preferences → Developer → Connected Devices** (per-device or revoke-all);
revocation takes effect within a few minutes everywhere.

Device credentials expire after 90 days; renewal is simply `fn2 auth login`
again. Accounts are capped at 10 active devices.

## Agents

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/agents` | create an agent |
| `GET` | `/agents` | list agents (`?status=&limit=&offset=`) |
| `GET` | `/agents/{id}` | one agent's settings |
| `PATCH` | `/agents/{id}` | update name/prompt/model/labels/schedule/status |
| `DELETE` | `/agents/{id}` | delete agent + history (`204`) |

### Create body

```json
{
  "prompt": "Summarize overnight moves in NVDA and peers",
  "name": "NVDA overnight",
  "model": "anthropic/claude-3.5-sonnet",
  "labels": ["watchlist"],
  "schedule": {
    "frequency": "custom",
    "cron": "0 9 * * 1-5",
    "timezone": "America/New_York"
  }
}
```

- **No `schedule`** → the agent runs once, immediately.
- **`schedule.run_at`** (ISO 8601) → a single future run.
- **`schedule.frequency`** (`daily` / `weekdays` / `hourly` / `custom`) →
  recurring. `custom` requires `cron`. `timezone` is IANA (default `UTC`).
  Optional `ends_at` (`YYYY-MM-DD`) stops the recurrence.

Pre-flight quota is enforced: creating (or running) an agent returns `429` if
the account is over its token budget.

## Runs

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/agents/{id}/run` | trigger now → `202 {run_id, status}` |
| `GET` | `/agents/{id}/runs` | run history (`?limit=&offset=`) |
| `GET` | `/agents/{id}/runs/{run_id}` | one run's outcome |

A run object:

```json
{
  "run_id": "…", "agent_id": "…",
  "status": "pending|running|completed|failed|cancelled",
  "started_at": "…", "completed_at": "…", "duration_seconds": 12.3,
  "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
  "error": {"code": "quota|timeout|upstream|…", "message": "…"},
  "model": "…",
  "result": {"text": "the agent's final answer"}
}
```

## Account

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/usage` | plan, token quota/usage, credential metadata (includes a `device` block when authenticated with a device token) |
| `GET` | `/models` | models enabled for the account |

## Reading results

Run results are available through `GET /agents/{id}/runs/{run_id}`
(`fn2 result`) and in the fn2 web app. Email delivery is configured in the web
app — it is not part of this API surface, and the skill does not send mail.
