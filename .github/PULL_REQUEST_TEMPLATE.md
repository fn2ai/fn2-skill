<!-- Keep this short. What changed, and why it is safe. -->

## What

## Why

## Checks

- [ ] `make test` passes
- [ ] `make lint` passes
- [ ] No new runtime dependency — the skill stays standard-library only
- [ ] No credential, token, or account identifier in the diff or screenshots
- [ ] If CLI output changed: `python3 tools/screenshots/generate.py` re-run and
      `docs/media/` updated
- [ ] If the contract changed: `skills/fn2/references/api.md` updated
