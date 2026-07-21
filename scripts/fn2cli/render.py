"""Human-readable and JSON rendering. Presentation only — no network, no logic.

Every view degrades gracefully: the fn2 API may add or rename fields, so we read
defensively and never crash on a missing key.
"""

from __future__ import annotations

import datetime as dt
import json
import textwrap
from typing import Any, Dict, List, Optional, Sequence


def emit_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=False, default=str))


def _first(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if isinstance(d, dict) and d.get(key) not in (None, ""):
            return d[key]
    return default


def short_id(value: Any, width: int = 8) -> str:
    text = str(value or "")
    return text[:width] if text else "—"


def fmt_ts(value: Any) -> str:
    if not value:
        return "—"
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
            widths[i] = max(widths[i], len(cell))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(cols))
    print(line.rstrip())
    print("  ".join("-" * widths[i] for i in range(len(cols))))
    for cells in text_rows:
        print("  ".join(cells[i].ljust(widths[i]) for i in range(len(cells))).rstrip())


def describe_schedule(agent: Dict[str, Any]) -> str:
    schedule = agent.get("schedule")
    if isinstance(schedule, dict):
        if schedule.get("run_at"):
            return f"once @ {fmt_ts(schedule['run_at'])}"
        freq = schedule.get("frequency")
        cron = schedule.get("cron")
        if freq == "custom" and cron:
            return f"cron {cron}"
        if freq:
            return str(freq)
    if agent.get("recurring") is False:
        return "one-off"
    return "—"


# -- views ---------------------------------------------------------------
def agents(data: Dict[str, Any]) -> None:
    items = data.get("agents") if isinstance(data, dict) else data
    items = items or []
    rows = []
    for a in items:
        rows.append([
            short_id(_first(a, "id", "agent_id")),
            (_first(a, "name", default="Agent") or "Agent")[:32],
            _first(a, "status", default="?"),
            describe_schedule(a),
            rel_ts(_first(a, "last_run_at", "last_run")),
            _first(a, "run_count", "runs", default=0),
        ])
    table(["ID", "NAME", "STATUS", "SCHEDULE", "LAST RUN", "RUNS"], rows)
    total = data.get("total") if isinstance(data, dict) else None
    if total is not None and total > len(items):
        print(f"\nshowing {len(items)} of {total} — narrow with --status or page with --offset")


def agent_detail(a: Dict[str, Any]) -> None:
    print(f"id         {_first(a, 'id', 'agent_id')}")
    print(f"name       {_first(a, 'name', default='Agent')}")
    print(f"status     {_first(a, 'status', default='?')}")
    print(f"schedule   {describe_schedule(a)}")
    if _first(a, "model", default=None) or _model_of(a):
        print(f"model      {_first(a, 'model', default=None) or _model_of(a)}")
    labels = _first(a, "labels", default=None)
    if labels:
        print(f"labels     {', '.join(labels)}")
    print(f"runs       {_first(a, 'run_count', 'runs', default=0)}")
    print(f"last run   {fmt_ts(_first(a, 'last_run_at', 'last_run'))}")
    print(f"created    {fmt_ts(a.get('created_at'))}")
    prompt = _first(a, "prompt", default=None) or _prompt_of(a)
    if prompt:
        print("\nprompt:")
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
            short_id(_first(r, "run_id", "id", "task_id"), 12),
            _first(r, "status", default="?"),
            fmt_ts(_first(r, "started_at", "created_at")),
            _duration(r),
        ])
    table(["RUN ID", "STATUS", "STARTED", "DURATION"], rows)
    if isinstance(data, dict) and data.get("has_more"):
        print("\nmore runs available — page with --offset")


def _duration(r: Dict[str, Any]) -> str:
    secs = r.get("duration_seconds")
    if secs is None:
        return "—"
    try:
        secs = float(secs)
    except (TypeError, ValueError):
        return "—"
    if secs < 60:
        return f"{secs:.0f}s"
    return f"{secs / 60:.1f}m"


def run_result(r: Dict[str, Any]) -> None:
    print(f"run       {_first(r, 'run_id', 'id')}")
    print(f"status    {_first(r, 'status', default='?')}")
    print(f"started   {fmt_ts(_first(r, 'started_at', 'created_at'))}")
    print(f"finished  {fmt_ts(r.get('completed_at'))}")
    print(f"duration  {_duration(r)}")
    if r.get("model"):
        print(f"model     {r['model']}")
    usage = r.get("usage")
    if isinstance(usage, dict):
        print(f"tokens    in {usage.get('input_tokens', '?')} / "
              f"out {usage.get('output_tokens', '?')} / "
              f"total {usage.get('total_tokens', '?')}")
    error = r.get("error")
    if isinstance(error, dict) and (error.get("message") or error.get("code")):
        print(f"\nerror [{error.get('code', 'error')}]: {error.get('message', '')}")
    result = r.get("result")
    text = result.get("text") if isinstance(result, dict) else result
    if text:
        print("\nresult:")
        print(textwrap.indent(str(text).strip(), "  "))


def usage(u: Dict[str, Any]) -> None:
    print(f"plan      {u.get('plan', '?')}")
    tokens = u.get("tokens")
    if isinstance(tokens, dict):
        if tokens.get("unlimited"):
            print(f"tokens    {tokens.get('used', 0):,} used (unlimited)")
        else:
            print(f"tokens    {tokens.get('used', 0):,} used / "
                  f"{tokens.get('limit', 0):,} limit / "
                  f"{tokens.get('remaining', 0):,} left")
        if tokens.get("resets_at"):
            print(f"resets    {fmt_ts(tokens['resets_at'])}")
    key = u.get("api_key")
    if isinstance(key, dict):
        print(f"key       {key.get('name', '?')} "
              f"({key.get('total_requests', 0)} requests)")


def models(payload: Any) -> None:
    items = payload if isinstance(payload, list) else payload.get("models", [])
    rows = []
    for m in items or []:
        rows.append([
            _first(m, "model_id", "id", default="?"),
            (_first(m, "display_name", "name", default="") or "")[:30],
            _first(m, "model_class", default="—"),
            _first(m, "required_plan", default="") or "",
            "★" if m.get("is_default") else "",
        ])
    table(["MODEL ID", "NAME", "CLASS", "PLAN", "DEFAULT"], rows)
