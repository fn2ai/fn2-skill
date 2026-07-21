# Troubleshooting

## "not signed in"

No key was found. Run `fn2 login` (or set `FN2_API_KEY`). Check what the skill
sees with `fn2 whoami` — it prints the endpoint, the masked key, and where the
key was read from (`env`, `dotenv`, or `file`).

## "fn2 rejected that key" / HTTP 401 / 403

- The key is revoked, expired, or missing the **`agents`** scope. Create a fresh
  one in the fn2 web app and `fn2 login --token …` again.
- 403 on a specific route usually means the key lacks that scope (`models`
  for `fn2 models`).

## HTTP 429 (quota)

The account is over its token budget. `fn2 whoami` shows `used / limit /
remaining` and the reset time. Upgrade the plan or wait for the reset; creating
or running agents is blocked until then.

## "could not reach https://fn2.ai"

Network/DNS/TLS problem reaching the endpoint, not an API error. Confirm
connectivity, any corporate proxy, and that `FN2_BASE_URL` (if set) is correct.

## HTTP 400 on `start`

- `prompt is required` — pass a non-empty prompt.
- `schedule requires either run_at or frequency` — the cadence didn't parse to a
  recurring or one-off shape; check `references/scheduling.md`.
- `cron must have 5 fields` — a `cron:` expression needs `min hour dom month dow`.

## A one-off time fails with a zoneinfo error

The Python build lacks `zoneinfo` (pre-3.9). Use a recurring cadence, or give an
absolute UTC time like `2026-07-22T13:00`.

## Where is my key stored?

`~/.config/fn2/credentials.json` (or `$FN2_CONFIG_HOME`), mode `0600`. Remove it
with `fn2 logout`.
