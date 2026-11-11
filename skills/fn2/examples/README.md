# FN2 research cookbook

Three runnable workflows for developers who want an inspectable research
record: compare earnings periods, reconcile GAAP and adjusted earnings, and
run a short watchlist pilot. The prompts, source rules, and runner ship inside
the skill. Python 3.9+ and its standard library are sufficient.

| Recipe | Inputs | What to inspect in the result |
|---|---|---|
| [Earnings comparison](prompts/earnings.md) | Ticker, two fiscal periods, cutoff date | Matched periods, guidance basis, source-linked changes |
| [GAAP reconciliation](prompts/reconcile.md) | Ticker, fiscal period, cutoff date | Signed adjustments, tax/share basis, arithmetic residual |
| [Watchlist brief](prompts/watchlist.md) | Up to 10 tickers; optional end-dated schedule | Dated evidence, price freshness, gaps and next questions |

These are research instructions, not precomputed investment results. The
examples below use IBM's historical fiscal labels only as user inputs; they do
not assert any company figures. Generated answers and citations need review.
The cutoff instruction does **not** make FN2 a point-in-time backtest database.

## Install or locate your existing skill

For a new project-local Codex installation, run from that project's root:

```bash
DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 npx skills add fn2ai/fn2-skill --skill fn2 --agent codex --yes
FN2_SKILL_DIR="$PWD/.agents/skills/fn2"
```

The install command needs Node.js/npm; the bundled runner needs only Python.
If you already installed the plugin, set `FN2_SKILL_DIR` to the directory
containing its loaded `SKILL.md`; don't install another copy. From a repository
checkout use `FN2_SKILL_DIR="$PWD/skills/fn2"`. See [the install guide](../../../README.md#install-details).

```bash
FN2="$FN2_SKILL_DIR/scripts/fn2"
COOKBOOK="$FN2_SKILL_DIR/examples/cookbook.py"
python3 "$COOKBOOK" --help
```

## 1. Compare two earnings periods

This previews the complete prompt and CLI arguments locally. It does not
read credentials, send a request, or create an agent:

```bash
python3 "$COOKBOOK" earnings --ticker IBM \
  --earlier 'FY2025 Q2' --later 'FY2025 Q3' --as-of 2025-11-01
```

The report should identify the actual issuer, fiscal dates, source coverage,
and comparison basis before drawing conclusions. Review each material source
link and separate issuer explanations from the researcher's interpretation.
For a manual worksheet, see [FN2's earnings comparison guide](https://fn2.ai/blog/compare-earnings-calls-across-quarters).

## 2. Check a GAAP-to-adjusted bridge

```bash
python3 "$COOKBOOK" reconcile --ticker IBM \
  --period 'FY2025 Q3' --as-of 2025-11-01
```

The prompt requests the issuer's reconciliation, compatible units and
denominators, signed adjustments, and the difference between its computed and
reported total. It preserves missing information instead of forcing a balance.
It does not assume that adjusted earnings are cash earnings or that companies'
adjusted definitions are comparable. See [the reconciliation worksheet](https://fn2.ai/blog/gaap-vs-adjusted-eps-reconciliation-workflow).

## Connect and execute a reviewed prompt

An FN2 account and available agent quota are required. The open-source client
does not make the hosted service free or bypass plan/cadence restrictions.
Browser device authorization requests `agents`, `models`, and read-only
`research`; there is no credential to paste into a command, prompt, or
repository:

```bash
python3 "$FN2" auth login --no-wait
# Approve the displayed code at https://fn2.ai/start.
python3 "$FN2" auth login --no-browser
python3 "$FN2" auth status
python3 "$FN2" whoami
python3 "$FN2" models
```

When an assistant drives this flow, it should relay the code immediately and
run the finishing wait in the background, as [the skill explains](../SKILL.md#first-run-connect-an-account-no-secret-copying).
The credential stays in macOS Keychain or the CLI's owner-only config file.
For CI, inject `FN2_API_TOKEN` from a secret manager; `.env` is not supported.

After reviewing a preview, add `--execute` to create exactly one agent:

```bash
python3 "$COOKBOOK" earnings --ticker IBM \
  --earlier 'FY2025 Q2' --later 'FY2025 Q3' --as-of 2025-11-01 \
  --execute > earnings-agent.json
```

Use the same flag on `reconcile` to run that recipe. `--model` is optional;
when omitted the service selects its default. To choose, pass an exact model
ID currently available from `models`, not a copied historical model name.

The JSON is an **agent creation receipt**, not a completed research report.
`--json start` returns immediately; it does not wait for results. Save the ID,
then inspect the agent and retrieve the particular run you want to preserve:

```bash
AGENT_ID="$(python3 -c 'import json; d=json.load(open("earnings-agent.json")); print(d.get("id") or d["agent_id"])')"
python3 "$FN2" status "$AGENT_ID"
python3 "$FN2" --json runs "$AGENT_ID" > earnings-runs.json
# When a run is completed, get the newest result or use its exact run ID:
python3 "$FN2" --json result "$AGENT_ID" > earnings-result.json
```

Check `status` in the result; pending or failed is not an answer. For durable
comparisons use `result "$AGENT_ID" "$RUN_ID"` after setting `RUN_ID` to a
completed ID from `runs`. Keep the prompt, source ledger, run ID, model, and
retrieval time beside your report. Do not publish account metadata or secrets.

Each `--execute` creates a new agent. After a timeout, inspect `agents` before
retrying; the cookbook does not automatically retry creates. `run "$AGENT_ID"`
starts another potentially quota-consuming run. A 403 plan restriction or 429
quota response should be resolved before another attempt; there is no retry loop.

## 3. Preview once, then schedule a bounded watchlist

Start with the one-off version. Adding `--execute` runs it now:

```bash
python3 "$COOKBOOK" watchlist --tickers AAPL MSFT NVDA
```

For a short recurring pilot, choose an end date after today's UTC date and no
more than 31 days away. This example computes a date seven days ahead:

```bash
END_DATE="$(python3 -c 'import datetime as d; print(d.datetime.now(d.timezone.utc).date() + d.timedelta(days=7))')"
python3 "$COOKBOOK" watchlist --tickers AAPL MSFT NVDA \
  --schedule --ends "$END_DATE"
# Review the preview, then create the recurring agent:
python3 "$COOKBOOK" watchlist --tickers AAPL MSFT NVDA \
  --schedule --ends "$END_DATE" --execute > watchlist-agent.json
```

This sends the public API a `market_open` schedule with `offset_minutes: -30`,
`timezone: America/New_York`, and `ends_at`. The server owns the exchange
calendar; inspect `status` for the actual next run and normalized end time.
The end date is a deadline, not a guarantee of seven runs. A scheduled start
does not guarantee the report finishes before the open. No email delivery is
requested. Plan, model, quota, and cadence limits still apply.

```bash
WATCH_ID="$(python3 -c 'import json; d=json.load(open("watchlist-agent.json")); print(d.get("id") or d["agent_id"])')"
python3 "$FN2" status "$WATCH_ID"
python3 "$FN2" pause "$WATCH_ID"
```

`pause` stops future scheduled runs; it does not undo a run already underway.
Keep the agent paused while checking cost and source quality. The cookbook
does not automatically extend its deadline, resume it, or delete history.
The 72-hour search window can overlap reports or miss events during longer
gaps; no persistent-memory or real-time-alert claim is made.

## Evidence rules and verification

The shared [evidence rules](prompts/evidence.md) require dates, exact source
locations, comparable units, and labeled gaps. Financial-statement context
comes from [Investor.gov's guide to reading a 10-K](https://www.investor.gov/introduction-investing/getting-started/researching-investments/how-read-10-k).
The [SEC's non-GAAP interpretations](https://www.sec.gov/rules-regulations/staff-guidance/corporation-finance-interpretations/non-gaap-financial-measures)
explain why definitions, tax effects, and treatment across periods matter.
These materials inform the workflow; they do not validate a generated answer.

`make test` exercises all three workflows through the real CLI parser and HTTP
client with an offline transport fixture, including result retrieval and pause.
It checks credential-free previews and rejects unbounded or stale schedules.
`make lint` compiles the helper and cookbook. No live financial report, model
quality, account quota, or successful paid research run is claimed by those
tests. API details: [public contract](../references/api.md),
[calendar semantics](../references/scheduling.md), and
[troubleshooting](../references/troubleshooting.md).
