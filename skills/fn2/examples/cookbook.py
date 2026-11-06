#!/usr/bin/env python3
"""Preview reproducible research prompts; execute only with --execute.

Uses the bundled CLI unchanged for auth, origin pinning, and API requests.
Preview never resolves credentials, opens a connection, or creates an agent.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
from string import Template
import sys

EXAMPLES = Path(__file__).resolve().parent
sys.path.insert(0, str(EXAMPLES.parent / "scripts"))
from fn2cli import cli, schedule  # noqa: E402


def ticker(value):
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", value):
        raise argparse.ArgumentTypeError("use an exchange ticker, for example IBM or BRK.B")
    return value


def date(value):
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("use a valid YYYY-MM-DD date") from None


def period(value):
    value = value.strip()
    if not value or len(value) > 80 or any(ord(c) < 32 for c in value):
        raise argparse.ArgumentTypeError("use a short fiscal period, for example FY2025 Q3")
    return value


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="recipe", required=True)
    for recipe in ("earnings", "reconcile", "watchlist"):
        s = sub.add_parser(recipe)
        s.add_argument("--execute", action="store_true",
                       help="create an agent; otherwise print an offline preview")
        s.add_argument("--model", help="optional model ID from the authenticated fn2 models command")
        if recipe == "watchlist":
            s.add_argument("--tickers", type=ticker, nargs="+", required=True)
            s.add_argument("--schedule", action="store_true",
                           help="repeat before market open instead of running once now")
            s.add_argument("--ends", type=date, help="required with --schedule; within the next 31 days")
        else:
            s.add_argument("--ticker", type=ticker, required=True)
            s.add_argument("--as-of", type=date, required=True,
                           help="research cutoff date; not a point-in-time data guarantee")
            if recipe == "earnings":
                s.add_argument("--earlier", type=period, required=True)
                s.add_argument("--later", type=period, required=True)
            else:
                s.add_argument("--period", type=period, required=True)
    return p


def build_plan(args, today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    values = vars(args).copy()
    scheduled = args.recipe == "watchlist" and args.schedule
    if args.recipe == "watchlist":
        values["tickers"] = ", ".join(dict.fromkeys(args.tickers))
        if len(set(args.tickers)) > 10:
            raise ValueError("keep the starter watchlist to 10 tickers or fewer")
        if scheduled and (not args.ends or not today < args.ends <= today + dt.timedelta(days=31)):
            raise ValueError("--schedule requires --ends after today's UTC date, within 31 days")
        if args.ends and not scheduled:
            raise ValueError("--ends applies only with --schedule")
        name = "Cookbook watchlist: " + values["tickers"]
    else:
        if args.as_of > today:
            raise ValueError("--as-of must not be in the future")
        if args.recipe == "earnings" and args.earlier.casefold() == args.later.casefold():
            raise ValueError("choose two different fiscal periods")
        name = "Cookbook " + args.recipe + ": " + args.ticker
    common = (EXAMPLES / "prompts" / "evidence.md").read_text(encoding="utf-8")
    template = (EXAMPLES / "prompts" / (args.recipe + ".md")).read_text(encoding="utf-8")
    prompt = Template(template).substitute(values) + "\n" + common
    argv = ["--json", "start", prompt, "--name", name, "--label", "cookbook:" + args.recipe]
    if args.model:
        argv += ["--model", args.model]
    cadence = None
    if scheduled:
        argv += ["--when", "before market open", "--tz", "America/New_York", "--ends", str(args.ends)]
        cadence = dict(schedule.parse_when("before market open").payload, ends_at=str(args.ends))
    # Validate against the real CLI parser before a user can execute the plan.
    cli.build_parser().parse_args(argv)
    return {"preview_only": not args.execute, "recipe": args.recipe,
            "helper": str(EXAMPLES.parent / "scripts" / "fn2"),
            "cli_argv": argv, "schedule": cadence,
            "creates": "one recurring agent" if scheduled else "one agent running once now",
            "delivery": "web app and CLI; no email delivery requested"}


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        plan = build_plan(args)
    except ValueError as exc:
        p.error(str(exc))
    if not args.execute:
        print(json.dumps(plan, indent=2))
        return 0
    # JSON is the creation receipt, not a completed answer. Never retry creates.
    return cli.main(plan["cli_argv"])


if __name__ == "__main__":
    raise SystemExit(main())
