# fn2 public API — the contract this skill maps to

Base URL: `https://fn2.ai` (override with `FN2_BASE_URL`). All routes below are
under `/api/v1`. Authenticate with a personal API key sent as
`Authorization: Bearer fn2_…`. The key needs the **`agents`** scope for agent
routes and **`models`** for the model list.

Keys are created in the fn2 web app (Settings → API keys, or the onboarding
link). They are shown once at creation. Max 10 keys per account.

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
| `GET` | `/usage` | plan, token quota/usage, key metadata |
| `GET` | `/models` | models enabled for the account |

## Email delivery

fn2 emails an agent's findings to the account email after each run. There is no
per-agent email toggle on the public API today, so this skill does not send
mail itself — it schedules the run and the platform delivers the result. If a
future API version adds a delivery field, it belongs in the `schedule`/create
body and would surface here.
