# Security policy

## Reporting a vulnerability

Report privately through
[GitHub Security Advisories](https://github.com/fn2ai/fn2-skill/security/advisories/new).
Please do not open a public issue for a suspected vulnerability.

Include what you can: the command or flow, what you expected, what happened,
and whether a credential could leave the machine. We aim to acknowledge within
three business days.

**Never include a real credential in a report.** All CLI output is redacted to
a masked `fn2d_…wxyz` form already, so paste it as printed.

## What this skill guarantees

These are the properties worth attacking; a break in any of them is a
vulnerability, not a bug report.

| Guarantee | Where it lives |
|---|---|
| The credential is only ever sent to `https://fn2.ai` or `*.fn2.ai` | `config.enforce_base_url` |
| No secret appears in output, `--json`, error text, or argv | `config.mask` / `config.redact`, `storage` (Keychain writes go over stdin) |
| No working-directory file can inject a credential or endpoint: there is no `.env` support | `config.resolve` |
| Stored credentials are owner-only: directory `0700`, file `0600`, symlinks refused, `O_NOFOLLOW` on write | `storage._write_owner_json` |
| The pending device-login state never contains an access token | `storage.save_pending` |
| A server-supplied poll interval cannot wedge the CLI | `deviceauth.poll_until_complete` |

## Revoking access

A device credential is scoped and revocable. Its scopes are `agents`,
`models`, and `research` (read-only: FN2's market data and the notes your own
agents saved). It cannot read or change billing, email, or password; cannot
open a web session or read your chats; and cannot approve new devices or
create API keys.

```bash
fn2 auth logout --revoke
```

Or revoke it in the FN2 AI web app under **Preferences → Developer → Connected
Devices**. Revocation takes effect within a few minutes everywhere.

Signing in again on a machine that already holds a device credential revokes
the one being replaced, so a superseded credential does not stay active. The
old token is sent only to the endpoint that issued it, and a failure to revoke
never blocks the new sign-in.

## Supported versions

The latest release on `main` is supported. Fixes ship forward; there are no
backport branches.
