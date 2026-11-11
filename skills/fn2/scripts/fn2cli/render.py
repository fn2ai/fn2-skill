"""Human-readable and JSON rendering. Presentation only, no network, no logic.

Every view degrades gracefully: the FN2 AI API may add or rename fields, so we
read defensively and never crash on a missing key.

Colour goes through :mod:`style`, which is a no-op unless stdout is a terminal,
so piped and ``--json`` output stays plain text.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import re
import textwrap
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import style

NONE = "-"


def emit_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=False, default=str))


def _first(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if isinstance(d, dict) and d.get(key) not in (None, ""):
            return d[key]
    return default


def short_id(value: Any, width: int = 8) -> str:
    text = str(value or "")
    return text[:width] if text else NONE


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z")


def fmt_ts(value: Any) -> str:
    if not value:
        return NONE
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def rel_ts(value: Any) -> str:
    if not value:
        return "never"
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    delta = dt.datetime.now(dt.timezone.utc) - parsed
    seconds = int(delta.total_seconds())
    future = seconds < 0
    seconds = abs(seconds)
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            span = f"{seconds // size}{unit}"
            break
    else:
        span = f"{seconds}s"
    return f"in {span}" if future else f"{span} ago"


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    """Print an aligned table. Cells may already carry ANSI styling: widths are
    measured on the visible text, so colour never shifts a column."""
    if not rows:
        print("(none)")
        return
    cols = [str(h) for h in headers]
    widths = [len(h) for h in cols]
    text_rows: List[List[str]] = []
    for row in rows:
        cells = [str(c) for c in row]
        text_rows.append(cells)
        for i, cell in enumerate(cells):
            widths[i] = max(widths[i], style.width(cell))
    print(style.head("  ".join(h.ljust(widths[i]) for i, h in enumerate(cols)).rstrip()))
    print(style.label("  ".join("-" * widths[i] for i in range(len(cols)))))
    for cells in text_rows:
        line = "  ".join(style.pad(cells[i], widths[i]) for i in range(len(cells)))
        print(line.rstrip())


def _market_phrase(freq: str, offset: Any) -> str:
    """"market_open" + -30 gives "30m before open". The server owns the calendar."""
    boundary = "open" if freq == "market_open" else "close"
    try:
        minutes = int(offset)
    except (TypeError, ValueError):
        minutes = 0
    if minutes < 0:
        return f"{abs(minutes)}m before {boundary}"
    if minutes > 0:
        return f"{minutes}m after {boundary}"
    return f"at the {boundary}"


def describe_schedule(agent: Dict[str, Any]) -> str:
    schedule = agent.get("schedule")
    if isinstance(schedule, dict):
        if schedule.get("run_at"):
            return f"once @ {fmt_ts(schedule['run_at'])}"
        freq = schedule.get("frequency")
        cron = schedule.get("cron")
        if freq == "custom" and cron:
            return f"cron {cron}"
        if freq in ("market_open", "market_close"):
            return _market_phrase(freq, schedule.get("offset_minutes"))
        if freq:
            return str(freq)
    if agent.get("recurring") is False:
        return "one-off"
    return NONE


# -- views ---------------------------------------------------------------
def agents(data: Dict[str, Any]) -> None:
    items = data.get("agents") if isinstance(data, dict) else data
    items = items or []
    rows = []
    for a in items:
        rows.append([
            style.paint(short_id(_first(a, "id", "agent_id")), "cyan"),
            (_first(a, "name", default="Agent") or "Agent")[:32],
            style.status(_first(a, "status", default="?")),
            describe_schedule(a),
            style.label(rel_ts(_first(a, "last_run_at", "last_run"))),
            _first(a, "run_count", "runs", default=0),
        ])
    table(["ID", "NAME", "STATUS", "SCHEDULE", "LAST RUN", "RUNS"], rows)
    total = data.get("total") if isinstance(data, dict) else None
    if total is not None and total > len(items):
        print("\n" + style.label(
            f"showing {len(items)} of {total}; narrow with --status or page "
            "with --offset"))


def agent_detail(a: Dict[str, Any]) -> None:
    def row(name: str, value: Any) -> None:
        print(f"{style.label(name.ljust(11))}{value}")

    row("id", style.paint(str(_first(a, "id", "agent_id")), "cyan"))
    row("name", _first(a, "name", default="Agent"))
    row("status", style.status(_first(a, "status", default="?")))
    row("schedule", describe_schedule(a))
    if _first(a, "model", default=None) or _model_of(a):
        row("model", _first(a, "model", default=None) or _model_of(a))
    labels = _first(a, "labels", default=None)
    if labels:
        row("labels", ", ".join(labels))
    row("runs", _first(a, "run_count", "runs", default=0))
    row("last run", fmt_ts(_first(a, "last_run_at", "last_run")))
    row("created", fmt_ts(a.get("created_at")))
    prompt = _first(a, "prompt", default=None) or _prompt_of(a)
    if prompt:
        print("\n" + style.label("prompt:"))
        print(textwrap.indent(textwrap.fill(prompt, width=88), "  "))


def _model_of(a: Dict[str, Any]) -> Optional[str]:
    payload = a.get("payload")
    if isinstance(payload, dict):
        cfg = payload.get("config")
        if isinstance(cfg, dict):
            return cfg.get("model")
    return None


def _prompt_of(a: Dict[str, Any]) -> Optional[str]:
    payload = a.get("payload")
    if isinstance(payload, dict):
        return payload.get("prompt")
    return None


def runs(data: Dict[str, Any]) -> None:
    items = data.get("runs") if isinstance(data, dict) else data
    items = items or []
    rows = []
    for r in items:
        rows.append([
            style.paint(short_id(_first(r, "run_id", "id", "task_id"), 12), "cyan"),
            style.status(_first(r, "status", default="?")),
            style.label(fmt_ts(_first(r, "started_at", "created_at"))),
            _duration(r),
        ])
    table(["RUN ID", "STATUS", "STARTED", "DURATION"], rows)
    if isinstance(data, dict) and data.get("has_more"):
        print("\n" + style.label("more runs available; page with --offset"))


def _duration(r: Dict[str, Any]) -> str:
    secs = r.get("duration_seconds")
    if secs is None:
        return NONE
    try:
        secs = float(secs)
    except (TypeError, ValueError):
        return NONE
    if secs < 60:
        return f"{secs:.0f}s"
    return f"{secs / 60:.1f}m"


def run_result(r: Dict[str, Any]) -> None:
    def row(name: str, value: Any) -> None:
        print(f"{style.label(name.ljust(10))}{value}")

    row("run", style.paint(str(_first(r, 'run_id', 'id')), "cyan"))
    row("status", style.status(_first(r, "status", default="?")))
    row("started", fmt_ts(_first(r, "started_at", "created_at")))
    row("finished", fmt_ts(r.get("completed_at")))
    row("duration", _duration(r))
    if r.get("model"):
        row("model", r["model"])
    usage_info = r.get("usage")
    if isinstance(usage_info, dict):
        row("tokens", f"in {usage_info.get('input_tokens', '?')} / "
                      f"out {usage_info.get('output_tokens', '?')} / "
                      f"total {usage_info.get('total_tokens', '?')}")
    error = r.get("error")
    if isinstance(error, dict) and (error.get("message") or error.get("code")):
        print("\n" + style.bad(f"error [{error.get('code', 'error')}]: "
                                f"{error.get('message', '')}"))
    result = r.get("result")
    text = result.get("text") if isinstance(result, dict) else result
    if text:
        print("\n" + style.label("result:"))
        print(textwrap.indent(str(text).strip(), "  "))


def usage(u: Dict[str, Any]) -> None:
    # Label column is 11 wide to line up with `whoami`'s endpoint/credential
    # rows and with `auth status`: these views print next to each other.
    def row(name: str, value: Any) -> None:
        print(f"{style.label(name.ljust(11))}{value}")

    row("plan", style.paint(str(u.get("plan", "?")), "bold"))
    tokens = u.get("tokens")
    if isinstance(tokens, dict):
        if tokens.get("unlimited"):
            row("tokens", f"{tokens.get('used', 0):,} used (unlimited)")
        else:
            row("tokens", f"{tokens.get('used', 0):,} used / "
                          f"{tokens.get('limit', 0):,} limit / "
                          f"{tokens.get('remaining', 0):,} left")
        if tokens.get("resets_at"):
            row("resets", fmt_ts(tokens["resets_at"]))
    research = u.get("research_requests")
    if isinstance(research, dict):
        # The direct research commands draw on this, not on the token quota.
        used = fmt_number(research.get("used")) or "0"
        if research.get("unlimited"):
            line = f"{used} requests used this week (unlimited)"
        else:
            line = (f"{used} used / "
                    f"{fmt_number(research.get('limit')) or '?'} per week / "
                    f"{fmt_number(research.get('remaining')) or '?'} left")
        if research.get("resets_at"):
            line += f" (resets {fmt_ts(research['resets_at'])})"
        row("research", line)
    key = u.get("api_key")
    if isinstance(key, dict):
        row("key", f"{key.get('name', '?')} "
                   f"({key.get('total_requests', 0)} requests)")
    device = u.get("device")
    if isinstance(device, dict):
        scopes = device.get("scopes")
        parts = [str(device.get("label") or "device")]
        if scopes:
            parts.append(f"scopes: {', '.join(scopes)}")
        if device.get("expires_at"):
            parts.append(f"expires {fmt_ts(device['expires_at'])}")
        row("device", " · ".join(parts))


def models(payload: Any) -> None:
    items = payload if isinstance(payload, list) else payload.get("models", [])
    rows = []
    for m in items or []:
        rows.append([
            _first(m, "model_id", "id", default="?"),
            (_first(m, "display_name", "name", default="") or "")[:30],
            _first(m, "model_class", default=NONE),
            # No required_plan means every plan can run it: say so rather
            # than leaving a column of blanks.
            _first(m, "required_plan", default="any") or "any",
            style.paint("★", "yellow") if m.get("is_default") else "",
        ])
    table(["MODEL ID", "NAME", "CLASS", "PLAN", "DEFAULT"], rows)


# ---------------------------------------------------------------------------
# research views
# ---------------------------------------------------------------------------
# The reader is usually a model driving the CLI through a pipe, so these views
# are plain, dense and explicit: exact figures, ISO dates, full transcript ids
# (they are arguments to the next command), and a sentence wherever FN2 has no
# data. Nothing here rounds, abbreviates or infers; arithmetic the server did
# not do is not done here either.
MISSING = "not available"

_SESSIONS = {"amc": "after market close", "bmo": "before market open"}
_OUTCOMES = {"beat": "beat consensus", "miss": "missed consensus",
             "match": "matched consensus"}


def _text(value: Any) -> Optional[str]:
    """A non-empty display string, or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def fmt_number(value: Any, *, signed: bool = False) -> Optional[str]:
    """An exact figure with thousands separators, or None when there is none.

    Never rounds: 12874180000 reads "12,874,180,000" and 0.87 reads "0.87".
    Numeric strings (the API serialises NUMERIC columns that way) keep every
    digit they arrived with.
    """
    if value is None or isinstance(value, bool):
        return None
    positive = False
    if isinstance(value, int):
        out, positive = f"{value:,}", value > 0
    elif isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        if value.is_integer() and abs(value) < 1e15:
            out = f"{int(value):,}"
        else:
            out = f"{value:,}"
        positive = value > 0
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            number = decimal.Decimal(text)
        except decimal.InvalidOperation:
            return text
        if not number.is_finite():
            return text
        out, positive = f"{number:,f}", number > 0
    return f"+{out}" if signed and positive else out


def _day(value: Any) -> Optional[str]:
    """YYYY-MM-DD from an ISO or HTTP-date string; anything else as given."""
    text = _text(value)
    if text is None:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return text


def _session_phrase(value: Any) -> str:
    """bmo / amc in words. Anything else is unknown, and says so: a guessed
    before/after-market is exactly the kind of detail that must not be made up."""
    return _SESSIONS.get(str(value or "").strip().lower(),
                         "before or after market: unknown")


def _fiscal_label(row: Dict[str, Any], *, ending: str = "ended") -> str:
    label = _text(row.get("fiscal_period"))
    year, quarter = row.get("fiscal_year"), row.get("fiscal_quarter")
    names = []
    if label:
        names.append(label)
    if year is not None and quarter is not None:
        names.append(f"fiscal {year} Q{quarter}")
    head = " = ".join(names) if names else f"fiscal quarter label {MISSING}"
    end = _day(row.get("fiscal_date_ending"))
    tail = f"quarter {ending} {end}" if end else f"quarter end date {MISSING}"
    return f"{head}, {tail}"


def _versus_consensus(name: str, block: Any) -> str:
    block = block if isinstance(block, dict) else {}
    actual = fmt_number(block.get("actual"))
    estimate = fmt_number(block.get("estimate"))
    if actual is None and estimate is None:
        return f"    {name:<8} {MISSING} (FN2 holds no actual or consensus)"
    parts = [f"actual {actual or MISSING}", f"consensus {estimate or MISSING}"]
    surprise = fmt_number(block.get("surprise"), signed=True)
    surprise_pct = fmt_number(block.get("surprise_pct"), signed=True)
    if surprise is not None:
        pct = f" ({surprise_pct}%)" if surprise_pct is not None else ""
        parts.append(f"surprise {surprise}{pct}")
    elif surprise_pct is not None:
        parts.append(f"surprise {surprise_pct}%")
    else:
        parts.append(f"surprise {MISSING}")
    outcome = _text(block.get("outcome"))
    parts.append(_OUTCOMES.get(outcome, outcome) if outcome
                 else f"beat/miss {MISSING}")
    return f"    {name:<8} " + " | ".join(parts)


def earnings(data: Dict[str, Any]) -> None:
    symbol = _text(data.get("symbol")) or "?"
    rows = [r for r in (data.get("reported") or []) if isinstance(r, dict)]
    notes = [str(n).strip() for n in (data.get("notes") or []) if _text(n)]

    # Staleness goes FIRST. "The newest quarter FN2 holds" is only "the latest
    # quarter" while the calendar is current, and a reader who misses this
    # line will summarise a years-old report as the company's latest.
    stale = None
    if data.get("possibly_stale"):
        stale = notes[0] if notes else (
            f"The newest result FN2 holds for {symbol} may not be the "
            "company's latest quarter; do not present it as the latest "
            "without saying so.")
        print(style.bad("POSSIBLY STALE: ") + stale)

    as_of = _day(data.get("as_of"))
    head = f"{symbol} earnings" + (f", FN2 data as of {as_of}" if as_of else "")
    if rows:
        plural = "quarter" if len(rows) == 1 else "quarters"
        print(style.head(f"{head}: {len(rows)} reported {plural} FN2 holds, "
                         "newest first"))
    else:
        print(style.head(f"{head}: no reported quarters in FN2's data"))
    print("consensus = analyst consensus from FN2's market-data vendor, NOT "
          "company guidance. EPS is per share; revenue is in whole currency "
          "units (US dollars for US companies).")

    # False only when FN2's transcript lookup failed for this response. A
    # missing call is then "unknown", and must not be reported as "none held".
    calls_checked = data.get("calls_checked") is not False
    for index, row in enumerate(rows, 1):
        report_date = _day(row.get("report_date"))
        when = (f"reported {report_date}, {_session_phrase(row.get('session'))}"
                if report_date else f"report date {MISSING}")
        print(f"\n[{index}] {_fiscal_label(row)} | {when}")
        print(_versus_consensus("EPS", row.get("eps")))
        print(_versus_consensus("revenue", row.get("revenue")))
        call = row.get("call")
        if isinstance(call, dict) and _text(call.get("transcript_id")):
            tid = _text(call.get("transcript_id"))
            held = _day(call.get("call_date")) or f"date {MISSING}"
            print(f"    {'call':<8} held {held} | transcript id {tid}")
        elif calls_checked:
            print(f"    {'call':<8} {MISSING}: FN2 holds no transcript matched "
                  "to this report")
        else:
            print(f"    {'call':<8} not checked: FN2 could not look up "
                  "transcripts for this response, so one may exist. Retry, or "
                  f"list them: fn2 calls {symbol}")

    upcoming = data.get("next")
    print()
    if isinstance(upcoming, dict):
        date = _day(upcoming.get("report_date"))
        status = _text(upcoming.get("date_status"))
        if status == "estimated":
            caveat = "date is a scheduled estimate, not company-confirmed"
        else:
            caveat = f"date status: {status or MISSING}"
        when = (f"{date}, {_session_phrase(upcoming.get('session'))} ({caveat})"
                if date else f"date {MISSING}")
        print(f"next report: {when} | {_fiscal_label(upcoming, ending='ending')}")
        print("    consensus EPS "
              f"{fmt_number(upcoming.get('eps_estimate')) or MISSING} | "
              "consensus revenue "
              f"{fmt_number(upcoming.get('revenue_estimate')) or MISSING}")
    else:
        print(f"next report: {MISSING} (no upcoming report is scheduled in "
              "FN2's data)")

    remaining = [n for n in notes if n != stale]
    if remaining:
        print("\nnotes from FN2:")
        for note in remaining:
            print(f"  - {note}")
    print(f"\nread a call: fn2 transcript {symbol} --id <transcript id> | "
          "search inside it: fn2 search \"QUERY\" --call <transcript id> | "
          f"filed margins: fn2 financials {symbol} --quarterly")


def calls(data: Dict[str, Any], *, limit: Optional[int] = None) -> None:
    symbol = _text(data.get("symbol")) or "?"
    items = [c for c in (data.get("calls") or []) if isinstance(c, dict)]
    more = ""
    if limit is not None and len(items) >= limit:
        more = f" (limit {limit} reached; older calls may exist, raise --limit)"
    print(style.head(f"{symbol} earnings calls FN2 holds text for: "
                     f"{len(items)} shown, newest first{more}"))
    rows = []
    for call in items:
        year, quarter = call.get("fiscal_year"), call.get("fiscal_quarter")
        fiscal = (f"{year} Q{quarter}" if year is not None and quarter is not None
                  else MISSING)
        rows.append([
            _day(call.get("call_date")) or MISSING,
            fiscal,
            fmt_number(call.get("characters")) or MISSING,
            _text(call.get("transcript_id")) or MISSING,
        ])
    table(["CALL DATE", "FISCAL (TRANSCRIPT LABEL)", "CHARACTERS",
           "TRANSCRIPT ID"], rows)
    note = _text(data.get("coverage_note"))
    if note:
        print(f"\nnote from FN2: {note}")
    print("note: the fiscal label is the transcript's own and can differ from "
          "`fn2 earnings` when a company's fiscal year is offset; match a call "
          "to a report by date, or use the transcript id `fn2 earnings` prints.")
    print(f"read one:          fn2 transcript {symbol} --id <TRANSCRIPT ID>")
    print("search inside one: fn2 search \"QUERY\" --call <TRANSCRIPT ID>")


def transcript(data: Dict[str, Any], *, requested_symbol: Optional[str] = None,
               max_chars: Optional[int] = None) -> None:
    tid = _text(data.get("transcript_id")) or "?"
    symbol = _text(data.get("symbol")) or requested_symbol or "?"
    text = str(data.get("text") or "")
    offset = data.get("offset") if isinstance(data.get("offset"), int) else 0
    returned = (data.get("returned") if isinstance(data.get("returned"), int)
                else len(text))
    total = data.get("characters") if isinstance(data.get("characters"), int) else None
    next_offset = data.get("next_offset")

    held = _day(data.get("call_date"))
    year, quarter = data.get("fiscal_year"), data.get("fiscal_quarter")
    fiscal = (f"fiscal {year} Q{quarter} (the transcript's own label)"
              if year is not None and quarter is not None
              else f"fiscal period {MISSING}")
    print(style.head(f"{symbol} earnings call | "
                     f"{'held ' + held if held else 'call date ' + MISSING} | "
                     f"{fiscal} | transcript id {tid}"))
    if requested_symbol and _text(data.get("symbol")) and \
            requested_symbol.upper() != str(data.get("symbol")).upper():
        print(f"note: this transcript belongs to {data.get('symbol')}, not the "
              f"{requested_symbol} you named.")

    # The paging line is printed above AND below the text: if a harness cuts
    # the output, the top copy survives and the reader still knows the call
    # is not finished.
    if isinstance(next_offset, int):
        size = f" --max-chars {max_chars}" if max_chars else ""
        paging = (f"next page: fn2 transcript {symbol} --id {tid} "
                  f"--offset {next_offset}{size}")
    else:
        paging = ("end of call: this page reaches the end of the transcript; "
                  "there is no next page.")
    of_total = f" of {total:,}" if total is not None else ""
    if returned <= 0:
        print(f"no text at offset {offset:,}: the call has "
              f"{fmt_number(total) or 'an unknown number of'} characters. "
              f"Start over with: fn2 transcript {symbol} --id {tid}")
        return
    print(f"characters {offset:,} to {offset + returned:,}{of_total}, "
          "in speaker order (\"Name: paragraph\" blocks)")
    print(paging)
    print("----- call text begins (verbatim) -----")
    print(text.strip("\n"))
    print("----- call text ends -----")
    print(paging)


def _matched_words(hit: Dict[str, Any]) -> Optional[List[str]]:
    """The query words FN2 found in a hit, or None when it found none.

    `highlights` holds the fragments a keyword match produced, with the
    matched words wrapped in <em>. It is null for a hit that matched by
    meaning only: the nearest passage to the query, which the search returns
    even when the call never raised the topic.
    """
    highlights = hit.get("highlights")
    if not highlights or not isinstance(highlights, (list, tuple)):
        return None
    words: List[str] = []
    for fragment in highlights:
        for word in re.findall(r"<em>(.*?)</em>", str(fragment)):
            word = word.strip()
            if word and word.lower() not in (w.lower() for w in words):
                words.append(word)
    return words


def transcript_search(data: Dict[str, Any], *, limit: Optional[int] = None,
                      requested_symbol: Optional[str] = None) -> None:
    hits = [h for h in (data.get("results") or []) if isinstance(h, dict)]
    query = _text(data.get("query")) or ""
    filters = []
    if _text(data.get("symbol")):
        filters.append(f"symbol {data['symbol']}")
    if _text(data.get("after")):
        filters.append(f"calls on or after {data['after']}")
    if _text(data.get("transcript_id")):
        filters.append(f"inside transcript {data['transcript_id']}")
    scope = " | ".join(filters) if filters else "none (all companies, all dates)"

    if hits:
        more = ""
        if limit is not None and len(hits) >= limit:
            more = f" (limit {limit} reached; raise --limit for more)"
        plural = "hit" if len(hits) == 1 else "hits"
        print(style.head(f"transcript search \"{query}\": {len(hits)} {plural}"
                         f"{more}, ranked by relevance, NOT by date"))
    else:
        print(style.head(f"transcript search \"{query}\": no matching call "
                         "text in FN2"))
    print(f"filters: {scope}")
    if requested_symbol and not _text(data.get("symbol")):
        print(f"WARNING: FN2 did not recognise {requested_symbol!r} as a "
              "ticker, so this search was NOT limited to one company.")
    matched = [_matched_words(hit) for hit in hits]
    by_meaning = sum(1 for words in matched if words is None)
    if hits:
        print("each hit is one speaker turn, quoted verbatim from the call it "
              "names.")
    if hits and by_meaning == len(hits):
        print(f"CAUTION: none of these {len(hits)} hits contains your query "
              "words; all matched by meaning only. The nearest passages are "
              "returned even when a topic was never raised, so read each one "
              "before citing it. \"Not discussed\" can be the right answer.")
    elif by_meaning:
        print(f"CAUTION: {by_meaning} of {len(hits)} hits matched by meaning "
              "only (marked below) and contain none of your query words. Read "
              "those before citing them; they may be about something else.")
    for index, hit in enumerate(hits, 1):
        company = _text(hit.get("company_name"))
        who = _text(hit.get("symbol")) or f"symbol {MISSING}"
        if company:
            who += f" ({company})"
        held = _day(hit.get("call_date"))
        year, quarter = hit.get("fiscal_year"), hit.get("fiscal_quarter")
        call = f"call {held}" if held else f"call date {MISSING}"
        if year is not None and quarter is not None:
            call += f", fiscal {year} Q{quarter} (transcript label)"
        speaker = _text(hit.get("speaker")) or f"speaker {MISSING}"
        where = f"transcript {_text(hit.get('transcript_id')) or MISSING}"
        if hit.get("block_id") is not None:
            where += f" block {hit.get('block_id')}"
        words = matched[index - 1]
        if words is None:
            how = "matched by meaning only"
        elif words:
            how = "matched your words: " + ", ".join(words)
        else:
            how = "matched your words"
        print(f"\n[{index}] {who} | {call} | {speaker} | {where} | {how}")
        print(textwrap.indent(str(hit.get("text") or "").strip("\n")
                              or f"(text {MISSING})", "    "))
    note = _text(data.get("coverage_note"))
    if note:
        print(f"\nnote from FN2: {note}")


# -- financials ----------------------------------------------------------
# (key, label) in statement order. A row prints when FN2 returned the key for
# at least one period; keys FN2 adds later are appended under their own name
# rather than dropped.
_FINANCIAL_ROWS: Tuple[Tuple[str, str], ...] = (
    ("revenue", "revenue"),
    ("revenue_growth", "revenue growth YoY %"),
    ("gross_profit", "gross profit"),
    ("gross_margin", "gross margin %"),
    ("operating_income", "operating income"),
    ("operating_margin", "operating margin %"),
    ("ebitda", "EBITDA"),
    ("ebitda_margin", "EBITDA margin %"),
    ("net_income", "net income"),
    ("net_margin", "net margin %"),
    ("diluted_eps", "diluted EPS"),
    ("diluted_eps_growth", "diluted EPS growth YoY %"),
    ("operating_cash_flow", "operating cash flow"),
    ("capex", "capex"),
    ("free_cash_flow", "free cash flow"),
    ("free_cash_flow_margin", "free cash flow margin %"),
    ("cash", "cash and equivalents"),
    ("short_term_debt", "short-term debt"),
    ("long_term_debt", "long-term debt"),
    ("total_debt", "total debt"),
    ("market_cap", "market cap"),
    ("enterprise_value", "enterprise value"),
)
_VARIANT_WORDS = {
    "annual": "annual (fiscal years, from 10-K filings)",
    "quarterly": "quarterly (single quarters, from 10-Q filings)",
    "ttm": "trailing twelve months (four consecutive 10-Q quarters summed)",
}


def financials(data: Dict[str, Any]) -> None:
    symbol = _text(data.get("ticker")) or _text(data.get("symbol")) or "?"
    variant = _text(data.get("variant")) or "?"
    periods = [p for p in (data.get("periods") or []) if isinstance(p, dict)]
    # Newest first, whatever order the API used, so column 1 is always the
    # latest period this source has.
    periods.sort(key=lambda p: str(p.get("period_end") or ""), reverse=True)
    unavailable = data.get("unavailable") if isinstance(data.get("unavailable"), dict) else {}

    plural = "period" if len(periods) == 1 else "periods"
    print(style.head(f"{symbol} financials from SEC filings: "
                     f"{_VARIANT_WORDS.get(variant, variant)}, {len(periods)} "
                     f"{plural}, newest first (left to right)"))
    if not periods:
        print(f"no periods {MISSING} for this view in FN2's filing data.")
        return
    print("amounts are whole currency units as filed (US dollars for US "
          "filers), not thousands or millions; % rows are percentages; EPS is "
          "per diluted share.")
    print("\"-\" means FN2's filing data has no value for that item in that "
          "period. It does not mean zero.")
    if variant in ("quarterly", "ttm"):
        print("a fiscal fourth quarter is reported on the annual 10-K, not a "
              "10-Q, so it has no column of its own here; see --annual.")
    print()

    def values_of(period: Dict[str, Any]) -> Dict[str, Any]:
        values = period.get("values")
        return values if isinstance(values, dict) else {}

    def fiscal(period: Dict[str, Any]) -> str:
        year, part = period.get("fiscal_year"), _text(period.get("fiscal_period"))
        if year is not None and part:
            return f"FY{year} {part}"
        if year is not None:
            return f"FY{year}"
        return part or "-"

    grid: List[List[str]] = [
        ["period end"] + [_day(p.get("period_end")) or "-" for p in periods],
        ["fiscal period"] + [fiscal(p) for p in periods],
        ["form"] + [_text(p.get("form_type")) or "-" for p in periods],
        ["filed"] + [_day(p.get("filing_date")) or "-" for p in periods],
    ]
    present = set()
    for period in periods:
        present.update(values_of(period).keys())
    known = [key for key, _ in _FINANCIAL_ROWS]
    labels = dict(_FINANCIAL_ROWS)
    ordered = [k for k in known if k in present] + \
        sorted(k for k in present if k not in labels)
    for key in ordered:
        cells = [fmt_number(values_of(p).get(key)) for p in periods]
        if key in unavailable and not any(cells):
            continue  # reported once, below, with FN2's reason
        grid.append([labels.get(key, key)] + [c or "-" for c in cells])

    widths = [max(len(row[i]) for row in grid) for i in range(len(periods) + 1)]
    for row in grid:
        line = row[0].ljust(widths[0]) + "".join(
            "  " + cell.rjust(widths[i]) for i, cell in enumerate(row[1:], 1))
        print(line.rstrip())

    for period in periods:
        quality = period.get("quality") if isinstance(period.get("quality"), dict) else {}
        disputed = quality.get("cross_check_disagreements") or []
        if disputed:
            print(f"\ndata-quality flag, period ending "
                  f"{_day(period.get('period_end')) or '?'}: FN2's derived "
                  "figure disagrees with the filing index for "
                  f"{', '.join(str(d) for d in disputed)}; treat with care.")
        withheld = quality.get("growth_withheld")
        if isinstance(withheld, dict):
            # e.g. EPS growth across a stock split: filed EPS is not restated,
            # so FN2 gives no figure rather than a false collapse.
            for key, reason in withheld.items():
                print(f"\nwithheld by FN2, period ending "
                      f"{_day(period.get('period_end')) or '?'}: "
                      f"{labels.get(key, key)}. Reason: {reason}. Do not "
                      "compute it from the per-share rows.")
    if unavailable:
        reasons = "; ".join(f"{labels.get(k, k)} ({v})"
                            for k, v in unavailable.items())
        print(f"\n{MISSING} from this source: {reasons}")


# -- prices --------------------------------------------------------------
def _market_zone() -> Tuple[Any, str]:
    """US Eastern when the platform has the zone data, otherwise UTC. The
    column header names whichever was used."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York"), "ET"
    except Exception:
        return dt.timezone.utc, "UTC"


def price(data: Dict[str, Any]) -> None:
    symbol = _text(data.get("symbol")) or "?"
    quote = data.get("quote") if isinstance(data.get("quote"), dict) else {}
    regular = quote.get("regular") if isinstance(quote.get("regular"), dict) else {}
    extended = quote.get("extended")
    session = (_text(quote.get("session")) or MISSING).replace("_", " ")
    source = _text(quote.get("source")) or MISSING
    print(style.head(f"{symbol} quote | market session now: {session} | "
                     f"source: {source} | delayed market data, not a "
                     "real-time trading feed"))
    change = fmt_number(regular.get("change"), signed=True)
    change_pct = fmt_number(regular.get("change_pct"), signed=True)
    print(f"regular   price {fmt_number(regular.get('price')) or MISSING} | "
          f"change {change or MISSING}"
          f"{' (' + change_pct + '%)' if change_pct else ''} | "
          f"previous close {fmt_number(regular.get('previous_close')) or MISSING}"
          f" | as of {_text(regular.get('as_of')) or MISSING}")
    if isinstance(extended, dict):
        versus = fmt_number(extended.get("change_vs_close_pct"), signed=True)
        print(f"extended  price {fmt_number(extended.get('price')) or MISSING} | "
              f"{versus + '%' if versus else 'change ' + MISSING} vs the "
              f"regular price above | as of "
              f"{_text(extended.get('as_of')) or MISSING}")
    else:
        print(f"extended  {MISSING} (no extended-hours print, or the regular "
              "session is open)")

    history = data.get("history")
    if not isinstance(history, dict):
        print("history   not requested (add --range 1D, 5D, 1M, 3M, 6M, YTD, "
              "1Y, 5Y or MAX)")
        return
    span = _text(history.get("range")) or "?"
    points = [p for p in (history.get("points") or [])
              if isinstance(p, (list, tuple))]
    if not points:
        note = _text(history.get("note")) or "FN2 returned no bars."
        print(f"\nhistory {span}: {MISSING}. {note}")
        return
    names = history.get("point_format") or ["timestamp_ms", "close", "volume",
                                            "open", "high", "low"]
    bars = [dict(zip(names, point)) for point in points]
    zone, zone_name = _market_zone()
    stamps: List[Optional[dt.datetime]] = []
    for bar in bars:
        try:
            stamps.append(dt.datetime.fromtimestamp(
                float(bar.get("timestamp_ms")) / 1000.0, tz=zone))
        except (TypeError, ValueError, OverflowError, OSError):
            stamps.append(None)
    # Daily and coarser bars all carry one time of day (midnight Eastern);
    # only bars within a day need their time shown.
    clock = {(s.hour, s.minute) for s in stamps if s is not None}
    intraday = len(clock) > 1 or (len(bars) == 1 and clock not in (set(), {(0, 0)}))
    plural = "bar" if len(bars) == 1 else "bars"
    print(f"\nhistory {span}: {len(bars)} {plural}, oldest first"
          + (f", times in {zone_name}" if intraday else ""))
    if history.get("truncated"):
        print(f"note: FN2 returned only the most recent {len(bars)} bars of "
              "this range; older bars were left out.")
    rows = []
    for bar, stamp in zip(bars, stamps):
        if stamp is None:
            when = _text(bar.get("timestamp_ms")) or MISSING
        else:
            when = stamp.strftime("%Y-%m-%d %H:%M" if intraday else "%Y-%m-%d")
        rows.append([when] + [fmt_number(bar.get(k)) or "-"
                              for k in ("open", "high", "low", "close", "volume")])
    table([f"TIME ({zone_name})" if intraday else "DATE",
           "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"], rows)


# -- FRED ----------------------------------------------------------------
def fred(data: Dict[str, Any], *, limit: Optional[int] = None) -> None:
    if "observations" not in data and "series" in data:
        _fred_catalog(data)
        return
    series_id = _text(data.get("series_id")) or "?"
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    title = _text(meta.get("title"))
    print(style.head(f"FRED {series_id}" + (f" | {title}" if title else "")))
    if meta:
        facts = []
        for name, keys in (("frequency", ("frequency", "frequency_short")),
                           ("units", ("units", "units_short")),
                           ("seasonal adjustment", ("seasonal_adjustment_short",)),
                           ("category", ("category",))):
            value = _first(meta, *keys)
            if value is not None:
                facts.append(f"{name}: {value}")
        if facts:
            print(" | ".join(facts))
        start, end = _day(meta.get("observation_start")), _day(meta.get("observation_end"))
        updated = _day(meta.get("last_updated_fred"))
        if start or end or updated:
            print(f"FRED's own range: {start or MISSING} to {end or MISSING}"
                  + (f" | FRED last updated {updated}" if updated else ""))
    else:
        print(f"series description {MISSING} in FN2's catalog.")

    observations = [o for o in (data.get("observations") or [])
                    if isinstance(o, dict)]
    if not observations:
        print(f"observations: {MISSING} (FN2 holds none for this series).")
        return
    more = ""
    if limit is not None and len(observations) >= limit:
        more = (f" (limit {limit}: the most recent; raise --limit for "
                "earlier dates)")
    plural = "observation" if len(observations) == 1 else "observations"
    print(f"\n{len(observations)} {plural}, oldest first{more}")
    changes = [(key, head) for key, head in (("yoy_pct", "YOY %"),
                                             ("mom_pct", "MOM %"),
                                             ("qoq_pct", "QOQ %"))
               if any(o.get(key) is not None for o in observations)]
    rows = [[_day(o.get("date")) or MISSING, fmt_number(o.get("value")) or "-"]
            + [fmt_number(o.get(key), signed=True) or "-" for key, _ in changes]
            for o in observations]
    table(["DATE", "VALUE"] + [head for _, head in changes], rows)
    absent = [head for key, head in (("yoy_pct", "YOY %"), ("mom_pct", "MOM %"),
                                     ("qoq_pct", "QOQ %"))
              if (key, head) not in changes]
    if absent:
        print(f"\n{MISSING} for these observations: {', '.join(absent)} "
              "(change columns FN2 has no figures for are left out).")


def _fred_catalog(data: Dict[str, Any]) -> None:
    items = [s for s in (data.get("series") or []) if isinstance(s, dict)]
    print(style.head(f"FRED series FN2 tracks: {len(items)} listed. "
                     "Observations for one: fn2 fred <SERIES ID>"))
    rows = []
    for item in items:
        rows.append([
            _text(item.get("series_id")) or MISSING,
            _text(item.get("title")) or "-",
            _text(item.get("category")) or "-",
            _text(_first(item, "frequency_short", "frequency")) or "-",
            _text(_first(item, "units_short", "units")) or "-",
            _day(item.get("observation_start")) or "-",
            _day(item.get("observation_end")) or "-",
        ])
    table(["SERIES ID", "TITLE", "CATEGORY", "FREQ", "UNITS", "FROM", "TO"], rows)
    if len(items) >= 200:
        print("\nnote: FN2 lists at most 200 series here; a series id not "
              "shown may still exist, so try it directly.")


# -- recall --------------------------------------------------------------
def recall(data: Dict[str, Any], *, limit: Optional[int] = None,
           tag: Optional[str] = None) -> None:
    memories = [m for m in (data.get("memories") or []) if isinstance(m, dict)]
    filters = []
    if _text(data.get("query")):
        filters.append(f"query \"{data['query']}\"")
    if _text(tag):
        filters.append(f"tag {tag}")
    if _text(data.get("agent_id")):
        filters.append(f"agent {data['agent_id']}")
    scope = ", ".join(filters) if filters else "everything saved on this account"
    if not memories:
        print(style.head(f"saved memory ({scope}): nothing found"))
        print("FN2 agents save notes as they run. Nothing saved matches, or "
              "nothing has been saved yet; this is not an error.")
        return
    more = ""
    if limit is not None and len(memories) >= limit:
        more = f" (limit {limit} reached; raise --limit for more)"
    plural = "note" if len(memories) == 1 else "notes"
    print(style.head(f"saved memory ({scope}): {len(memories)} {plural}, "
                     f"most recently updated first{more}"))
    for index, memory in enumerate(memories, 1):
        parts = [f"tag {_text(memory.get('tag')) or MISSING}"]
        if _text(memory.get("item_key")):
            parts.append(f"key {memory['item_key']}")
        agent = _text(memory.get("agent_name"))
        agent_id = _text(memory.get("agent_id"))
        if agent or agent_id:
            parts.append("agent " + (f"\"{agent}\" " if agent else "")
                         + (f"({short_id(agent_id)})" if agent_id else ""))
        parts.append(f"updated {fmt_ts(memory.get('updated_at'))}")
        print(f"\n[{index}] " + " | ".join(p.rstrip() for p in parts))
        print(textwrap.indent(str(memory.get("content") or "").strip("\n")
                              or f"(content {MISSING})", "    "))
