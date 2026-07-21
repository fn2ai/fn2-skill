"""Command-line surface for the fn2 agents API.

Verbs map onto the three things the skill promises: start agents, see their
status, and schedule them.

    login / logout / whoami / models      account & onboarding
    start / agents / status               create and inspect
    run / runs / result                   trigger and read outcomes
    pause / resume / schedule / delete    manage lifecycle
"""

from __future__ import annotations

import argparse
import dataclasses
import getpass
import sys
import urllib.parse
from typing import List, Optional

from . import __version__, api, config, render, schedule
from .client import ApiError, AuthError, Client


# ---------------------------------------------------------------------------
# context helpers
# ---------------------------------------------------------------------------
def _settings(args: argparse.Namespace) -> config.Settings:
    settings = config.resolve()
    if getattr(args, "base_url", None):
        settings = dataclasses.replace(settings, base_url=args.base_url.rstrip("/"))
    return settings


def _client(args: argparse.Namespace, *, require_auth: bool = True) -> Client:
    settings = _settings(args)
    if require_auth and not settings.authenticated:
        raise SystemExit(
            "not signed in. Run `fn2 login` to connect your fn2 account "
            f"({settings.onboard_url})."
        )
    return Client(settings.base_url, settings.api_key)


def _out(args: argparse.Namespace, obj, view) -> None:
    """Emit JSON when --json is set, otherwise the human view."""
    if getattr(args, "json", False):
        render.emit_json(obj)
    else:
        view(obj)


# ---------------------------------------------------------------------------
# account / onboarding
# ---------------------------------------------------------------------------
def cmd_login(args: argparse.Namespace) -> int:
    settings = _settings(args)
    token = (args.token or "").strip()

    if not token:
        link = settings.onboard_url
        if args.email:
            link = f"{link}?{urllib.parse.urlencode({'email': args.email})}"
        print("Connect your fn2 account in two steps:\n")
        print(f"  1. Open {link}")
        print("     Sign up / sign in (we email you a link to confirm), then")
        print("     create an API key with the 'agents' scope.")
        print("  2. Paste it back here:\n")
        print("       fn2 login --token fn2_xxxxxxxxxxxxxxxxxxxx\n")
        print("The key is stored at "
              f"{config.credentials_path()} with 0600 permissions.")
        if sys.stdin.isatty():
            try:
                token = getpass.getpass("fn2 API key (or Enter to cancel): ").strip()
            except (EOFError, KeyboardInterrupt):
                token = ""
        if not token:
            return 2

    if not config.looks_like_key(token):
        print(f"error: that does not look like an fn2 key (expected '{config.KEY_PREFIX}…').",
              file=sys.stderr)
        return 1

    # Validate before persisting so we never store a dud.
    probe = Client(settings.base_url, token)
    try:
        info = api.usage(probe)
    except AuthError:
        print("error: fn2 rejected that key. Create a fresh one and try again.",
              file=sys.stderr)
        return 1

    path = config.save_token(token, settings.base_url)
    print(f"\n✓ signed in — key {config.mask(token)} saved to {path}")
    render.usage(info)
    return 0


def cmd_logout(args: argparse.Namespace) -> int:
    if config.clear_token():
        print("signed out — stored key removed.")
    else:
        print("no stored key to remove.")
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if not settings.authenticated:
        print(f"not signed in. Run `fn2 login` ({settings.onboard_url}).")
        return 2
    client = Client(settings.base_url, settings.api_key)
    info = api.usage(client)
    if getattr(args, "json", False):
        render.emit_json(info)
        return 0
    print(f"endpoint  {settings.base_url}")
    print(f"key       {config.mask(settings.api_key)} (from {settings.source})")
    render.usage(info)
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    client = _client(args)
    _out(args, api.list_models(client), render.models)
    return 0


# ---------------------------------------------------------------------------
# create / inspect
# ---------------------------------------------------------------------------
def cmd_start(args: argparse.Namespace) -> int:
    client = _client(args)
    sched = schedule.parse_when(args.when, timezone=args.tz)
    payload = sched.payload
    if payload is not None and args.ends and sched.kind == "recurring":
        payload = {**payload, "ends_at": args.ends}

    agent = api.create_agent(
        client, prompt=args.prompt, name=args.name, model=args.model,
        labels=args.label or None, schedule=payload,
    )
    if getattr(args, "json", False):
        render.emit_json(agent)
        return 0

    agent_id = agent.get("id") or agent.get("agent_id")
    print(f"✓ agent created — {agent_id}")
    print(f"  cadence: {sched.summary}")
    if sched.kind == "now":
        print("  running now; results are emailed to your fn2 account when it finishes.")
        print(f"  watch it:  fn2 status {agent_id}")
    else:
        print("  results are emailed to your fn2 account after each run.")
        print(f"  inspect:   fn2 status {agent_id}")
    return 0


def cmd_agents(args: argparse.Namespace) -> int:
    client = _client(args)
    data = api.list_agents(client, status=args.status, limit=args.limit,
                           offset=args.offset)
    _out(args, data, render.agents)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    client = _client(args)
    if not args.agent_id:
        data = api.list_agents(client, limit=args.limit)
        _out(args, data, render.agents)
        return 0

    agent = api.get_agent(client, args.agent_id)
    if getattr(args, "json", False):
        recent = api.list_runs(client, args.agent_id, limit=args.runs)
        render.emit_json({"agent": agent, "recent_runs": recent})
        return 0
    render.agent_detail(agent)
    if args.runs:
        print("\nrecent runs:")
        render.runs(api.list_runs(client, args.agent_id, limit=args.runs))
    return 0


# ---------------------------------------------------------------------------
# trigger / read
# ---------------------------------------------------------------------------
def cmd_run(args: argparse.Namespace) -> int:
    client = _client(args)
    result = api.run_agent(client, args.agent_id)
    if getattr(args, "json", False):
        render.emit_json(result)
        return 0
    run_id = result.get("run_id") or result.get("id")
    print(f"✓ run queued — {run_id} ({result.get('status', 'pending')})")
    print(f"  result: fn2 result {args.agent_id} {run_id}")
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    client = _client(args)
    data = api.list_runs(client, args.agent_id, limit=args.limit, offset=args.offset)
    _out(args, data, render.runs)
    return 0


def cmd_result(args: argparse.Namespace) -> int:
    client = _client(args)
    data = api.get_run(client, args.agent_id, args.run_id)
    _out(args, data, render.run_result)
    return 0


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------
def cmd_pause(args: argparse.Namespace) -> int:
    client = _client(args)
    api.update_agent(client, args.agent_id, status="paused")
    print(f"⏸ paused {args.agent_id}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    client = _client(args)
    api.update_agent(client, args.agent_id, status="active")
    print(f"▶ resumed {args.agent_id}")
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    client = _client(args)
    sched = schedule.parse_when(args.when, timezone=args.tz)
    if sched.kind == "now" or sched.payload is None:
        print("error: give a cadence, e.g. 'before market open', 'weekdays at 8am', "
              "or 'cron:0 9 * * 1-5'.", file=sys.stderr)
        return 1
    payload = sched.payload
    if args.ends and sched.kind == "recurring":
        payload = {**payload, "ends_at": args.ends}
    api.update_agent(client, args.agent_id, schedule=payload)
    print(f"✓ rescheduled {args.agent_id}: {sched.summary}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    client = _client(args)
    if not args.yes and sys.stdin.isatty():
        reply = input(f"delete agent {args.agent_id} and its history? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.")
            return 1
    api.delete_agent(client, args.agent_id)
    print(f"🗑 deleted {args.agent_id}")
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fn2",
        description="Start, watch, and schedule fn2.ai research agents.",
    )
    parser.add_argument("--version", action="version",
                        version=f"fn2-skill {__version__}")
    parser.add_argument("--base-url", help="override the fn2 endpoint (or set FN2_BASE_URL)")
    parser.add_argument("--json", action="store_true", help="emit raw JSON")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    def add(name, func, help_text, aliases=()):
        p = sub.add_parser(name, help=help_text, aliases=list(aliases))
        p.set_defaults(func=func)
        return p

    p = add("login", cmd_login, "connect your fn2 account")
    p.add_argument("--token", help="an fn2_… API key (omit for guided setup)")
    p.add_argument("--email", help="pre-fill your email on the sign-up link")

    add("logout", cmd_logout, "remove the stored key")
    add("whoami", cmd_whoami, "show the signed-in account, plan, and quota")
    add("models", cmd_models, "list models available to your account")

    p = add("start", cmd_start, "create an agent (runs now, or on a schedule)")
    p.add_argument("prompt", help="what the agent should research/do")
    p.add_argument("--name", help="a label for the agent")
    p.add_argument("--model", help="model_id from `fn2 models` (optional)")
    p.add_argument("--label", action="append", help="tag (repeatable)")
    p.add_argument("--when", help="cadence, e.g. 'before market open', 'weekdays at "
                                  "8am', 'hourly', 'in 2 hours', 'cron:0 9 * * 1-5'")
    p.add_argument("--tz", help="IANA timezone for the cadence (default UTC; "
                                "market phrases default to America/New_York)")
    p.add_argument("--ends", metavar="YYYY-MM-DD", help="stop recurring after this date")

    p = add("agents", cmd_agents, "list your agents", aliases=("list", "ls"))
    p.add_argument("--status", help="filter by status (active, paused, …)")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--offset", type=int, default=0)

    p = add("status", cmd_status, "overview of all agents, or detail for one")
    p.add_argument("agent_id", nargs="?", help="agent id (omit for the overview)")
    p.add_argument("--runs", type=int, default=5, help="recent runs to show (detail view)")
    p.add_argument("--limit", type=int, default=50, help="agents to show (overview)")

    p = add("run", cmd_run, "trigger an agent immediately")
    p.add_argument("agent_id")

    p = add("runs", cmd_runs, "list an agent's runs")
    p.add_argument("agent_id")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)

    p = add("result", cmd_result, "show one run's outcome and output")
    p.add_argument("agent_id")
    p.add_argument("run_id")

    p = add("pause", cmd_pause, "pause a scheduled agent")
    p.add_argument("agent_id")

    p = add("resume", cmd_resume, "resume a paused agent")
    p.add_argument("agent_id")

    p = add("schedule", cmd_schedule, "change an agent's cadence")
    p.add_argument("agent_id")
    p.add_argument("when", help="new cadence (see `start --when`)")
    p.add_argument("--tz", help="IANA timezone")
    p.add_argument("--ends", metavar="YYYY-MM-DD")

    p = add("delete", cmd_delete, "delete an agent and its history", aliases=("rm",))
    p.add_argument("agent_id")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except AuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("your key may be revoked or out of scope — run `fn2 login` again.",
              file=sys.stderr)
        return 1
    except (ApiError, schedule.ScheduleError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("\ninterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
