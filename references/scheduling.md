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
| `before market open` / `premarket` | `cron 0 9 * * 1-5`, `America/New_York` |
| `market close` / `after close` | `cron 5 16 * * 1-5`, `America/New_York` |
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
| `before next market open` | next weekday 09:00 ET, once |
| `in 2 hours` / `in 45 minutes` / `in 1 day` | relative to now |
| `tomorrow at 9am` / `today at 4pm` | that local time (UTC unless `--tz`) |
| `2026-07-22T13:00` / `2026-07-22 13:00` / `2026-07-22` | explicit datetime |

## Caveats

- **Market calendar.** "market open"/"close" assume the regular US equities
  session (09:30–16:00 ET). The skill does **not** skip market holidays or
  early-close days — a holiday-scheduled run still fires; the agent simply has
  little fresh price data. If you need an exchange calendar, drive it with an
  explicit `cron:` and manage exceptions upstream.
- **"Before the open" = 09:00 ET**, 30 minutes ahead of the 09:30 bell, so a
  brief is ready (via `fn2 result` and the fn2 web app) before trading starts.
- **Timezone maths for one-off runs** needs Python's `zoneinfo` (standard since
  3.9). On the rare build without it, use a recurring cadence (server-side
  timezone) or an absolute UTC time instead.
- **DST** is handled correctly for recurring cron (the server evaluates the
  IANA zone) and for one-off runs (resolved through `zoneinfo`).
