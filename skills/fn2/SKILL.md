---
name: fn2
description: >
  Start, monitor, and schedule FN2 AI autonomous research agents for public
  markets from your terminal assistant. Use when asked a markets research
  question ("what did NVIDIA say about data-center demand on the last earnings
  call?", "how is NVDA trading today?", "what changed in TSLA's latest 10-Q?"),
  asked for a standing watch or alert ("notify me when AAPL drops more than
  5%"), asked to launch or run an FN2 AI agent, to check what your agents are
  doing or their latest results, to schedule an agent on a cadence ("before the
  next market open", "every weekday at 8am", "hourly"), to
  pause/resume/reschedule/delete an agent, or to connect an FN2 AI account.
  Covers earnings-call transcripts, price action, SEC filings, FRED macro
  series, and prediction markets. Talks to the public FN2 AI HTTP API with a
  scoped, revocable device credential; no admin access required.
license: MIT
allowed-tools: Bash
metadata:
  homepage: https://fn2.ai
  hermes:
    tags: [fn2, agents, markets, scheduling, automation]
    category: integrations
    requires_toolsets: [terminal]
---

# FN2 AI research agents, from your assistant

This skill drives the **public fn2.ai API** so you can start, watch, and
schedule FN2 AI research agents without leaving Claude, Codex, or Pi. It is a
single, dependency-free Python 3 helper: standard library only, no `pip
install`, no build step.

## First run: connect an account (no secret copying)

Resolve the helper as described in **Locating the helper**, then run:

```bash
python3 "$FN2" auth login
# → Open https://fn2.ai/start
# → Enter code XXXX-XXXX
```

That's the whole flow: the browser opens `https://fn2.ai/start`, the user signs
in (or signs up) and types the short code shown in the terminal, clicks
**Approve**, and the CLI receives a scoped, revocable device credential. The
credential is stored in the macOS Keychain when available, otherwise in
`~/.config/fn2/credentials.json` with `0600` permissions. No key is ever
pasted, printed, or sent to chat.

- Interrupted? `fn2 auth login` resumes the same code until it expires
  (15 minutes), then starts a fresh one.
- Check the connection any time: `fn2 auth status`. See what it can do:
  `fn2 permissions`. Diagnose problems: `fn2 doctor`.
- Disconnect: `fn2 auth logout` (add `--revoke` to also kill the credential on
  fn2). Credentials can also be revoked in the FN2 AI web app under
  **Preferences → Developer → Connected Devices**; revocation takes effect
  within a few minutes everywhere.

## Locating the helper

The bundled helper lives at `<skill-dir>/scripts/fn2`. There is **no `fn2` on
`PATH`**; always invoke it as `python3 "$FN2"`. Resolve `<skill-dir>` from the
path of this loaded `SKILL.md`; do not assume the current working directory.
Claude Code expands `${CLAUDE_SKILL_DIR}` to this directory. The fallbacks
cover a marketplace plugin install (whose directory carries the version, so it
moves on every update) and standalone installs:

```bash
FN2_SKILL_DIR="${CLAUDE_SKILL_DIR:-}"
for d in "$FN2_SKILL_DIR" \
         $(ls -td "$HOME"/.claude/plugins/cache/*/*/*/skills/fn2 \
                  "${CODEX_HOME:-$HOME/.codex}"/plugins/cache/*/*/*/skills/fn2 \
                  2>/dev/null) \
         "$HOME/.claude/skills/fn2" \
         "${CODEX_HOME:-$HOME/.codex}/skills/fn2" "$HOME/.agents/skills/fn2" \
         "${HERMES_HOME:-$HOME/.hermes}/skills/fn2" "$(pwd)"; do
  [ -f "$d/scripts/fn2" ] && FN2="$d/scripts/fn2" && break
done
test -n "${FN2:-}" || { echo "fn2 helper not found" >&2; exit 1; }
python3 "$FN2" --help
```

`ls -td` puts the most recently installed copy first, so an upgraded plugin
wins over a stale cached version.

## Command cheatsheet

```bash
python3 "$FN2" start "Summarize overnight moves in NVDA and peers"        # run once, now
python3 "$FN2" start "Pre-market brief on my watchlist" \
    --when "before market open"                                          # 30 min before each open (trading days only)
python3 "$FN2" start "Daily macro digest" --when "weekdays at 7am" --tz America/New_York
python3 "$FN2" start "One-time earnings recap" --when "before next market open"  # single future run
python3 "$FN2" start "EOD watchlist recap" --when "market close" --email  # + email each result to your account

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

python3 "$FN2" auth status                # credential health + storage backend
python3 "$FN2" permissions                # what the credential can / cannot do
python3 "$FN2" doctor                     # local diagnostics
python3 "$FN2" auth logout --revoke       # disconnect + revoke on FN2 AI
```

Add `--json` to any command for machine-readable output.

## Reading results

Results are available via `fn2 result <agent_id> <run_id>` and in the fn2 web
app. Add `--email` to `start` to also deliver each completed run to your
account's **own verified email**: the server resolves the address and honors
your opt-out; the skill never sends a recipient. Broader delivery options (extra
channels, per-condition rules) live in the web app.

## Scheduling vocabulary

`--when` understands: `daily`, `weekdays`, `hourly`, `before market open`,
`market close`, `weekdays at 8:30am`, `daily 16:00`, `in 2 hours`, `tomorrow at
9am`, an ISO time like `2026-07-22T13:00`, or a raw `cron:0 9 * * 1-5`. Market
phrases resolve against the **exchange calendar server-side** (`America/New_York`),
so a run **skips holidays and half-days** and lands 30 min before the open / 5 min
after the close. See [references/scheduling.md](references/scheduling.md).

## Advanced / CI: headless credential

For CI or containers where a browser flow is impossible, set the environment
variable **`FN2_API_TOKEN`** (accepts a device token `fn2d_…` or an API key
`fn2_…`). It is the only headless override; `FN2_API_KEY` remains as a legacy
alias. There is no `.env` support.

A manual API key still works as a fallback: create one in the FN2 AI web app
(**Preferences → Developer**, needs the `agents` scope) and run
`fn2 login --token fn2_…`. Prefer `fn2 auth login` everywhere else.

## Safety

- Never paste a credential into chat, argv, or a commit. All output, including
  `--json` and error text, shows only a masked `fn2d_…wxyz` form.
- The API base is pinned to `https://fn2.ai` / `*.fn2.ai`; the credential is
  never sent anywhere else.
- `delete` is irreversible (removes the agent and its history). Confirm the
  agent id with `status` first; pass `--yes` only when the user is explicit.
- Prefer read-only verbs (`agents`, `status`, `runs`, `result`) before creating
  or destroying anything.

## References

- [references/api.md](references/api.md): the endpoint contract this skill maps to.
- [references/scheduling.md](references/scheduling.md): cadence phrases and calendar caveats.
- [references/troubleshooting.md](references/troubleshooting.md): auth, storage, quota, and network errors.
