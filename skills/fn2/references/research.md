# Direct research reads

Eight commands read FN2 AI's market data without starting an agent. Each is one
`GET` under `/api/v1/research/*` (see [api.md](api.md#research)): read-only,
answered in about a second, no model tokens spent.

Use them for a factual question about one company or one series. Start an agent
(`fn2 start "…" --wait`) when the answer needs news, web pages, the text of a
filing, prediction markets, synthesis across many companies, or a schedule.

Invoke the helper as `python3 "$FN2" <command>`; `fn2 <command>` below is the
same thing after `fn2 link`. Hints printed by the CLI use the `fn2` form.

## Commands

| Command | Returns | Options (bounds, default) |
|---|---|---|
| `earnings SYMBOL` | reported quarters newest first: fiscal quarter, report date, EPS and revenue vs analyst consensus, the call's transcript id; then the next scheduled report | `--limit` 1-12 (4) |
| `calls SYMBOL` (alias `transcripts`) | the earnings calls FN2 holds text for: date, fiscal label, size, transcript id | `--limit` 1-40 (8) |
| `transcript SYMBOL` | one call's text in speaker order, one page per request. `SYMBOL` alone is the most recent call | `--id ID`, or `--year Y --quarter Q`; `--offset N` (0); `--max-chars` 1000-60000 (24000) |
| `search QUERY…` | relevance-ranked speaker turns from call transcripts | `--symbol S`, `--after YYYY-MM-DD`, `--call ID`, `--limit` 1-20 (5) |
| `financials SYMBOL` | income, margin, cash-flow, and debt figures from SEC filings, by period | `--annual` (default), `--quarterly`; `--ttm` exists but is rarely available; `--limit` 1-12 (5) |
| `price SYMBOL` (aliases `prices`, `quote`) | current quote; with `--range`, price bars | `--range` 1D, 5D, 1M, 3M, 6M, YTD, 1Y, 5Y, MAX |
| `fred [SERIES_ID]` | observations for one FRED series; with no id, the list of series FN2 tracks | `--limit` 1-500 (60) |
| `recall [QUERY…]` | notes the account's own FN2 agents saved | `--agent ID\|NAME`, `--tag T`, `--limit` 1-50 (12) |

Every command takes `--json` for the API payload exactly as returned. Values
outside the bounds are refused before any request is made, so nothing is
silently clamped.

## Reading the output

The human view is written for a reader who cannot ask a follow-up: figures are
exact (`12,874,180,000`, never `12.87B`), dates are ISO, transcript ids are
printed in full because they are arguments to the next command, and missing
data is a sentence (`not available`), never a blank or a zero.

### `earnings`

```text
NFLX earnings, FN2 data as of 2026-11-11: 4 reported quarters FN2 holds, newest first
[1] Q3 '26 = fiscal 2026 Q3, quarter ended 2026-09-30 | reported 2026-10-20, after market close
    EPS      actual … | consensus … | surprise … (…%) | beat consensus
    revenue  actual … | consensus … | surprise … (…%) | beat consensus
    call     held 2026-10-20 | transcript id <id>
next report: 2027-01-19, … (date is a scheduled estimate, not company-confirmed) | Q4 '26 …
```

- **Consensus is analyst consensus** from FN2's market-data vendor at report
  time. It is not company guidance, and `earnings` contains no guidance at
  all: guidance is in the call.
- The surprise, its percentage, and beat / miss / match are computed by FN2.
  Do not recompute them.
- The EPS basis (GAAP or adjusted) is whatever the vendor reports. For filed
  GAAP figures use `financials`.
- `POSSIBLY STALE:` as the first line means the newest result FN2 holds is old
  and nothing is scheduled, so the company has very likely reported since.
  Relay that; do not call row `[1]` the latest quarter without it.
- The report session is `after market close`, `before market open`, or
  `unknown`. Unknown means unknown.
- The next report date is the vendor's schedule, never a company confirmation.
- `call  not available` means FN2 holds no transcript within two weeks of that
  report date. It never substitutes the nearest other call.
- Any field can be `not available`: revenue while EPS is present, the fiscal
  label, the call, the next report.

### `calls` and `transcript`

`transcript` prints the paging status above and below the text:

```text
characters 0 to 23,950 of 36,427, in speaker order ("Name: paragraph" blocks)
next page: fn2 transcript NFLX --id <id> --offset 23950
----- call text begins (verbatim) -----
…
----- call text ends -----
next page: fn2 transcript NFLX --id <id> --offset 23950
```

- Run the `next page:` command as printed until the output says `end of call`.
  Pages break on paragraph boundaries and join exactly. A typical call is about
  41,000 characters, so two pages; long calls run to 160,000.
- Each page is one request against the weekly allowance.
- Prefer `--id` from `earnings`. `--year` / `--quarter` use the transcript's
  own fiscal label, which can differ from the `earnings` label when a company's
  fiscal year is offset from the calendar.
- Keep the default page size. Terminal assistants cut tool output near 30,000
  characters; when a view exceeds that, its first line says so.
- The text is the call as transcribed. Quote it with the speaker's name.

### `search`

- Hits are ranked by **relevance, not date**. To search the latest call, take
  its transcript id from `earnings` and pass `--call`.
- Each hit is one whole speaker turn with the company, call date, speaker, and
  transcript id. Turns shorter than 40 characters ("Thanks.", "Next question")
  are never returned.
- Each hit ends with how it matched. `matched your words: …` lists the query
  words FN2 found in the passage. `matched by meaning only` means none were
  found: the search also returns the passages nearest in meaning, and it
  returns them even when the call never raised the topic. Read a meaning-only
  hit before citing it. When every hit is meaning-only the output opens with a
  `CAUTION` line, and the honest answer is often that the call does not
  discuss the topic.
- `--after` and `--call` combine: a call outside the date window gives no hits.
- No hits means FN2 holds no matching call text. It does not mean the company
  said nothing; coverage varies by company and period.
- A topic missing from a call may live elsewhere. Buybacks, for example, are
  often in the shareholder letter or a filing rather than the call, and the
  direct data holds neither. Say so, and offer an agent run, which can search
  filings and news.
- If FN2 does not recognise the `--symbol` value as a ticker, the search runs
  across all companies and the output carries a `WARNING` line saying so.

### `financials`

Columns are periods, newest first; rows are line items.

- Source: the company's 10-K and 10-Q filings (US filers with XBRL statements).
  Each column shows its period end, form, and filing date.
- Amounts are whole currency units as filed, not thousands or millions.
  Margin and growth rows are percentages. Growth is year over year, and is
  `-` when FN2 has no comparable year-ago period to measure against.
- `-` means FN2's filing data has no value for that item in that period. It
  does not mean zero.
- `--quarterly` columns come from 10-Q filings. A fiscal fourth quarter is
  reported on the 10-K, so it has no quarterly column; and the newest quarter
  appears only after its 10-Q is filed, which can be days or weeks after the
  earnings release. Match a column to an `earnings` row by `period end` =
  `quarter ended`. No match means the filed figures are not available yet.
- Prefer `--quarterly` or `--annual`. `--ttm` sums four consecutive quarterly
  filings, and because a fiscal fourth quarter is filed on the 10-K, most
  companies never have four 10-Qs in a row: FN2 then answers `not_found` with
  a sentence saying so. Relay that sentence; do not estimate a trailing
  figure by adding quarters yourself.
- A `withheld by FN2` line names a growth figure FN2 declined to compute and
  why, typically EPS growth across a stock split, where filed per-share
  figures are not on the same basis. Do not compute it from the EPS row.
- Market cap, enterprise value, and forward estimates are not in this source;
  the last line of the output says so.

### `price`

- Delayed market data, not a real-time trading feed.
- `regular` is the regular-session price with its change and previous close;
  `extended` is the last pre-market or after-hours print when there is one.
- `--range` adds bars, oldest first: intraday bars for 1D to 3M, daily for 6M,
  YTD and 1Y, weekly for 5Y, monthly for MAX. At most 400 bars are returned;
  if older ones were dropped the output says so.

### `fred`

- `fred` alone lists the series FN2 tracks. `fred DGS10` prints observations
  oldest first with the year-over-year, month-over-month, and
  quarter-over-quarter changes FN2 holds for that series.
- `--limit` is the number of most recent observations.

### `recall`

- Searches notes saved on the user's own account by their FN2 agents
  (holdings, watchlists, stated preferences). It returns nothing from other
  accounts and nothing about markets in general.
- `--agent` takes an id, an id prefix, or a name, like the agent commands.

## Recipes

**Latest earnings report and call** ("summarize NFLX's most recent earnings"):

```bash
python3 "$FN2" earnings NFLX                         # quarter, report date, EPS/revenue vs consensus, transcript ids
python3 "$FN2" transcript NFLX --id <row 1 id>       # the call; repeat the printed "next page:" until "end of call"
python3 "$FN2" financials NFLX --quarterly           # filed operating margin for the matching period end
python3 "$FN2" search "guidance outlook operating margin" --call <row 2 id>   # what was guided the quarter before
```

About five requests. Report the quarter and report date from `earnings`; the
headline numbers against consensus from `earnings`; margins from `financials`
if the period is there; guidance and management's themes from the transcript,
attributed. Anything the four outputs do not contain is stated as not in FN2's
data.

**Did it beat?** `earnings SYMBOL --limit 1`.

**What did management say about a topic on the last call?**
`earnings SYMBOL --limit 1` for the transcript id, then
`search "topic" --call <id>`; read the surrounding call with `transcript` if
the hit needs context. If the hits are all `matched by meaning only` and none
is actually about the topic, the answer is that the call does not discuss it:
say so, then try the previous call's id, or offer an agent run.

**How has a theme moved across calls?**
`search "topic" --symbol SYMBOL --after YYYY-MM-DD --limit 10`, then order the
hits by their call dates yourself; the ranking is by relevance.

**Margin or cash-flow trend:** `financials SYMBOL --quarterly --limit 8`, or
`--annual` (not `--ttm`, which is rarely available).

**When is the next report?** The `next report:` line of `earnings SYMBOL`. Say
that the date is a scheduled estimate.

**Rates and macro:** `fred` to find the series id, then `fred <ID> --limit N`.

## Rules for answers built on these commands

1. State periods and dates as printed. Do not convert a fiscal quarter into a
   calendar quarter.
2. Call consensus "analyst consensus". It is not guidance.
3. Quote or paraphrase only returned text, attributed to the speaker and call.
4. Add no number, quote, or guidance from memory, even one you are sure of.
5. Say what is missing. "FN2's data does not include company guidance for
   that metric" is a complete, correct sentence.
6. Relay warnings the output carries (`POSSIBLY STALE`, `WARNING`, `CAUTION`,
   data-quality flags, `withheld by FN2`, `note from FN2`).
7. A topic a call does not cover is an answer. Say the call does not discuss
   it; do not stretch a meaning-only hit into a quote on that topic.

## Access, allowance, and errors

- **Scope.** The commands need the `research` scope. `fn2 auth login` requests
  it since 0.8.0. A sign-in made earlier fails with
  `HTTP 403: Missing scope: research`, and the CLI prints the fix: sign in
  again (`fn2 auth login --no-wait`, approve the code, `fn2 auth login`). The
  account, agents, and schedules are untouched, and the credential the new
  sign-in replaces is revoked. `fn2 permissions` and
  `fn2 auth status` show whether the scope is present. A credential supplied
  through `FN2_API_TOKEN`, or a manual API key, has to be replaced by one
  created with `research`.
- **Weekly allowance.** Each successful read spends one research request
  (see the table in [api.md](api.md#the-research-surface-and-its-weekly-allowance)).
  `fn2 whoami` shows used, limit, remaining, and the reset time. Failed
  lookups (`404`, `503`) are free.
- **`api_quota_exceeded` (HTTP 429).** The allowance is used up. The CLI prints
  FN2's sentence, which names the plan, the limit, the reset date, and the
  upgrade URL. Relay it as written. Do not retry; nothing changes before the
  reset.
- **`not_found` (HTTP 404).** FN2 has no data for that symbol, call, or series.
  The message says which. This is an answer, not an outage.
- **`upstream_unavailable` / `quota_check_failed` (HTTP 503).** A data source
  is briefly unavailable. The message gives the seconds to wait; one retry
  after that is reasonable.
- **`invalid_request` (HTTP 400).** An argument FN2 could not use, for example
  a symbol it does not recognise as a ticker.
