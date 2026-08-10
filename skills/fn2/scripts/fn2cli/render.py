"""Human-readable and JSON rendering. Presentation only, no network, no logic.

Every view degrades gracefully: the FN2 AI API may add or rename fields, so we
read defensively and never crash on a missing key.

Colour goes through :mod:`style`, which is a no-op unless stdout is a terminal,
so piped and ``--json`` output stays plain text.
"""

from __future__ import annotations

import datetime as dt
import json
import textwrap
from typing import Any, Dict, List, Optional, Sequence

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
