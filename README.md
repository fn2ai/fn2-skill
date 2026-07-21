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
you › schedule a pre-market brief on my watchlist before the open, and email me
  ↳ ✓ agent created — a1b2c3d4
     cadence: every weekday at 09:00 America/New_York (before the open)
     results are emailed to your fn2 account after each run.
```

## Get started

> [!NOTE]
> You need an fn2 account and a personal API key (a `fn2_…` string). The steps
> below create one; the key is stored locally with `0600` permissions and never
> printed in full.

### 1. Install into your harness

**Claude Code / Pi** — copy or symlink the skill folder:

```bash
git clone https://github.com/fn2ai/fn2-skill ~/.fn2-skill
ln -s ~/.fn2-skill ~/.claude/skills/fn2          # Claude Code
ln -s ~/.fn2-skill "${HERMES_HOME:-$HOME/.hermes}/skills/fn2"   # Pi
```

**Codex** — it ships a `.codex-plugin/plugin.json`, so install as a plugin:

```bash
git clone https://github.com/fn2ai/fn2-skill "${CODEX_HOME:-$HOME/.codex}/plugins/fn2"
```

Or just run `make install` from the repo to link it into whichever harnesses it
finds.

### 2. Connect your account

```bash
python3 scripts/fn2 login --email you@example.com
```

This prints a personalized sign-up link. Open it, confirm your email, create an
API key with the **`agents`** scope, then paste it back:

```bash
python3 scripts/fn2 login --token fn2_xxxxxxxxxxxxxxxxxxxx
python3 scripts/fn2 whoami          # confirms plan + quota
```

### 3. Ask your assistant

Once installed, you talk to it in natural language and it calls the skill:

> *"start an agent that tracks unusual options flow in my watchlist hourly"*
> *"what did my agents find today?"*
> *"pause the macro digest until Monday"*

## Commands

| Command | Does |
|---|---|
| `login` / `logout` / `whoami` | connect, disconnect, show plan + quota |
| `models` | list models available to your account |
| `start "<prompt>" [--when …]` | create an agent — runs now, or on a schedule |
| `agents` (`ls`) | list your agents |
| `status [<id>]` | overview, or one agent's detail + recent runs |
| `run <id>` | trigger an agent immediately |
| `runs <id>` / `result <id> <run_id>` | run history / one run's output |
| `pause` / `resume` / `schedule <id> "<cadence>"` | manage the cadence |
| `delete <id>` | remove an agent and its history |

Every command accepts `--json` for scripting.

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

Market phrases default to `America/New_York` and **do not** skip market
holidays — see [references/scheduling.md](references/scheduling.md).

## Security & configuration

The API key is resolved in this order — the first hit wins:

1. `FN2_API_KEY` environment variable
2. a `.env` file in the working directory (see [`.env.example`](.env.example))
3. `~/.config/fn2/credentials.json` (written `0600` by `fn2 login`)

Other knobs: `FN2_BASE_URL` (default `https://fn2.ai`), `FN2_CONFIG_HOME`,
`FN2_DOTENV`. The recommended, most secure setup is `fn2 login` — the `.env`
option exists for CI and container convenience.

The skill never echoes your key; `whoami` and all output show a masked
`fn2_…wxyz` form only.

## How it works

```
scripts/fn2            → entry point (adds scripts/ to sys.path, calls the CLI)
scripts/fn2cli/
  config.py            → credential + endpoint resolution
  client.py            → urllib HTTP layer + typed errors
  api.py               → one function per fn2 endpoint
  schedule.py          → "before market open" → fn2 schedule object
  render.py            → human / JSON output
  cli.py               → argument parsing + dispatch
```

It talks only to the documented public API (`/api/v1/agents`, `/runs`, `/usage`,
`/models`) with your key — no admin access, no scraping. See
[references/api.md](references/api.md).

## Development

```bash
make test        # unittest, no network
make lint        # byte-compile every module
make install     # link into detected harnesses
```

## License

MIT — see [LICENSE](LICENSE).
