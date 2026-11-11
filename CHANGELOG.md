# Changelog

Notable changes to the FN2 AI skill. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html) on the CLI's
user-visible surface.

## [0.8.0] - 2026-11-11

### Added

- **Direct research reads.** Eight read-only commands fetch FN2 AI's data
  without starting an agent, one request each: `earnings` (reported quarters
  against analyst consensus, report dates, the next report), `calls` and
  `transcript` (the earnings calls FN2 holds, and one call's text a page at a
  time), `search` (what executives said, across calls or inside one with
  `--call`), `financials` (SEC-filing figures, now including operating income
  and operating margin), `price`, `fred`, and `recall`. "Summarize Netflix's
  most recent earnings report and call" is now a handful of reads instead of an
  agent run. Every command takes `--json`.
- **Output written to be quoted accurately.** Exact figures (never `12.87B`),
  ISO dates, full transcript ids, and an explicit "not available" wherever FN2
  has no data. `earnings` labels consensus as analyst consensus rather than
  company guidance, never guesses a before/after-market session, marks the next
  report date as an estimate, and opens with `POSSIBLY STALE` when the newest
  result FN2 holds is old. `transcript` prints the exact `next page:` command
  above and below the text. `search` marks every hit `matched your words` or
  `matched by meaning only`, and cautions when no hit contains the query
  words, so the nearest passage is not mistaken for a quote on a topic the
  call never raised. A view too long for a terminal assistant's output limit
  says so on its first line instead of being cut silently.
- **`fn2 auth login` requests the `research` scope.** `fn2 permissions`,
  `fn2 auth status` and `fn2 whoami` show whether a credential has it, and
  `whoami` shows the weekly research allowance beside the token quota.
- `SKILL.md` teaches assistants when to read directly and when to run an
  agent, with a recipe for an earnings summary and the rules for reporting it
  honestly. `references/research.md` documents the commands, their output, and
  the data's limits.

### Changed

- **Signed in before 0.8.0? Run `fn2 auth login` once more.** Older sign-ins
  carry `agents` and `models` only, so the research commands answer
  `Missing scope: research`. The CLI now explains that and prints the commands
  to fix it, per credential type, instead of the generic "may be revoked or
  out of scope". Agents, schedules, and results are untouched.
- A used-up weekly research allowance (`api_quota_exceeded`) prints FN2's own
  sentence, with the plan, limit, reset date and upgrade link, exactly as sent,
  and says not to retry.
- `fn2 permissions` no longer lists default scopes for a manual API key whose
  scopes it cannot see; it shows the two an agent credential must have and
  says the rest is set at key creation.
- Piped output escapes characters the terminal's code page cannot encode
  instead of aborting part-way through a transcript.

## [0.7.0] - 2026-11-06

### Added

- Ship a research cookbook inside the canonical skill: earnings comparison,
  GAAP reconciliation, and a bounded watchlist pilot. The standard-library
  runner previews prompts without credentials or network, delegates opt-in
  execution to the existing CLI, and requires an end date for recurrence.
- Test all three recipes through the actual CLI/HTTP contract with offline
  fixtures, including result retrieval, schedule fields, pause, and rejection
  of invalid or unbounded inputs. No live research output is fabricated.

### Documentation

- Document the Skills CLI install route, project-local Codex path, telemetry
  opt-out, and the account and runtime requirements for first use. Verified
  with Skills CLI 1.7.6.

## [0.6.1] - 2026-11-05

### Fixed

- Pi installation now uses `~/.pi/agent/skills` and respects
  `PI_CODING_AGENT_DIR`. The CLI launcher and skill helper resolve that path;
  installations previously placed under Hermes remain discoverable.

## [0.6.0] - 2026-08-11

### Fixed

- **The browser actually opens when an assistant runs the sign-in.** Auto-open
  was gated on stdout being a terminal, but the normal caller is Claude Code or
  Codex driving the CLI through a pipe: nothing opened, and nothing said why.
  The gate is now "can this machine show a browser window": always on macOS
  and Windows, on Linux when `DISPLAY` / `WAYLAND_DISPLAY` is present, never
  over a plain SSH session. `--no-browser` still turns it off.
- **The code and URL appear immediately when output is piped.** Python
  block-buffers a piped stdout, so `auth login` run as a background task could
  sit on the sign-in code until the process exited — a user watching a task
  log saw nothing at all. All output is now line-buffered.

### Added

- **`fn2 auth login --no-wait`**: start (or resume) the sign-in, print the code
  and URL, open the browser, and return immediately instead of blocking for up
  to 15 minutes; a later `fn2 auth login` resumes the same code and finishes.
  This is the flow `SKILL.md` now teaches assistants: get the code in the
  foreground, put it in chat at once, wait for approval in the background.
- The README now leads with a **Get started** section (install → connect →
  first question) ahead of the feature tour; install variants moved to
  **Install details**. A troubleshooting entry covers "the browser never
  opened".

## [0.5.0] - 2026-08-10

### Added

- **`fn2 link`** writes an `fn2` launcher into the first writable `bin`
  directory on your `PATH`, so a plugin install can actually give you the
  command. The launcher re-resolves the skill at run time, so a plugin update
  (which moves the versioned install directory) cannot strand it. `fn2 unlink`
  removes it, and refuses to delete a file it did not write.
- **Agent references accept an id, an id prefix, or a name.** `fn2 agents`
  prints 8-character ids; those 8 characters now work everywhere an agent is
  taken. Ambiguous references are refused with the candidates listed, never
  guessed. A full id still costs no extra request.
- **`--wait`** on `start` (when it runs now) and on `run`: blocks until the run
  is terminal and prints the result, turning ask-and-read into one command. It
  uses the API's own `?wait=` long-poll rather than a client-side hammer loop,
  and honours `--timeout` (default 300s).
- **`fn2 result <agent>`** defaults to the newest run, so there is no run id to
  copy for the common case.

### Fixed

- A console that cannot encode `✓` (legacy Windows cp1252) took the whole
  command down with `UnicodeEncodeError`. Glyphs now fall back to ASCII.
- API errors carrying `retry_after` say when to try again; 5xx responses quote
  their `request_id`.
- The launcher and the documented resolution chain honour `CLAUDE_CONFIG_DIR`,
  which a relocated Claude home needs.

## [0.4.1] - 2026-08-10

### Fixed

- A marketplace plugin install was unreachable when the harness did not expand
  `${CLAUDE_SKILL_DIR}`. Plugins land in
  `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/skills/fn2`, and
  none of the fallback locations in `SKILL.md` covered it, so the helper simply
  was not found. The fallback list now globs the plugin cache, newest install
  first.
- The README told you to run `fn2 auth login` straight after
  `claude plugin install`, but installing a plugin adds nothing to `PATH`, so
  the only possible outcome was `bash: fn2: command not found`. Connecting is
  now something you ask the assistant to do, with a separate section for
  driving the CLI yourself. `make install` prints the same caveat.
- Both documented snippets are now executed by the test suite against all four
  install layouts (plugin cache, `make install`, Codex, Pi), so they cannot go
  stale silently.

### Added

- A `fn2: command not found` entry in the troubleshooting reference.

## [0.4.0] - 2026-08-10

### Added

- Colour in the human views: agent and run status, ids, table headers, `doctor`
  verdicts, and the `✓` confirmations. It is off unless stdout is a terminal,
  `NO_COLOR` is honoured, `--json` is never colourised, and `--color
  auto|always|never` overrides the lot. New module `fn2cli/style.py`; column
  widths are measured on visible characters, so colour never shifts a table.

### Changed

- The product is written **FN2 AI** throughout. The `fn2` command, the `fn2.ai`
  domain, and the package name are unchanged.
- Output prose no longer uses em dashes.

## [0.3.0] - 2026-08-10

### Changed

- `fn2 agents` prints market cadences in English (`30m before open`,
  `5m after close`) instead of the raw `market_open` / `market_close`
  frequency name.
- Account views line up: `whoami`'s `plan` / `tokens` / `resets` / `device`
  rows now share the 11-column label gutter used by `endpoint`, `credential`,
  and `auth status`.
- `fn2 models` shows `any` for a model with no plan lock, rather than an empty
  `PLAN` column.

### Added

- Documentation media in `docs/media/`, generated by `tools/screenshots/` by
  running the real CLI against fixture payloads, so screenshots cannot drift from
  what the tool prints.
- The FN2 AI brand mark and lockup in `assets/`.
- CI across Python 3.9 to 3.13 plus macOS, manifest validation, issue and pull
  request templates, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`.

## [0.2.1] - 2026-08-06

### Fixed

- The CLI crashed with a `TypeError` traceback on every gateway-originated
  error. nginx returns `{"error": true, "message": …}` where Flask returns
  `{"error": "…"}`; the boolean flag was being used as the message text.
  (FNAI-2468)

### Added

- The research tools and their weekly request allowance are documented in the
  API reference. (FNAI-2411)
- The MCP connector is documented in the API reference. (FNAI-2396)
- Reliable plugin installation for Claude Code and Codex marketplaces.

## [0.2.0] - 2026-07-21

### Added

- `fn2 auth login`: browser device-authorization flow. No secret is pasted,
  printed, or sent to chat. The credential is scoped, revocable, and stored in
  the macOS Keychain or an owner-only file. (FNAI-2127/2125)
- `fn2 auth status`, `fn2 permissions`, and `fn2 doctor`.
- Server-owned market schedules: `--when "before market open"` and
  `"market close"` resolve against the exchange calendar server-side, so runs
  skip holidays and respect half-days. `--email` delivers each completed run to
  the account's own verified address. (FNAI-2130)

### Removed

- `.env` support, so a working-directory file can never inject a credential.

## [0.1.0] - 2026-07-21

- First release: start, watch, and schedule FN2 AI research agents from Claude
  Code, Codex, or Pi.

[0.6.0]: https://github.com/fn2ai/fn2-skill/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/fn2ai/fn2-skill/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/fn2ai/fn2-skill/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/fn2ai/fn2-skill/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/fn2ai/fn2-skill/releases/tag/v0.3.0
[0.2.1]: https://github.com/fn2ai/fn2-skill/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/fn2ai/fn2-skill/releases/tag/v0.2.0
[0.1.0]: https://github.com/fn2ai/fn2-skill/releases/tag/v0.1.0
