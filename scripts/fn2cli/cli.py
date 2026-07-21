"""Command-line surface for the fn2 agents API.

Verbs map onto the things the skill promises: connect an account without
copying secrets, start agents, see their status, and schedule them.

    auth login / auth status / auth logout    device sign-in & credential lifecycle
    permissions / doctor                      what's granted / local diagnostics
    login / logout / whoami / models          manual key fallback & account info
    start / agents / status                   create and inspect
    run / runs / result                       trigger and read outcomes
    pause / resume / schedule / delete        manage lifecycle
"""

from __future__ import annotations

import argparse
import dataclasses
import getpass
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

from . import __version__, api, config, deviceauth, render, schedule, storage
from .client import ApiError, AuthError, Client

_SCOPE_MEANINGS = {
    "agents": "Create and run your fn2 research agents",
    "models": "See which models your plan can use",
}
_NOT_GRANTED = (
    "read or change billing, email, or password",
    "open a web session or read your chats",
    "approve new devices or create API keys",
)
_REVOKE_POINTER = ("revoke anytime: fn2.ai → Preferences → Developer → Connected "
                   "Devices (takes effect within a few minutes everywhere)")


# ---------------------------------------------------------------------------
# context helpers
# ---------------------------------------------------------------------------
def _settings(args: argparse.Namespace, *, enforce_origin: bool = True) -> config.Settings:
    settings = config.resolve()
    if getattr(args, "base_url", None):
        settings = dataclasses.replace(settings, base_url=args.base_url.rstrip("/"))
    if enforce_origin:
        # The credential is never sent to a non-pinned origin.
        config.enforce_base_url(settings.base_url)
    return settings


def _client(args: argparse.Namespace, *, require_auth: bool = True) -> Client:
    settings = _settings(args)
    if require_auth and not settings.authenticated:
        raise SystemExit(
            "not signed in. Run `fn2 auth login` to connect your fn2 account "
            f"({settings.onboard_url})."
        )
    return Client(settings.base_url, settings.api_key)


def _out(args: argparse.Namespace, obj, view) -> None:
    """Emit JSON when --json is set, otherwise the human view."""
    if getattr(args, "json", False):
        render.emit_json(obj)
    else:
        view(obj)


def _emit_json_safe(obj: Any) -> None:
    """JSON output for auth surfaces: every secret-shaped string is masked."""
    print(config.redact(json.dumps(obj, indent=2, sort_keys=False, default=str)))


def _source_label(settings: config.Settings) -> str:
    return {
        "env": "environment (FN2_API_TOKEN)",
        "env-legacy": "environment (FN2_API_KEY, legacy alias)",
        "keychain": storage.describe_backend("keychain"),
        "file": str(storage.credentials_path()),
    }.get(settings.source, settings.source)


def _open_browser(uri: str) -> bool:
    try:
        import webbrowser
        return bool(webbrowser.open(uri))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# auth — device sign-in & credential lifecycle
# ---------------------------------------------------------------------------
def _start_device_flow(client: Client, settings: config.Settings) -> Dict[str, Any]:
    response = deviceauth.start(client)
    try:
        expires_in = int(response.get("expires_in") or 900)
    except (TypeError, ValueError):
        expires_in = 900
    pending = {
        "device_code": response.get("device_code"),
        "user_code": response.get("user_code"),
        "verification_uri": response.get("verification_uri") or settings.onboard_url,
        "interval": response.get("interval") or deviceauth.DEFAULT_INTERVAL,
        "expires_at": time.time() + expires_in,
        "base_url": settings.base_url,
    }
    storage.save_pending(pending)
    return pending


def _run_device_flow(client: Client, flow: Dict[str, Any],
                     args: argparse.Namespace, say) -> Dict[str, Any]:
    uri = flow.get("verification_uri") or config.DEFAULT_ONBOARD_URL
    code = str(flow.get("user_code") or "")
    say(f"\nOpen {uri}")
    say(f"Enter code {code}")
    if not getattr(args, "no_browser", False) and sys.stdout.isatty():
        if _open_browser(uri):
            say("(opened in your browser)")
    say("\nwaiting for approval — Ctrl-C is safe; `fn2 auth login` resumes.")
    try:
        return deviceauth.poll_until_complete(
            client, str(flow.get("device_code") or ""),
            interval=flow.get("interval"),
            deadline=float(flow.get("expires_at") or 0) or None,
        )
    except KeyboardInterrupt:
        say("\ninterrupted — your code stays valid; run `fn2 auth login` to resume.")
        raise SystemExit(130)


def cmd_auth_login(args: argparse.Namespace) -> int:
    settings = _settings(args)
    json_mode = getattr(args, "json", False)
    say = (lambda *a: print(*a, file=sys.stderr)) if json_mode else print
    client = Client(settings.base_url)

    resumed = False
    flow: Optional[Dict[str, Any]] = None
    pending = storage.load_pending()
    if (pending and pending.get("device_code")
            and pending.get("base_url") == settings.base_url
            and float(pending.get("expires_at") or 0) > time.time() + 5):
        flow, resumed = pending, True
        say("resuming your pending sign-in…")
    if flow is None:
        storage.clear_pending()
        flow = _start_device_flow(client, settings)

    outcome = _run_device_flow(client, flow, args, say)
    if outcome.get("status") == "expired" and resumed:
        # The resumed request aged out — restart once with a fresh code.
        say("that code expired — starting a fresh sign-in.")
        storage.clear_pending()
        flow = _start_device_flow(client, settings)
        outcome = _run_device_flow(client, flow, args, say)

    status = outcome.get("status")
    if status == "approved":
        token = str(outcome.get("access_token") or "")
        account = outcome.get("account") if isinstance(outcome.get("account"), dict) else {}
        scopes = outcome.get("scopes") or list(deviceauth.DEFAULT_SCOPES)
        backend = storage.store_credential(
            token, base_url=settings.base_url, kind="device",
            extra={
                "scopes": scopes,
                "device_id": outcome.get("device_id"),
                "expires_at": outcome.get("expires_at"),
                "account": account or None,
            },
        )
        storage.clear_pending()
        identity = account.get("email_masked") or "your fn2 account"
        if json_mode:
            _emit_json_safe({
                "status": "approved",
                "account": account,
                "device_id": outcome.get("device_id"),
                "scopes": scopes,
                "expires_at": outcome.get("expires_at"),
                "storage": backend,
                "credential": config.mask(token),
            })
        else:
            print(f"\n✓ signed in as {identity}")
            print(f"  credential {config.mask(token)} stored in {storage.describe_backend(backend)}")
            print(f"  scopes: {', '.join(scopes)}   expires: {render.fmt_ts(outcome.get('expires_at'))}")
            print(f"  {_REVOKE_POINTER}")
        return 0

    storage.clear_pending()
    if status == "denied":
        say("\nsign-in was denied in the browser. Nothing was stored.")
        if json_mode:
            _emit_json_safe({"status": "denied"})
        return 1
    say("\nthe sign-in code expired before approval. Run `fn2 auth login` to try again.")
    if json_mode:
        _emit_json_safe({"status": "expired"})
    return 1


def cmd_auth_status(args: argparse.Namespace) -> int:
    settings = _settings(args)
    json_mode = getattr(args, "json", False)
    record = storage.load_record()

    if not settings.authenticated:
        if json_mode:
            _emit_json_safe({"status": "signed_out"})
        else:
            print(f"not signed in. Run `fn2 auth login` ({settings.onboard_url}).")
        return 2

    info: Dict[str, Any] = {
        "status": "signed_in",
        "storage": settings.source,
        "credential": config.mask(settings.api_key),
        "kind": settings.credential_kind,
        "endpoint": settings.base_url,
        "scopes": record.get("scopes"),
        "expires_at": record.get("expires_at"),
        "last_verified_at": record.get("last_verified_at"),
    }

    verified_error: Optional[str] = None
    unreachable: Optional[str] = None
    client = Client(settings.base_url, settings.api_key)
    try:
        usage = api.usage(client)
        info["verified"] = True
        info["plan"] = usage.get("plan")
        if settings.source in ("keychain", "file") and record:
            record["last_verified_at"] = render.now_iso()
            try:
                storage.save_record(record)
            except storage.StorageError:
                pass
            info["last_verified_at"] = record["last_verified_at"]
    except AuthError as exc:
        info["verified"] = False
        verified_error = str(exc)
    except ApiError as exc:
        info["verified"] = None
        unreachable = str(exc)

    if json_mode:
        _emit_json_safe(info)
    else:
        print(f"storage    {_source_label(settings)}")
        kind_label = "device token" if info["kind"] == "device" else "API key"
        print(f"credential {info['credential']} ({kind_label})")
        if info.get("scopes"):
            print(f"scopes     {', '.join(info['scopes'])}")
        if info.get("expires_at"):
            print(f"expires    {render.fmt_ts(info['expires_at'])}")
        print(f"endpoint   {settings.base_url}")
        if info["verified"] is True:
            plan = f" — plan {info['plan']}" if info.get("plan") else ""
            print(f"verified   just now{plan}")
        elif info["verified"] is False:
            print("verified   NO — fn2 rejected this credential (revoked or expired).")
            print("           Reconnect with `fn2 auth login`.")
        else:
            print(f"verified   could not reach fn2 ({config.redact(unreachable or '')})")
            if info.get("last_verified_at"):
                print(f"           last verified {render.rel_ts(info['last_verified_at'])}")

    if verified_error is not None:
        return 1
    return 0


def cmd_auth_logout(args: argparse.Namespace) -> int:
    revoke = getattr(args, "revoke", False)
    settings = _settings(args, enforce_origin=revoke)

    if revoke:
        if not settings.authenticated:
            print("no credential found — nothing to revoke on fn2.")
        elif settings.credential_kind == "device":
            client = Client(settings.base_url, settings.api_key)
            try:
                deviceauth.logout(client)
                print("✓ device credential revoked on fn2.")
            except AuthError:
                # 401/403 = the credential is already dead server-side. Same end state.
                print("credential was already revoked or expired on fn2.")
            except ApiError as exc:
                # A transient failure (500/timeout/network) must not block local
                # sign-out — the credential is still revocable from the web app.
                print(f"could not confirm remote revoke ({config.redact(str(exc))}); "
                      "removing it locally. Revoke from fn2.ai › Preferences › "
                      "Developer › Connected Devices if it may still be active.")
        else:
            # /skill/device-auth/logout only revokes device tokens; an API key
            # must be deleted from the web app, not this endpoint.
            print("this is an API key, not a device credential — revoke it in the "
                  "fn2.ai web app (Preferences › Developer › API keys). "
                  "Removing it locally now.")

    removed = storage.clear_credential(settings.base_url)
    storage.clear_pending()
    if removed:
        print("signed out — stored credential removed.")
    else:
        print("no stored credential to remove.")
    if settings.source in ("env", "env-legacy"):
        env_name = "FN2_API_TOKEN" if settings.source == "env" else "FN2_API_KEY"
        print(f"note: {env_name} is still set in this environment and will be used "
              "until you unset it.")
    return 0


def cmd_permissions(args: argparse.Namespace) -> int:
    settings = _settings(args)
    json_mode = getattr(args, "json", False)
    record = storage.load_record()

    if not settings.authenticated:
        if json_mode:
            _emit_json_safe({"status": "signed_out"})
        else:
            print(f"not signed in. Run `fn2 auth login` ({settings.onboard_url}).")
        return 2

    scopes = record.get("scopes") or list(deviceauth.DEFAULT_SCOPES)
    scope_detail = [
        {"scope": s, "meaning": _SCOPE_MEANINGS.get(s, "(no description)")}
        for s in scopes
    ]
    if json_mode:
        _emit_json_safe({
            "kind": settings.credential_kind,
            "scopes": scope_detail,
            "not_granted": list(_NOT_GRANTED),
            "expires_at": record.get("expires_at"),
        })
        return 0

    print("granted scopes:")
    for entry in scope_detail:
        print(f"  {entry['scope']:<8}{entry['meaning']}")
    if settings.credential_kind == "api_key" and not record.get("scopes"):
        print("  (scopes as granted at key creation — see fn2.ai → Preferences → Developer)")
    print("\nthis credential can NOT:")
    for line in _NOT_GRANTED:
        print(f"  - {line}")
    if record.get("expires_at"):
        print(f"\nexpires    {render.fmt_ts(record.get('expires_at'))}")
    print(f"\n{_REVOKE_POINTER}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = _settings(args, enforce_origin=False)
    json_mode = getattr(args, "json", False)
    checks: List[Dict[str, Any]] = []

    def check(name: str, ok: Optional[bool], detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    # python version
    py = sys.version_info
    check("python", py >= (3, 9), f"{py.major}.{py.minor}.{py.micro} (need 3.9+)")

    # config dir + files
    home = storage.config_home()
    if home.exists():
        if home.is_symlink():
            check("config dir", False, f"{home} is a symlink — remove it")
        else:
            mode = os.stat(str(home)).st_mode & 0o777
            ok = not (mode & 0o077)
            check("config dir", ok,
                  f"{home} mode {mode:03o}" + ("" if ok else " — run chmod 700"))
    else:
        check("config dir", True, f"{home} (not created yet)")

    creds = storage.credentials_path()
    if creds.is_symlink():
        check("credentials file", False, f"{creds} is a symlink — remove it")
    elif creds.exists():
        mode = os.stat(str(creds)).st_mode & 0o777
        ok = not (mode & 0o077)
        check("credentials file", ok,
              f"{creds} mode {mode:03o}" + ("" if ok else " — run chmod 600"))
    else:
        check("credentials file", True, "none stored")

    pending = storage.load_pending()
    if pending:
        live = float(pending.get("expires_at") or 0) > time.time()
        check("pending login", True,
              "resumable sign-in present" if live else "expired — `fn2 auth login` starts fresh")

    # storage backend + credential
    backend = "keychain" if storage.keychain_available() else "file"
    check("storage backend", True, storage.describe_backend(backend))
    if settings.authenticated:
        kind = "device token" if settings.credential_kind == "device" else "API key"
        check("credential", True,
              f"{config.mask(settings.api_key)} ({kind}, from {settings.source})")
    else:
        check("credential", None, "not signed in — run `fn2 auth login`")

    # base-URL policy
    verdict = config.origin_verdict(settings.base_url)
    check("base URL", verdict != "refused",
          f"{settings.base_url} — {verdict}"
          + ("" if verdict == "pinned" else
             " (FN2_ALLOW_DEV_BASE=1 dev override)" if verdict == "dev-allowed" else
             " — credentials will not be sent here"))

    # reachability (unauthenticated endpoint; no credential leaves the machine)
    if verdict == "refused":
        check("reachability", None, "skipped — base URL refused")
    else:
        try:
            Client(settings.base_url).get("/api/v1/market/status", auth=False)
            check("reachability", True, f"{settings.base_url}/api/v1/market/status ok")
        except ApiError as exc:
            check("reachability", False, config.redact(str(exc)))

    failed = any(c["ok"] is False for c in checks)
    if json_mode:
        _emit_json_safe({"ok": not failed, "checks": checks})
    else:
        for c in checks:
            icon = {True: "ok  ", False: "FAIL", None: "--  "}[c["ok"]]
            print(f"{icon} {c['check']:<18}{c['detail']}")
        print("\nall good." if not failed else "\nproblems found — fix the FAIL lines above.")
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# account / onboarding (manual API-key fallback)
# ---------------------------------------------------------------------------
def cmd_login(args: argparse.Namespace) -> int:
    settings = _settings(args)
    token = (args.token or "").strip()

    if not token:
        print("The easy way is the browser sign-in — no key copying:\n")
        print("    fn2 auth login\n")
        print("Advanced fallback (CI / manual): create an API key with the 'agents'")
        print(f"scope in the fn2 web app ({settings.onboard_url}), then:")
        print("\n    fn2 login --token fn2_xxxxxxxxxxxxxxxxxxxx\n")
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

    backend = storage.store_credential(token, base_url=settings.base_url, kind="api_key")
    print(f"\n✓ signed in — key {config.mask(token)} stored in "
          f"{storage.describe_backend(backend)}")
    render.usage(info)
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if not settings.authenticated:
        print(f"not signed in. Run `fn2 auth login` ({settings.onboard_url}).")
        return 2
    client = Client(settings.base_url, settings.api_key)
    info = api.usage(client)
    if getattr(args, "json", False):
        _emit_json_safe(info)
        return 0
    print(f"endpoint   {settings.base_url}")
    kind_label = "device token" if settings.credential_kind == "device" else "API key"
    print(f"credential {config.mask(settings.api_key)} ({kind_label}, from {settings.source})")
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
        print("  running now.")
        print(f"  watch it:  fn2 status {agent_id}")
    else:
        print(f"  inspect:   fn2 status {agent_id}")
    print(f"  results:   fn2 result {agent_id} <run_id> — also in the fn2 web app,")
    print("             where email delivery can be configured.")
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

    def add(name, func, help_text, aliases=(), parent=sub):
        p = parent.add_parser(name, help=help_text, aliases=list(aliases))
        p.set_defaults(func=func)
        return p

    def add_json(p):
        # SUPPRESS keeps a root-level `fn2 --json <cmd>` from being clobbered.
        p.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                       help="emit raw JSON")

    p_auth = sub.add_parser("auth", help="sign in via the browser, inspect or drop the credential")
    auth_sub = p_auth.add_subparsers(dest="auth_command", required=True,
                                     metavar="<auth-command>")

    p = add("login", cmd_auth_login, "sign in: open fn2.ai/start, enter a short code",
            parent=auth_sub)
    p.add_argument("--no-browser", action="store_true",
                   help="don't try to open the browser automatically")
    add_json(p)

    p = add("status", cmd_auth_status, "where the credential lives + live verification",
            parent=auth_sub)
    add_json(p)

    p = add("logout", cmd_auth_logout, "remove the stored credential", parent=auth_sub)
    p.add_argument("--revoke", action="store_true",
                   help="also revoke the device credential on fn2 first")

    p = add("permissions", cmd_permissions, "what this credential can and cannot do")
    add_json(p)

    p = add("doctor", cmd_doctor, "diagnose config, storage, and connectivity")
    add_json(p)

    p = add("login", cmd_login, "connect with a manual API key (advanced fallback)")
    p.add_argument("--token", help="an fn2_… API key (prefer `fn2 auth login`)")

    p = add("logout", cmd_auth_logout, "remove the stored credential")
    p.add_argument("--revoke", action="store_true",
                   help="also revoke the device credential on fn2 first")

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
        print(f"error: {config.redact(str(exc))}", file=sys.stderr)
        print("your credential may be revoked or out of scope — run `fn2 auth login` again.",
              file=sys.stderr)
        return 1
    except storage.StorageError as exc:
        print(f"error: {config.redact(str(exc))}", file=sys.stderr)
        return 1
    except (ApiError, schedule.ScheduleError) as exc:
        print(f"error: {config.redact(str(exc))}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("\ninterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
