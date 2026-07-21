---
name: fn2
description: >
  Start, monitor, and schedule fn2.ai autonomous research agents for public
  markets from your terminal assistant. Use when asked to launch or run an fn2
  agent, check what your agents are doing or their latest results, schedule an
  agent to run on a cadence ("run this before the next market open and email
  me", "every weekday at 8am", "hourly"), pause/resume/reschedule/delete an
  agent, or connect an fn2 account. Talks to the public fn2 HTTP API with a
  personal API key; no admin access required.
version: 0.1.0
license: MIT
platforms: [macos, linux]
allowed-tools: Bash
metadata:
  homepage: https://fn2.ai
  hermes:
    tags: [fn2, agents, markets, scheduling, automation]
    category: integrations
    requires_toolsets: [terminal]
---

# fn2 — research agents from your assistant

This skill drives the **public fn2.ai API** so you can start, watch, and
schedule fn2 research agents without leaving Claude, Codex, or Pi. It is a
single, dependency-free Python 3 helper — standard library only, no `pip
install`, no build step.

## First run — connect an account

The user needs an fn2 account and a personal API key (a `fn2_…` string). Kick
off onboarding; it prints a personalized sign-up link and stores the key with
`0600` permissions once pasted back.

```bash
FN2="$(dirname "$0")"        # resolve the skill dir; see "Locating the helper"
python3 "$FN2/scripts/fn2" login --email "user@example.com"
# → open the link, sign up (email-confirmed), create a key with the 'agents' scope
python3 "$FN2/scripts/fn2" login --token fn2_xxxxxxxxxxxxxxxxxxxx
python3 "$FN2/scripts/fn2" whoami          # confirm plan + quota
```

Never paste a key into chat or commit it. The key is read (in order) from
`FN2_API_KEY`, a local `.env`, then `~/.config/fn2/credentials.json`.

## Locating the helper

The bundled helper lives at `<skill-dir>/scripts/fn2`. Resolve the skill dir
for whichever harness is running:

```bash
for d in "$HOME/.claude/skills/fn2" "${CODEX_HOME:-$HOME/.codex}/skills/fn2" \
         "${HERMES_HOME:-$HOME/.hermes}/skills/fn2" "$(pwd)"; do
  [ -f "$d/scripts/fn2" ] && FN2="$d/scripts/fn2" && break
done
python3 "$FN2" --help
```

## Command cheatsheet

```bash
python3 "$FN2" start "Summarize overnight moves in NVDA and peers"        # run once, now
python3 "$FN2" start "Pre-market brief on my watchlist" \
    --when "before market open"                                          # every weekday 09:00 ET
python3 "$FN2" start "Daily macro digest" --when "weekdays at 7am" --tz America/New_York
python3 "$FN2" start "One-time earnings recap" --when "before next market open"  # single future run

python3 "$FN2" agents                     # list your agents
python3 "$FN2" status                     # same overview
python3 "$FN2" status <agent_id>          # detail + recent runs
python3 "$FN2" run <agent_id>             # trigger now
python3 "$FN2" runs <agent_id>            # run history
python3 "$FN2" result <agent_id> <run_id> # one run's output

python3 "$FN2" pause <agent_id>
python3 "$FN2" resume <agent_id>
python3 "$FN2" schedule <agent_id> "hourly"
python3 "$FN2" delete <agent_id>
```

Add `--json` to any command for machine-readable output.

## "…and email me"

fn2 emails an agent's findings to the account email after each run — that is the
platform default, so scheduling the cadence is all this skill needs to do. To
satisfy "run this before the next market open and email me", schedule the agent
(`--when "before market open"` for a recurring brief, or `--when "before next
market open"` for a single run) and the email is delivered automatically.

## Scheduling vocabulary

`--when` understands: `daily`, `weekdays`, `hourly`, `before market open`,
`market close`, `weekdays at 8:30am`, `daily 16:00`, `in 2 hours`, `tomorrow at
9am`, an ISO time like `2026-07-22T13:00`, or a raw `cron:0 9 * * 1-5`. Market
phrases assume the US equities session and default to `America/New_York`; they
do **not** skip market holidays. See [references/scheduling.md](references/scheduling.md).

## Safety

- Treat the `fn2_…` key as a secret: never echo it, never commit it, never send
  it to chat. `whoami` and all output show only a masked form.
- `delete` is irreversible (removes the agent and its history). Confirm the
  agent id with `status` first; pass `--yes` only when the user is explicit.
- Prefer read-only verbs (`agents`, `status`, `runs`, `result`) before creating
  or destroying anything.

## References

- [references/api.md](references/api.md) — the endpoint contract this skill maps to.
- [references/scheduling.md](references/scheduling.md) — cadence phrases and calendar caveats.
- [references/troubleshooting.md](references/troubleshooting.md) — auth, quota, and network errors.
