# FN2 AI public API: the contract this skill maps to

Base URL: `https://fn2.ai` (the CLI pins the origin to `https://fn2.ai` /
`*.fn2.ai`; `FN2_BASE_URL` overrides within that pin). All routes below are
under `/api/v1`. Authenticate with a bearer credential:

- a **device token** (`fn2d_…`) issued by the device-authorization flow below
  (the default, obtained via `fn2 auth login`; scoped, 90-day expiry,
  revocable per device; or
- a personal **API key** (`fn2_…`) created in the FN2 AI web app
  (Preferences → Developer): the advanced/CI fallback.

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
  "client_version": "0.2.1",
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
| `slow_down` | polled too fast; the response carries the new, larger `interval` |
| `approved` | one-time payload: `access_token` (`fn2d_…`), `token_type`, `scopes`, `device_id`, `expires_at`, `account.email_masked` |
| `denied` | the user clicked Deny |
| `expired` | the request aged out, was already redeemed, or the code is unknown |

The `approved` payload is released exactly once; any later poll returns
`expired`. Unknown device codes are indistinguishable from expired ones.

### `logout`

`POST /skill/device-auth/logout` with the device token as the bearer revokes
that device. A `401` means the credential was already revoked or expired, and the
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
  "delivery": {"email": true},
  "schedule": {
    "frequency": "market_open",
    "offset_minutes": -30,
    "timezone": "America/New_York"
  }
}
```

- **No `schedule`** → the agent runs once, immediately.
- **`schedule.run_at`** (ISO 8601) → a single future run at an absolute time.
- **`schedule.frequency`** (`daily` / `weekdays` / `hourly` / `weekly` /
  `custom` / `market_open` / `market_close`) → recurring. `custom` requires
  `cron`. `timezone` is IANA (default `UTC`, else the account's saved tz).
  Optional `ends_at` (`YYYY-MM-DD`) stops the recurrence.
- **Market schedules** (`market_open` / `market_close`, or one-shot
  `market_event: "open" | "close"`) take a signed `offset_minutes` (e.g. `-30`
  = 30 min before). The **server** resolves the XNYS calendar (holidays, early
  closes, DST). The client never computes a market date. An invalid/unresolvable
  market request returns `400 {"code": "market_calendar"}`.
- **`delivery: {email: true}`** attaches on-complete email to the account's
  **own verified address** (opt-out honored). An arbitrary recipient is never
  accepted. Omit it to leave delivery off.

Policy parity: creation enforces the same plan/cadence, recurring-agent-count,
and model-tier limits as the web app (`403` on violation), and pre-flight token
quota (`429`). A per-key `allowed_models` restriction is enforced (`403
{"code": "model_not_allowed"}`).

## Reliability (optional, additive)

- **Idempotency.** Send `Idempotency-Key: <opaque>` on `POST /agents` or `POST
  /agents/{id}/run`; a retry with the same key + same body replays the first
  response (one resource). Same key + different body → `409
  {"code":"idempotency_key_reused"}`; still in flight → `409
  {"code":"idempotency_in_progress"}` with `retry_after`.
- **Wait.** `GET /agents/{id}/runs/{run_id}?wait=<0-25>` long-polls until the run
  is terminal or the deadline passes (then `200` with the current state).
- **Delivery state.** `?include=delivery` adds a read-only `delivery` block,
  separate from `status`.
- **Cursor pagination.** `GET /agents/{id}/runs?cursor=<opaque>` (from
  `next_cursor`); `limit`/`offset` still work.
- **Errors** are a superset of `{error, code}`, also `request_id` (echoed as
  `X-Request-Id`), `retryable`, `retry_after`, and a `type` doc URL.

## Runs

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/agents/{id}/run` | trigger now → `202 {run_id, status}` |
| `GET` | `/agents/{id}/runs` | run history (`?limit=&offset=` or `?cursor=`, optional `?wait=`) |
| `GET` | `/agents/{id}/runs/{run_id}` | one run's outcome (optional `?wait=`, `?include=delivery`) |

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
| `GET` | `/usage` | plan, token quota/usage, the weekly `research_requests` allowance, credential metadata (includes a `device` block when authenticated with a device token) |
| `GET` | `/models` | models enabled for the account |

## Reading results

Run results are available through `GET /agents/{id}/runs/{run_id}`
(`fn2 result`) and in the FN2 AI web app. Email delivery is opt-in per agent via
`delivery: {email: true}` on create, mapped to the account's own verified email
(the server resolves the address and honors opt-out; no recipient is ever sent
by the client). Additional delivery channels/rules are configured in the web app.

## MCP connector: the same API, from an MCP client

FN2 AI also speaks MCP. Paste `https://mcp.fn2.ai/mcp` into an MCP client's "add a
custom connector" dialog (Claude, Cursor, MCP Inspector) and it runs an OAuth 2.1
authorization-code + PKCE flow: the client registers itself, the user approves the
grant in the browser at `https://fn2.ai/authorize`, and the client receives a
scoped access token (`fn2m_…`).

**It is this contract, not a second one.** Each tool is one row mapping to a route
above, dispatched through the same `/api/v1` endpoints with the same scopes, plan
and cadence limits, model entitlement, quota pre-flight, `Idempotency-Key` replay,
cursor pagination, and error envelope. The skill and the connector are two front
doors onto one API.

| Tool | Route | Scope |
|---|---|---|
| `list_agents` / `get_agent` | `GET /agents`, `GET /agents/{id}` | `agents` |
| `start_agent` / `update_agent` | `POST /agents`, `PATCH /agents/{id}` | `agents` |
| `pause_agent` / `resume_agent` | `PATCH /agents/{id}` with `status` | `agents` |
| `delete_agent` | `DELETE /agents/{id}` (requires `confirm: true`) | `agents` |
| `run_agent` / `list_runs` / `get_run` | `POST /agents/{id}/run`, `GET /agents/{id}/runs[/{run_id}]` | `agents` |
| `get_usage` | `GET /usage` | `agents` |
| `list_models` | `GET /models` | `models` |
| `run_chat` | `POST /chat/incognito` | `chat` |
| `search_transcripts` | `GET /research/transcripts/search` | `research` |
| `recall` | `GET /research/recall` | `research` |
| `get_stock_price` | `GET /research/prices` | `research` |
| `get_fred_series` | `GET /research/fred` | `research` |
| `get_company_financials` | `GET /research/financials` | `research` |

Scopes are the same vocabulary: `agents`, `models`, `research`, and (unlike a
device token) `chat`, which `run_chat` needs. The client sees only the tools its
granted scopes can actually call. A client that requests no `scope` at all gets
`agents models research`; `chat` is opt-in.

### The research surface and its weekly allowance

The five `research` tools are read-only market data: earnings-call text, prices,
FRED series, SEC-derived financials, and the account's own saved notes. They spend
no model tokens, so they are **not** metered against the monthly token quota. They
draw on a separate **weekly request allowance** that resets Monday 00:00 UTC and
depends on the plan:

| Plan | Research requests / week |
|---|---|
| Free | 25 |
| Pro trial | 100 |
| Pro | 500 |
| Ultra | 2000 |
| Max | 5000 |

`GET /usage` reports it as `research_requests` (`used` / `limit` / `remaining` /
`resets_at`) beside the token block, so a client can show what is left before a
call fails. When it runs out the tool returns `429` with
`code: "api_quota_exceeded"` and an `error` message naming the plan, the limit,
the reset date and the upgrade URL. **Relay it as written rather than retrying**;
the number does not change until the reset. A failed call does not spend the
allowance: a `404` for an unknown ticker and a `503` from an unavailable index
are both free.

**Credentials do not cross origins.** An `fn2m_` token is valid only on
`mcp.fn2.ai`; `fn2d_` device tokens and `fn2_` API keys are rejected there, and an
`fn2m_` token is rejected on `fn2.ai`. Do not put an MCP token in `FN2_API_TOKEN`
and do not point the CLI at the MCP host. Grants are revoked in the web app under
**Preferences → Developer → Connected Apps** (per-app or revoke-all).

Full protocol, security and cross-region contract: `docs/public-mcp-server.md` in
the FN2 AI server repo (stock-server).
