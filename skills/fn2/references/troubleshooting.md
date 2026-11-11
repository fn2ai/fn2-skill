# Troubleshooting

## `bash: fn2: command not found`

Expected. Installing the plugin installs a **skill**, not a binary; nothing is
added to `PATH`. Normally you never type `fn2` at all, you ask the assistant
("connect my FN2 AI account", "what are my agents doing?") and it runs the
bundled helper.

To get the command, run the helper once by path and let it install a launcher:

```bash
python3 "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/plugins/cache/fn2/fn2/*/skills/fn2/scripts/fn2 link
```

It writes `fn2` into the first writable `bin` directory on your `PATH`, and
prints the `export PATH=…` line to add if there isn't one. The launcher
re-resolves the skill on every run, so a plugin update (which moves the
versioned install directory) cannot strand it. `fn2 unlink` removes it.

If the one-liner itself reports "No such file or directory", the plugin is not
installed where expected: check `claude plugin list`, and look for
`plugins/cache/<marketplace>/<plugin>/<version>/skills/fn2` under
`${CLAUDE_CONFIG_DIR:-$HOME/.claude}`.

## "not signed in"

No credential was found. Run `fn2 auth login` (browser flow, no secret
copying), or set `FN2_API_TOKEN` for headless use. Check what the skill sees
with `fn2 auth status`. It prints the storage backend, the masked credential,
scopes, expiry, and a live verification.

Resolution order: `FN2_API_TOKEN` env → `FN2_API_KEY` env (legacy) → macOS
Keychain → `~/.config/fn2/credentials.json`. There is no `.env` support.

## Revoked device / HTTP 401 / 403

- `fn2 auth status` says "FN2 AI rejected this credential": the device was revoked
  (web app → Preferences → Developer → Connected Devices), expired (device
  tokens live 90 days), or the account changed. Reconnect with
  `fn2 auth login`.
- Revocation takes effect within a few minutes everywhere, so a request that
  still succeeds seconds after revoking elsewhere can be that propagation
  window, not a bug.
- 403 on a specific route usually means the credential lacks that scope
  (`models` for `fn2 models`, `research` for the research commands; see the
  next section). `fn2 permissions` shows what is granted.
- For a manual API key, create a fresh one in the web app and
  `fn2 login --token …` again.

## "Missing scope: research"

```text
error: HTTP 403: Missing scope: research
this sign-in does not carry the `research` scope (it has: agents, models). …
```

The research commands (`earnings`, `calls`, `transcript`, `search`,
`financials`, `price`, `fred`, `recall`) need the `research` scope. Sign-ins
made before 0.8.0 asked only for `agents` and `models`, and a credential never
gains a scope after it is issued. Nothing is wrong with the account.

- **Signed in through the browser** (the usual case): sign in again.
  `fn2 auth login --no-wait` prints a code and URL, the user approves it at
  fn2.ai/start, and `fn2 auth login` finishes. Agents, schedules, and results
  are untouched. Assistants: use the two-step flow in SKILL.md, then re-run
  the command that failed.
- **`FN2_API_TOKEN` / `FN2_API_KEY` is set**: signing in cannot change an
  environment variable. Replace its value with a credential that has
  `research`, or unset it and run `fn2 auth login`.
- **A manual API key**: its scopes were chosen when it was created. Create a
  key with `research` under Preferences → Developer, or switch to
  `fn2 auth login`.

`fn2 permissions` lists `research` under "not granted yet" until this is done;
`fn2 auth status` shows the same on its `research` line.

The new sign-in revokes the stored device credential it replaces, so the old
device does not linger under Preferences → Developer → Connected Devices. That
clean-up is best effort and never blocks the sign-in: if FN2 AI could not be
reached for it, the CLI says so in one line, and the old device can be revoked
from that page. An account already at its limit of 10 connected devices has to
revoke one there first, because the new device is created before the old one
is removed.

## The browser never opened during `auth login`

The CLI opens the browser whenever the machine can show one: always on macOS
and Windows, on Linux when `DISPLAY` / `WAYLAND_DISPLAY` is set, never over a
plain SSH session (it would open on the wrong machine). It does **not** require
stdout to be a terminal, so it works when an assistant drives it through a
pipe. If no tab appears anyway, open the printed URL by hand — on any device;
the code, not the browser session, is what links the terminal. `--no-browser`
suppresses the attempt on purpose.

Assistants: use the two-step flow in SKILL.md (`auth login --no-wait`, relay
the code, then resume with `auth login --no-browser` in the background) so the
code reaches the user immediately.

## "the sign-in code expired before approval"

Device-login codes live 15 minutes. Just run `fn2 auth login` again; a fresh
code is issued. Nothing was stored, and the browser side shows its own
restart guidance.

## Interrupted login / resuming

`fn2 auth login` is safe to Ctrl-C: the pending state (never the credential)
is kept in `~/.config/fn2/device_login_pending.json`, and the next
`fn2 auth login` resumes the same code if it is still valid, otherwise starts
fresh. Devices are only created at browser approval, so an interrupted login
never leaves a half-connected device behind.

## "warning: … is group/world-accessible"

The credentials (or pending) file must be owner-only. The skill still reads it
but warns on every use. Fix with:

```bash
chmod 700 ~/.config/fn2
chmod 600 ~/.config/fn2/credentials.json
```

`fn2 doctor` re-checks these permissions. A symlinked credentials file is
refused outright, so remove the link.

## "error: refusing endpoint …" (origin pinning)

The API base must be `https://` on `fn2.ai` or a `*.fn2.ai` subdomain
(`--base-url`, `FN2_BASE_URL`, and the stored `base_url` are all checked).
Anything else (plain `http://`, another domain, or lookalikes such as
`fn2.ai.evil.com`) is refused so the credential can never be sent to a
non-fn2 origin. `FN2_ALLOW_DEV_BASE=1` bypasses the pin **for local
development only** and prints a loud warning.

## Keychain prompts or failures (macOS)

The credential lives in the login Keychain (service `fn2-skill`). If macOS
prompts, allow the `security` tool. If Keychain writes fail (locked keychain,
CI without a session), unlock it or use `FN2_API_TOKEN`.

## HTTP 429 (quota)

Two separate meters, both shown by `fn2 whoami`:

- **Tokens** (monthly; agents). The account is over its token budget. `whoami`
  shows `used / limit / remaining` and the reset time. Upgrade the plan or
  wait for the reset; creating or running agents is blocked until then.
- **Research requests** (weekly; the research commands). The error is one
  sentence from FN2, printed as sent:

  ```text
  error: The Free plan includes 25 FN2 research requests per week, and you've used all 25. Your quota resets on Monday, 16 November (UTC). Upgrade at https://fn2.ai/preferences#billing for a higher weekly limit.
  ```

  Its code is `api_quota_exceeded`. Relay that sentence as written and do not
  retry: the number does not change before the reset. Agents are unaffected,
  so `fn2 start "…" --wait` still works for the same question. Only successful
  reads are counted; a `404` or `503` costs nothing.

## A research command says FN2 has no data (HTTP 404)

`FN2 has no earnings results…`, `FN2 holds no earnings-call transcripts…`,
`No SEC-derived financials…`, `No market data for symbol…`: FN2 does not cover
that symbol, period, or series. It is an answer, not an outage, and retrying
will not change it. Check the ticker; `fn2 calls SYMBOL` shows which calls are
held; financials cover US filers with XBRL statements. An agent run
(`fn2 start`) can look further afield.

## A research command's output was cut off

Terminal assistants cut a command's output near 30,000 characters. The research
views fit under that by default (a transcript page is 24,000 characters), and
when one does not, its first line says so. Ask for less (`--limit`, a smaller
`--max-chars`), or page a transcript with the `next page:` command it prints
rather than raising `--max-chars`. `--json > file` keeps everything.

## "could not reach https://fn2.ai"

Network/DNS/TLS problem reaching the endpoint, not an API error. `fn2 doctor`
runs an unauthenticated reachability check. Confirm connectivity, any corporate
proxy, and that `FN2_BASE_URL` (if set) is correct.

## HTTP 400 on `start`

- `prompt is required`: pass a non-empty prompt.
- `schedule requires either run_at or frequency`: the cadence didn't parse to a
  recurring or one-off shape; check `references/scheduling.md`.
- `cron must have 5 fields`: a `cron:` expression needs `min hour dom month dow`.

## A one-off time fails with a zoneinfo error

The Python build lacks `zoneinfo` (pre-3.9). Use a recurring cadence, or give an
absolute UTC time like `2026-07-22T13:00`.

## Where is my credential stored?

- macOS: the login Keychain, service `fn2-skill`, account = the API host; the
  non-secret metadata lives in `~/.config/fn2/credentials.json`.
- Linux (and macOS without `security`): `~/.config/fn2/credentials.json`
  (or `$FN2_CONFIG_HOME`), mode `0600`.

Remove it with `fn2 auth logout`; add `--revoke` to also revoke the device on
fn2 (a 401 during revoke means it was already dead, which is fine). The web app
lists and revokes every connected device under Preferences → Developer →
Connected Devices.
