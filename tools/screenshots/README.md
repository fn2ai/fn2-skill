# Documentation media

Everything in [`docs/media/`](../../docs/media) is generated:

```bash
python3 tools/screenshots/generate.py            # all of it
python3 tools/screenshots/generate.py agents     # one scene
```

Requirements: a Chromium/Chrome binary and ImageMagick's `convert`. None of
this is needed to *use* the skill — it only rebuilds the images in the README.

## Why it is not a mockup

`capture.py` imports the shipped CLI and calls `fn2cli.cli.main()` exactly as a
shell would. Two seams are swapped, and only two:

| Seam | Replaced with | Why |
|---|---|---|
| `Client._urlopen` | the fixture router in `fixtures.py` | the same transport seam the unit tests use; keeps the docs offline |
| the macOS Keychain adapter | an in-memory dict | so the captured output shows the backend a Mac user actually gets |

Argument parsing, cadence translation, storage, redaction, table layout, and
every string in the screenshots come from the real code. If the CLI's output
changes, re-running `generate.py` changes the screenshots — they cannot drift.

The payloads in `fixtures.py` are real fn2 API response shapes with demo
identifiers substituted, and timestamps anchored to the most recent market
session at generation time. `--home` sets the demo home directory whose path
appears in `fn2 doctor` output.

## Files

| File | Role |
|---|---|
| `fixtures.py` | the API payloads served to the CLI |
| `capture.py` | runs the CLI against them and captures stdout |
| `scenes.py` | which commands each screenshot shows |
| `generate.py` | HTML + headless Chrome + trim → PNG |
| `fonts/` | JetBrains Mono and Libre Franklin, both SIL OFL 1.1 (licenses alongside) |
