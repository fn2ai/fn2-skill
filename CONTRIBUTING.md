# Contributing

Thanks for helping. This repository is small on purpose: a skill an assistant
loads and a CLI it shells out to, so the bar is less about volume and more
about keeping those two things honest.

## The constraints

They are not negotiable, and a change that breaks one will be sent back:

1. **Standard library only.** No `pip install`, no `requirements.txt`, no
   `pyproject.toml`, no vendored packages. The skill has to work the moment a
   harness clones it. CI fails if a dependency manifest appears.
2. **Python 3.9+.** CI runs 3.9 through 3.13, plus macOS for the Keychain path.
3. **No network in tests.** Swap `Client._urlopen`; that seam exists for this.
4. **Credentials never surface.** Not in stdout, not in `--json`, not in error
   text, not in argv. `config.mask` / `config.redact` and the storage rules in
   [SECURITY.md](SECURITY.md) are load-bearing.
5. **The API base stays pinned** to `https://fn2.ai` / `*.fn2.ai`.

## Getting set up

```bash
git clone https://github.com/fn2ai/fn2-skill
cd fn2-skill
make test          # unittest, offline
make lint          # byte-compile every module
make install       # symlink the canonical skill into Claude / Codex / Pi
```

`make install` is idempotent and refuses to clobber a real directory. Undo it
with `make uninstall`; stored credentials are left alone.

To try it against your own account:

```bash
alias fn2='python3 skills/fn2/scripts/fn2'
fn2 auth login
fn2 doctor
```

## Where things live

| Change | File |
|---|---|
| a new verb or flag | `skills/fn2/scripts/fn2cli/cli.py` |
| a new endpoint | `skills/fn2/scripts/fn2cli/api.py` (+ `references/api.md`) |
| a new cadence phrase | `skills/fn2/scripts/fn2cli/schedule.py` (+ `references/scheduling.md`) |
| how output looks | `skills/fn2/scripts/fn2cli/render.py` |
| what the assistant is told | `skills/fn2/SKILL.md` |
| screenshots | `tools/screenshots/`, never hand-edit `docs/media/` |

`SKILL.md` is a prompt, not documentation. Every sentence costs context in
every session that loads it; add one only if an assistant would get the task
wrong without it.

## If you change CLI output

The screenshots are captured from the real CLI, so they go stale silently.
Regenerate them in the same PR:

```bash
python3 tools/screenshots/generate.py
```

See [tools/screenshots/README.md](tools/screenshots/README.md) for how the
capture works and why it is not a mockup.

## Pull requests

- One concern per PR. The last commit subject becomes the PR title.
- Add a test for anything with a failure mode. `tests/` is offline and fast;
  keep it that way.
- Bump `__version__` in `skills/fn2/scripts/fn2cli/__init__.py` **and** both
  plugin manifests together; a packaging test enforces that they match.
- Note user-visible changes in [CHANGELOG.md](CHANGELOG.md).

## Reporting problems

Bugs and feature requests go through the
[issue forms](https://github.com/fn2ai/fn2-skill/issues/new/choose). Suspected
vulnerabilities go to [SECURITY.md](SECURITY.md) instead, privately.
