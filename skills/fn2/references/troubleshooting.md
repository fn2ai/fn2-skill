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
  (`models` for `fn2 models`). `fn2 permissions` shows what is granted.
- For a manual API key, create a fresh one in the web app and
  `fn2 login --token …` again.

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

The account is over its token budget. `fn2 whoami` shows `used / limit /
remaining` and the reset time. Upgrade the plan or wait for the reset; creating
or running agents is blocked until then.

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
