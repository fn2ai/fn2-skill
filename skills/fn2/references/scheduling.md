# Scheduling vocabulary and caveats

`--when` (on `start` and `schedule`) turns a phrase into an fn2 `schedule`
object. Parsing happens locally in `schedule.py`; recurring cadences are handed
to the server as `frequency`/`cron` + `timezone` (the server evaluates the
timezone), while one-off runs are resolved to an absolute UTC `run_at`.

## Recurring cadences

| Phrase | Result |
|---|---|
| `daily` | `{"frequency": "daily"}` |
| `weekdays` / `every weekday` / `business days` | `{"frequency": "weekdays"}` |
| `hourly` / `every hour` | `{"frequency": "hourly"}` |
| `before market open` / `premarket` | `frequency market_open`, `offset_minutes -30`, `America/New_York` |
| `market close` / `after close` | `frequency market_close`, `offset_minutes 5`, `America/New_York` |
| `weekdays at 8:30am` | `cron 30 8 * * 1-5` |
| `daily 16:00` / `at 9am` | `cron … * * *` (daily) |
| `cron:0 9 * * 1-5` | that cron, verbatim (5 fields required) |

Pass `--tz America/New_York` (any IANA name) to set the timezone for a cadence.
Market phrases already default to `America/New_York`.

## One-off runs

A phrase containing `next`, `today`, `tomorrow`, `in N …`, or an ISO date is
treated as a single future run (`run_at`):

| Phrase | Result |
|---|---|
| `before next market open` | `market_event open`, `offset_minutes -30`, once (server resolves the next session) |
| `in 2 hours` / `in 45 minutes` / `in 1 day` | relative to now |
| `tomorrow at 9am` / `today at 4pm` | that local time (UTC unless `--tz`) |
| `2026-07-22T13:00` / `2026-07-22 13:00` / `2026-07-22` | explicit datetime |

## Caveats

- **Market calendar (server-owned).** "market open"/"close" resolve against the
  exchange calendar **on the server** (XNYS): holidays and early-close days are
  honored, so a run does not fire on a closed day, and DST is handled correctly.
  The client sends only the phase (`market_open`/`market_close` or a one-shot
  `market_event`) and a signed `offset_minutes`; it never computes a market date.
- **"Before the open" = `offset_minutes -30`**, 30 minutes ahead of the 09:30
  bell, so a brief is ready (via `fn2 result` and the FN2 AI web app) before trading
  starts. "After the close" = `offset_minutes 5`.
- **Timezone maths for one-off runs** needs Python's `zoneinfo` (standard since
  3.9). On the rare build without it, use a recurring cadence (server-side
  timezone) or an absolute UTC time instead.
- **DST** is handled correctly for recurring cron (the server evaluates the
  IANA zone) and for one-off runs (resolved through `zoneinfo`).
