<div align="center">

# fn2 skill

**Start, watch, and schedule [fn2.ai](https://fn2.ai) research agents — right from your terminal assistant.**

![license](https://img.shields.io/badge/license-MIT-0B5FFF?style=flat-square)
![python](https://img.shields.io/badge/python-3.9%2B-0B5FFF?style=flat-square)
![deps](https://img.shields.io/badge/dependencies-none-0B5FFF?style=flat-square)
![harnesses](https://img.shields.io/badge/works%20in-Claude%20%C2%B7%20Codex%20%C2%B7%20Pi-0B5FFF?style=flat-square)

</div>

fn2 runs autonomous research agents on public markets. This skill lets your
assistant — **Claude Code, OpenAI Codex, or Pi** — launch those agents, check
what they found, and put them on a schedule like *"brief me before the next
market open."* It is one dependency-free Python 3 file tree: **no `pip install`,
no build step, standard library only.**

```text
you › schedule a pre-market brief on my watchlist before the open
  ↳ ✓ agent created — a1b2c3d4
     cadence: every weekday at 09:00 America/New_York (before the open)
     results:   fn2 result a1b2c3d4 <run_id> — also in the fn2 web app,
                where email delivery can be configured.
```

## Get started

### 1. Install into your harness

**Claude Code** — add the repository marketplace, then install the plugin:

```bash
claude plugin marketplace add fn2ai/fn2-skill
claude plugin install fn2@fn2
```

**Codex** — use the same repository as a Codex marketplace:

```bash
codex plugin marketplace add fn2ai/fn2-skill
codex plugin add fn2@fn2
```

**Pi**, or local development in any harness — clone the repository and link the
canonical skill directory:

```bash
git clone https://github.com/fn2ai/fn2-skill ~/.fn2-skill
ln -s ~/.fn2-skill/skills/fn2 "${HERMES_HOME:-$HOME/.hermes}/skills/fn2"
```

Run `make install` from a checkout to link the canonical skill into Claude,
Codex, and Pi at once.

### 2. Connect your account — no secret copying

```bash
python3 skills/fn2/scripts/fn2 auth login
```

The terminal prints a short code and opens `https://fn2.ai/start`. Sign in (or
sign up), type the code, click **Approve** — done. The CLI receives a scoped,
revocable device credential and stores it in the macOS Keychain (or an
owner-only file on Linux). You never see or copy a secret.

```bash
python3 skills/fn2/scripts/fn2 whoami          # confirms plan + quota
python3 skills/fn2/scripts/fn2 auth status     # credential health + where it's stored
```

### 3. Ask your assistant

Once installed, you talk to it in natural language and it calls the skill:

> *"start an agent that tracks unusual options flow in my watchlist hourly"*
> *"what did my agents find today?"*
> *"pause the macro digest until Monday"*

## Commands

| Command | Does |
|---|---|
| `auth login [--no-browser]` | connect via the browser device flow (code at fn2.ai/start) |
| `auth status` | storage backend, masked credential, scopes, expiry, live check |
| `auth logout [--revoke]` | disconnect (optionally revoke the credential on fn2 first) |
| `permissions` | what the credential can and cannot do |
| `doctor` | diagnose config, storage, and connectivity |
| `login --token` / `whoami` | manual API-key fallback / show plan + quota |
| `models` | list models available to your account |
| `start "<prompt>" [--when …]` | create an agent — runs now, or on a schedule |
| `agents` (`ls`) | list your agents |
| `status [<id>]` | overview, or one agent's detail + recent runs |
| `run <id>` | trigger an agent immediately |
| `runs <id>` / `result <id> <run_id>` | run history / one run's output |
| `pause` / `resume` / `schedule <id> "<cadence>"` | manage the cadence |
| `delete <id>` | remove an agent and its history |

Every command accepts `--json` for scripting. Run results are available via
`fn2 result` and in the fn2 web app; email delivery is configured in the web
app.

## Scheduling in plain English

`--when` accepts everyday phrasing:

```text
before market open      every weekday 09:00 ET (30 min before the bell)
market close            every weekday 16:05 ET
weekdays at 8:30am      cron under the hood, your timezone
daily / hourly          named cadences
before next market open a single run at the next open
in 2 hours / tomorrow at 9am / 2026-07-22T13:00    one-off runs
cron:0 9 * * 1-5        raw cron for full control
```

Market phrases default to `America/New_York` and are resolved against the
exchange calendar server-side, so they skip holidays and respect half-days — see
[skills/fn2/references/scheduling.md](skills/fn2/references/scheduling.md).

## Security & configuration

The credential is resolved in this order — the first hit wins:

1. `FN2_API_TOKEN` environment variable (canonical headless override;
   accepts `fn2d_…` device tokens and `fn2_…` API keys)
2. `FN2_API_KEY` environment variable (legacy alias)
3. macOS Keychain (service `fn2-skill`; used automatically on macOS)
4. `~/.config/fn2/credentials.json` (written `0600`, directory `0700`)

There is **no `.env` support** — a working-directory file can never inject a
credential. Other knobs: `FN2_BASE_URL` (default `https://fn2.ai`),
`FN2_CONFIG_HOME`.

Hard safety rails:

- **Origin pinning** — the API base must be `https://` on `fn2.ai` or
  `*.fn2.ai`; the credential is never sent anywhere else
  (`FN2_ALLOW_DEV_BASE=1` exists for local development only and warns loudly).
- **Redaction** — the credential appears only as a masked `fn2d_…wxyz` form in
  all output, including `--json` and error text.
- **Revocation** — revoke any connected device in the fn2 web app under
  **Preferences → Developer → Connected Devices** (or `fn2 auth logout
  --revoke`); it takes effect within a few minutes everywhere.

## How it works

```
skills/fn2/scripts/fn2            → entry point (adds scripts/ to sys.path, calls the CLI)
skills/fn2/scripts/fn2cli/
  config.py            → credential + endpoint resolution, origin pinning, redaction
  storage.py           → macOS Keychain / owner-only file + pending-login state
  deviceauth.py        → the fn2.ai/start device-authorization flow
  client.py            → urllib HTTP layer + typed errors
  api.py               → one function per fn2 endpoint
  schedule.py          → "before market open" → fn2 schedule object
  render.py            → human / JSON output
  cli.py               → argument parsing + dispatch
```

It talks only to the documented public API (`/api/v1/agents`, `/runs`, `/usage`,
`/models`, `/skill/device-auth/*`) with your scoped credential — no admin
access, no scraping. See [skills/fn2/references/api.md](skills/fn2/references/api.md).

## Development

```bash
make test        # unittest, no network
make lint        # byte-compile every module
make validate    # strict Claude plugin validation (when Claude Code is installed)
make install     # link the canonical skill into Claude, Codex, and Pi
```

## License

MIT — see [LICENSE](LICENSE).
