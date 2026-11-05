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
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__, api, config, deviceauth, render, schedule, storage, style
from .client import ApiError, AuthError, Client

_SCOPE_MEANINGS = {
    "agents": "Create and run your FN2 AI research agents",
    "models": "See which models your plan can use",
}
_NOT_GRANTED = (
    "read or change billing, email, or password",
    "open a web session or read your chats",
    "approve new devices or create API keys",
)
_REVOKE_POINTER = ("revoke anytime: fn2.ai > Preferences > Developer > Connected "
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
            "not signed in. Run `fn2 auth login` to connect your FN2 AI account "
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


def _display_available(environ: Optional[Dict[str, str]] = None,
                       platform: Optional[str] = None) -> bool:
    """Whether this machine can plausibly put a browser window in front of the user.

    Deliberately not an isatty() check: the normal caller is an assistant
    driving the CLI through a pipe while the user sits at the same desktop, and
    that user still wants the sign-in page opened for them. What matters is a
    display, not a terminal: always present on macOS and Windows, present on
    Linux when X11/Wayland says so, and never on the far side of a plain SSH
    session (opening a browser there would land on the wrong machine's screen).
    """
    env = os.environ if environ is None else environ
    plat = platform if platform is not None else sys.platform
    if env.get("SSH_CONNECTION") or env.get("SSH_TTY"):
        return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))
    if plat == "darwin" or plat.startswith("win") or plat == "cygwin":
        return True
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


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


def _announce_device_flow(flow: Dict[str, Any], args: argparse.Namespace, say) -> None:
    """Print the URL + code first (they must never be stranded behind a poll),
    then try the browser."""
    uri = flow.get("verification_uri") or config.DEFAULT_ONBOARD_URL
    code = str(flow.get("user_code") or "")
    say(f"\nOpen {uri}")
    say(f"Enter code {code}")
    if not getattr(args, "no_browser", False) and _display_available():
        if _open_browser(uri):
            say("(opened in your browser)")


def _run_device_flow(client: Client, flow: Dict[str, Any],
                     args: argparse.Namespace, say) -> Dict[str, Any]:
    _announce_device_flow(flow, args, say)
    say("\nwaiting for approval. Ctrl-C is safe; `fn2 auth login` resumes.")
    try:
        return deviceauth.poll_until_complete(
            client, str(flow.get("device_code") or ""),
            interval=flow.get("interval"),
            deadline=float(flow.get("expires_at") or 0) or None,
        )
    except KeyboardInterrupt:
        say("\ninterrupted. Your code stays valid; run `fn2 auth login` to resume.")
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

    if getattr(args, "no_wait", False):
        # Two-phase flow for assistants: surface the code now, poll later.
        _announce_device_flow(flow, args, say)
        say("\nnot waiting (--no-wait). Approve in the browser, then run "
            "`fn2 auth login` again; it resumes this code and finishes.")
        if json_mode:
            _emit_json_safe({
                "status": "pending",
                "user_code": flow.get("user_code"),
                "verification_uri": flow.get("verification_uri"),
                "expires_at": flow.get("expires_at"),
            })
        return 0

    outcome = _run_device_flow(client, flow, args, say)
    if outcome.get("status") == "expired" and resumed:
        # The resumed request aged out — restart once with a fresh code.
        say("that code expired. Starting a fresh sign-in.")
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
        identity = account.get("email_masked") or "your FN2 AI account"
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
            print(f"\n{style.tick()} signed in as {style.paint(identity, 'bold')}")
            print(f"  credential {config.mask(token)} stored in "
                  f"{storage.describe_backend(backend)}")
            print(f"  scopes: {', '.join(scopes)}   expires: {render.fmt_ts(outcome.get('expires_at'))}")
            print(style.label(f"  {_REVOKE_POINTER}"))
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
            plan = f" (plan {info['plan']})" if info.get("plan") else ""
            print(f"{style.label('verified   ')}{style.ok('just now')}{plan}")
        elif info["verified"] is False:
            print(f"{style.label('verified   ')}"
                  f"{style.bad('NO')}. FN2 AI rejected this credential "
                  "(revoked or expired).")
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
            print("no credential found; nothing to revoke on FN2 AI.")
        elif settings.credential_kind == "device":
            client = Client(settings.base_url, settings.api_key)
            try:
                deviceauth.logout(client)
                print(f"{style.tick()} device credential revoked on FN2 AI.")
            except AuthError:
                # 401/403 = the credential is already dead server-side. Same end state.
                print("credential was already revoked or expired on FN2 AI.")
            except ApiError as exc:
                # A transient failure (500/timeout/network) must not block local
                # sign-out — the credential is still revocable from the web app.
                print(f"could not confirm remote revoke ({config.redact(str(exc))}); "
                      "removing it locally. Revoke from fn2.ai › Preferences › "
                      "Developer › Connected Devices if it may still be active.")
        else:
            # /skill/device-auth/logout only revokes device tokens; an API key
            # must be deleted from the web app, not this endpoint.
            print("this is an API key, not a device credential; revoke it in the "
                  "fn2.ai web app (Preferences › Developer › API keys). "
                  "Removing it locally now.")

    removed = storage.clear_credential(settings.base_url)
    storage.clear_pending()
    if removed:
        print("signed out; stored credential removed.")
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

    print(style.head("granted scopes:"))
    for entry in scope_detail:
        print(f"  {style.paint(entry['scope'].ljust(8), 'cyan')}{entry['meaning']}")
    if settings.credential_kind == "api_key" and not record.get("scopes"):
        print(style.label("  (scopes as granted at key creation: see fn2.ai > "
                          "Preferences > Developer)"))
    print("\n" + style.head("this credential can NOT:"))
    for line in _NOT_GRANTED:
        print(f"  - {line}")
    if record.get("expires_at"):
        print("\n" + style.label("expires    ")
              + render.fmt_ts(record.get("expires_at")))
    print("\n" + style.label(_REVOKE_POINTER))
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
            check("config dir", False, f"{home} is a symlink; remove it")
        else:
            mode = os.stat(str(home)).st_mode & 0o777
            ok = not (mode & 0o077)
            check("config dir", ok,
                  f"{home} mode {mode:03o}" + ("" if ok else "; run chmod 700"))
    else:
        check("config dir", True, f"{home} (not created yet)")

    creds = storage.credentials_path()
    if creds.is_symlink():
        check("credentials file", False, f"{creds} is a symlink; remove it")
    elif creds.exists():
        mode = os.stat(str(creds)).st_mode & 0o777
        ok = not (mode & 0o077)
        check("credentials file", ok,
              f"{creds} mode {mode:03o}" + ("" if ok else "; run chmod 600"))
    else:
        check("credentials file", True, "none stored")

    pending = storage.load_pending()
    if pending:
        live = float(pending.get("expires_at") or 0) > time.time()
        check("pending login", True,
              "resumable sign-in present" if live else "expired; `fn2 auth login` starts fresh")

    # storage backend + credential
    backend = "keychain" if storage.keychain_available() else "file"
    check("storage backend", True, storage.describe_backend(backend))
    if settings.authenticated:
        kind = "device token" if settings.credential_kind == "device" else "API key"
        check("credential", True,
              f"{config.mask(settings.api_key)} ({kind}, from {settings.source})")
    else:
        check("credential", None, "not signed in; run `fn2 auth login`")

    # base-URL policy
    verdict = config.origin_verdict(settings.base_url)
    check("base URL", verdict != "refused",
          f"{settings.base_url} ({verdict})"
          + ("" if verdict == "pinned" else
             " FN2_ALLOW_DEV_BASE=1 dev override" if verdict == "dev-allowed" else
             "; credentials will not be sent here"))

    # Reachability, from a SIGNED-OUT machine — which is when `doctor` is
    # actually run. The probe must therefore be an endpoint the public gateway
    # lets through unauthenticated.
    #
    # It used to probe /api/v1/market/status. That route is public in
    # stock-server but stock-web's `location /api/` runs a JWT gate in front of
    # it, so it answers 401 to anyone without a session — this check could
    # never pass before sign-in, which is precisely the state `doctor` exists
    # to diagnose. (The deploy smoke reaches market/status through the
    # kube-apiserver service proxy rather than nginx, which is why the
    # asymmetry went unnoticed. Same class as FNAI-2411.)
    #
    # /api/v1/public-config is genuinely public: it backs the signed-out shell.
    probe = "/api/v1/public-config"
    if verdict == "refused":
        check("reachability", None, "skipped; base URL refused")
    else:
        try:
            Client(settings.base_url).get(probe, auth=False)
            check("reachability", True, f"{settings.base_url}{probe} ok")
        except ApiError as exc:
            check("reachability", False, config.redact(str(exc)))

    failed = any(c["ok"] is False for c in checks)
    if json_mode:
        _emit_json_safe({"ok": not failed, "checks": checks})
    else:
        for c in checks:
            icon = {True: style.ok("ok  "), False: style.bad("FAIL"),
                    None: style.label("--  ")}[c["ok"]]
            print(f"{icon} {style.label(c['check'].ljust(18))}{c['detail']}")
        print("\n" + (style.ok("all good.") if not failed else
                       style.bad("problems found. Fix the FAIL lines above.")))
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# launcher: put `fn2` on PATH
# ---------------------------------------------------------------------------
# Installing a plugin gives you a skill, not a binary; nothing touches PATH.
# This writes a launcher that re-resolves the helper on every run, so a plugin
# update (which moves the versioned install directory) cannot strand it.
_LAUNCHER = """#!/bin/sh
# fn2 launcher, written by `fn2 link`. Do not edit: re-run `fn2 link` instead.
# Resolves the newest installed copy at run time, so plugin updates just work.
claude_home="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
codex_home="${CODEX_HOME:-$HOME/.codex}"
helper=$(ls -td "$claude_home"/plugins/cache/*/*/*/skills/fn2 \\
                "$codex_home"/plugins/cache/*/*/*/skills/fn2 \\
                "$claude_home"/skills/fn2 \\
                "$codex_home"/skills/fn2 \\
                "$HOME"/.agents/skills/fn2 \\
                "${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"/skills/fn2 \\
                "${HERMES_HOME:-$HOME/.hermes}"/skills/fn2 2>/dev/null | head -1)
if [ -z "$helper" ]; then
    echo "fn2: skill not found. Reinstall the plugin, or run \\`fn2 link\\` again." >&2
    exit 127
fi
exec "${FN2_PYTHON:-python3}" "$helper/scripts/fn2" "$@"
"""


def _path_entries() -> List[str]:
    return [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]


def _launcher_target(explicit: Optional[str]) -> Path:
    """Pick a bin directory: prefer one already on PATH that we can write to."""
    if explicit:
        return Path(explicit).expanduser() / "fn2"
    home = Path.home()
    candidates = [home / ".local" / "bin", home / "bin", Path("/usr/local/bin")]
    on_path = set(_path_entries())
    writable = [d for d in candidates
                if d.is_dir() and os.access(str(d), os.W_OK)]
    for directory in writable:
        if str(directory) in on_path:
            return directory / "fn2"
    if writable:
        return writable[0] / "fn2"
    return candidates[0] / "fn2"  # created below


def cmd_link(args: argparse.Namespace) -> int:
    target = _launcher_target(getattr(args, "dir", None))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_LAUNCHER, encoding="utf-8")
        os.chmod(str(target), 0o755)
    except OSError as exc:
        print(f"error: could not write {target}: {exc}", file=sys.stderr)
        print("Pass a writable directory with --dir, e.g. `fn2 link --dir ~/bin`.",
              file=sys.stderr)
        return 1

    print(f"{style.tick()} installed {style.paint(str(target), 'cyan')}")
    if str(target.parent) not in _path_entries():
        rc = "~/.zshrc" if os.environ.get("SHELL", "").endswith("zsh") else "~/.bashrc"
        print(f"\n{target.parent} is not on your PATH. Add it:\n")
        print(f'    echo \'export PATH="{target.parent}:$PATH"\' >> {rc}')
        print(f"    exec $SHELL -l\n")
    else:
        print("  run `fn2 auth login` to connect your account.")
    return 0


def cmd_unlink(args: argparse.Namespace) -> int:
    explicit = getattr(args, "dir", None)
    # Scan every place `link` could have chosen, not just the one it would
    # choose now: PATH may differ between the two invocations.
    home = Path.home()
    candidates = [Path(explicit).expanduser() / "fn2"] if explicit else [
        d / "fn2" for d in (home / ".local" / "bin", home / "bin",
                            Path("/usr/local/bin"))
    ] + [Path(d) / "fn2" for d in _path_entries()]

    removed = 0
    seen = set()
    for target in candidates:
        if str(target) in seen:
            continue
        seen.add(str(target))
        if not target.is_file():
            continue
        if "written by `fn2 link`" not in target.read_text(encoding="utf-8",
                                                           errors="replace"):
            print(f"skipped {target}: not written by `fn2 link`.", file=sys.stderr)
            continue
        try:
            target.unlink()
        except OSError as exc:
            print(f"error: could not remove {target}: {exc}", file=sys.stderr)
            return 1
        print(f"removed {target}")
        removed += 1
    if not removed:
        print("no `fn2 link` launcher found.")
    return 0


# ---------------------------------------------------------------------------
# account / onboarding (manual API-key fallback)
# ---------------------------------------------------------------------------
def cmd_login(args: argparse.Namespace) -> int:
    settings = _settings(args)
    token = (args.token or "").strip()

    if not token:
        print("The easy way is the browser sign-in, with no key copying:\n")
        print("    fn2 auth login\n")
        print("Advanced fallback (CI / manual): create an API key with the 'agents'")
        print(f"scope in the FN2 AI web app ({settings.onboard_url}), then:")
        print("\n    fn2 login --token fn2_xxxxxxxxxxxxxxxxxxxx\n")
        if sys.stdin.isatty():
            try:
                token = getpass.getpass("fn2 API key (or Enter to cancel): ").strip()
            except (EOFError, KeyboardInterrupt):
                token = ""
        if not token:
            return 2

    if not config.looks_like_key(token):
        print(f"error: that does not look like an FN2 AI key (expected '{config.KEY_PREFIX}…').",
              file=sys.stderr)
        return 1

    # Validate before persisting so we never store a dud.
    probe = Client(settings.base_url, token)
    try:
        info = api.usage(probe)
    except AuthError:
        print("error: FN2 AI rejected that key. Create a fresh one and try again.",
              file=sys.stderr)
        return 1

    backend = storage.store_credential(token, base_url=settings.base_url, kind="api_key")
    print(f"\n{style.tick()} signed in: key {config.mask(token)} stored in "
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
    print(f"{style.label('endpoint   ')}{settings.base_url}")
    kind_label = "device token" if settings.credential_kind == "device" else "API key"
    print(f"{style.label('credential ')}{config.mask(settings.api_key)} "
          f"({kind_label}, from {settings.source})")
    render.usage(info)
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    client = _client(args)
    _out(args, api.list_models(client), render.models)
    return 0


# ---------------------------------------------------------------------------
# agent references
# ---------------------------------------------------------------------------
_TERMINAL_RUN_STATES = frozenset({"completed", "failed", "cancelled", "error"})


def _looks_like_id(value: str) -> bool:
    return len(value) == 36 and value.count("-") == 4


def _resolve_agent(client: Client, value: str) -> str:
    """Accept a full id, an id prefix, or a name.

    `fn2 agents` prints 8-character ids, so demanding all 36 back made the
    output un-pasteable. A full id costs no extra request; anything shorter
    resolves against your agent list and refuses to guess when ambiguous.
    """
    value = (value or "").strip()
    if not value:
        raise SystemExit("error: no agent id given.")
    if _looks_like_id(value):
        return value

    items = api.list_agents(client, limit=100).get("agents") or []
    needle = value.lower()

    def ident(a: Dict[str, Any]) -> str:
        return str(a.get("id") or a.get("agent_id") or "")

    exact = [a for a in items if ident(a).lower() == needle]
    if not exact:
        exact = [a for a in items if str(a.get("name", "")).lower() == needle]
    matches = exact or [a for a in items if ident(a).lower().startswith(needle)]
    if not matches:
        matches = [a for a in items if needle in str(a.get("name", "")).lower()]

    if len(matches) == 1:
        return ident(matches[0])
    if not matches:
        raise SystemExit(
            f"error: no agent matches {value!r}. Run `fn2 agents` to see them."
        )
    listing = "\n".join(f"  {ident(a)[:8]}  {a.get('name', '?')}" for a in matches[:8])
    raise SystemExit(f"error: {value!r} matches {len(matches)} agents:\n{listing}\n"
                     "Use a longer id prefix.")


def _await_run(client: Client, agent_id: str, run_id: str, timeout: float,
               say) -> Dict[str, Any]:
    """Block until the run is terminal, using the API's own long-poll."""
    deadline = time.time() + max(0.0, timeout)
    run: Dict[str, Any] = {}
    said = False
    while True:
        remaining = deadline - time.time()
        run = api.get_run(client, agent_id, run_id,
                          wait=max(0, min(25, int(remaining))))
        if str(run.get("status", "")).lower() in _TERMINAL_RUN_STATES:
            return run
        if remaining <= 0:
            say(f"still {run.get('status', 'running')} after {int(timeout)}s; "
                f"read it later with `fn2 result {agent_id[:8]} {run_id[:8]}`.")
            return run
        if not said:
            say("waiting for the run to finish (Ctrl-C is safe)...")
            said = True


def _first_run_id(client: Client, agent_id: str, *, wait: int = 0) -> Optional[str]:
    data = api.list_runs(client, agent_id, limit=1, wait=wait or None)
    runs = data.get("runs") if isinstance(data, dict) else data
    if not runs:
        return None
    first = runs[0]
    return str(first.get("run_id") or first.get("id") or "") or None


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
        email=getattr(args, "email", False),
    )
    if getattr(args, "json", False):
        render.emit_json(agent)
        return 0

    agent_id = agent.get("id") or agent.get("agent_id")
    print(f"{style.tick()} agent created: {style.paint(str(agent_id), 'cyan')}")
    print(f"  cadence: {style.paint(sched.summary, 'bold')}")
    if sched.kind == "now":
        print("  running now.")
        print(f"  watch it:  fn2 status {agent_id}")
    else:
        print(f"  inspect:   fn2 status {agent_id}")
    print(f"  results:   fn2 result {agent_id} (also in the web app)")
    if getattr(args, "email", False):
        print("  delivery:  emailed to your verified account address on completion.")

    if getattr(args, "wait", False) and sched.kind == "now":
        say = lambda message: print(f"  {message}")
        run_id = _first_run_id(client, str(agent_id), wait=10)
        if not run_id:
            say("no run has appeared yet; try `fn2 runs " f"{str(agent_id)[:8]}`.")
            return 0
        run = _await_run(client, str(agent_id), run_id, args.timeout, say)
        print()
        render.run_result(run)
        if str(run.get("status", "")).lower() in ("failed", "error"):
            return 1
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

    agent_id = _resolve_agent(client, args.agent_id)
    agent = api.get_agent(client, agent_id)
    if getattr(args, "json", False):
        recent = api.list_runs(client, agent_id, limit=args.runs)
        render.emit_json({"agent": agent, "recent_runs": recent})
        return 0
    render.agent_detail(agent)
    if args.runs:
        print("\n" + style.label("recent runs:"))
        render.runs(api.list_runs(client, agent_id, limit=args.runs))
    return 0


# ---------------------------------------------------------------------------
# trigger / read
# ---------------------------------------------------------------------------
def cmd_run(args: argparse.Namespace) -> int:
    client = _client(args)
    agent_id = _resolve_agent(client, args.agent_id)
    result = api.run_agent(client, agent_id)
    run_id = str(result.get("run_id") or result.get("id") or "")

    if getattr(args, "wait", False) and run_id:
        run = _await_run(client, agent_id, run_id, args.timeout,
                         lambda message: print(message, file=sys.stderr))
        _out(args, run, render.run_result)
        return 1 if str(run.get("status", "")).lower() in ("failed", "error") else 0

    if getattr(args, "json", False):
        render.emit_json(result)
        return 0
    print(f"{style.tick()} run queued: {style.paint(run_id, 'cyan')} "
          f"({result.get('status', 'pending')})")
    print(f"  result: fn2 result {agent_id[:8]}")
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    client = _client(args)
    data = api.list_runs(client, _resolve_agent(client, args.agent_id),
                         limit=args.limit, offset=args.offset)
    _out(args, data, render.runs)
    return 0


def cmd_result(args: argparse.Namespace) -> int:
    client = _client(args)
    agent_id = _resolve_agent(client, args.agent_id)
    run_id = (args.run_id or "").strip()
    if run_id in ("", "latest", "last"):
        # The common case is "show me what it just found".
        run_id = _first_run_id(client, agent_id) or ""
        if not run_id:
            raise SystemExit(f"error: agent {agent_id[:8]} has no runs yet.")
    data = api.get_run(client, agent_id, run_id)
    _out(args, data, render.run_result)
    return 0


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------
def cmd_pause(args: argparse.Namespace) -> int:
    client = _client(args)
    agent_id = _resolve_agent(client, args.agent_id)
    api.update_agent(client, agent_id, status="paused")
    print(f"{style.paint(style.glyph('pause'), 'yellow')} paused {agent_id}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    client = _client(args)
    agent_id = _resolve_agent(client, args.agent_id)
    api.update_agent(client, agent_id, status="active")
    print(f"{style.ok(style.glyph('play'))} resumed {agent_id}")
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    client = _client(args)
    agent_id = _resolve_agent(client, args.agent_id)
    sched = schedule.parse_when(args.when, timezone=args.tz)
    if sched.kind == "now" or sched.payload is None:
        print("error: give a cadence, e.g. 'before market open', 'weekdays at 8am', "
              "or 'cron:0 9 * * 1-5'.", file=sys.stderr)
        return 1
    payload = sched.payload
    if args.ends and sched.kind == "recurring":
        payload = {**payload, "ends_at": args.ends}
    api.update_agent(client, agent_id, schedule=payload)
    print(f"{style.tick()} rescheduled {agent_id[:8]}: "
          f"{style.paint(sched.summary, 'bold')}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    client = _client(args)
    agent_id = _resolve_agent(client, args.agent_id)
    if not args.yes and sys.stdin.isatty():
        # Name the agent, not just its id: a prefix match must be confirmable.
        try:
            name = api.get_agent(client, agent_id).get("name") or agent_id
        except ApiError:
            name = agent_id
        reply = input(f"delete agent {name!r} ({agent_id[:8]}) and its history? "
                      "[y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("aborted.")
            return 1
    api.delete_agent(client, agent_id)
    print(f"{style.bad(style.glyph('trash'))} deleted {agent_id}")
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fn2",
        description="Start, watch, and schedule FN2 AI research agents.",
    )
    parser.add_argument("--version", action="version",
                        version=f"fn2-skill {__version__}")
    parser.add_argument("--base-url",
                        help="override the FN2 AI endpoint (or set FN2_BASE_URL)")
    parser.add_argument("--json", action="store_true", help="emit raw JSON")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto",
                        help="colourise output (default: only when writing to a "
                             "terminal; NO_COLOR is always honoured)")
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
    p.add_argument("--no-wait", action="store_true",
                   help="print the code, open the browser, and exit without "
                        "waiting; a later `auth login` resumes and finishes")
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

    p = add("link", cmd_link, "put an `fn2` launcher on your PATH")
    p.add_argument("--dir", help="bin directory to install into (default: the "
                                 "first writable one already on PATH)")

    p = add("unlink", cmd_unlink, "remove the launcher `fn2 link` installed")
    p.add_argument("--dir", help="where it was installed")

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
    p.add_argument("--email", action="store_true",
                   help="email each completed run to your verified account address")
    p.add_argument("--wait", action="store_true",
                   help="when it runs now, block until the run finishes and "
                        "print the result")
    p.add_argument("--timeout", type=float, default=300.0, metavar="SECONDS",
                   help="how long --wait blocks (default: 300)")

    p = add("agents", cmd_agents, "list your agents", aliases=("list", "ls"))
    p.add_argument("--status", help="filter by status (active, paused, …)")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--offset", type=int, default=0)

    p = add("status", cmd_status, "overview of all agents, or detail for one")
    p.add_argument("agent_id", nargs="?",
                   help="id, id prefix, or name (omit for the overview)")
    p.add_argument("--runs", type=int, default=5, help="recent runs to show (detail view)")
    p.add_argument("--limit", type=int, default=50, help="agents to show (overview)")

    p = add("run", cmd_run, "trigger an agent immediately")
    p.add_argument("agent_id", help="id, id prefix, or name")
    p.add_argument("--wait", action="store_true",
                   help="block until the run finishes and print the result")
    p.add_argument("--timeout", type=float, default=300.0, metavar="SECONDS",
                   help="how long --wait blocks (default: 300)")
    add_json(p)

    p = add("runs", cmd_runs, "list an agent's runs")
    p.add_argument("agent_id", help="id, id prefix, or name")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)

    p = add("result", cmd_result, "show one run's outcome and output")
    p.add_argument("agent_id", help="id, id prefix, or name")
    p.add_argument("run_id", nargs="?", default="latest",
                   help="run id (default: the most recent run)")

    p = add("pause", cmd_pause, "pause a scheduled agent")
    p.add_argument("agent_id", help="id, id prefix, or name")

    p = add("resume", cmd_resume, "resume a paused agent")
    p.add_argument("agent_id", help="id, id prefix, or name")

    p = add("schedule", cmd_schedule, "change an agent's cadence")
    p.add_argument("agent_id", help="id, id prefix, or name")
    p.add_argument("when", help="new cadence (see `start --when`)")
    p.add_argument("--tz", help="IANA timezone")
    p.add_argument("--ends", metavar="YYYY-MM-DD")

    p = add("delete", cmd_delete, "delete an agent and its history", aliases=("rm",))
    p.add_argument("agent_id", help="id, id prefix, or name")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    # The CLI is routinely driven by an assistant through a pipe, where Python
    # block-buffers stdout: a sign-in code would sit invisible in the buffer
    # exactly when the user needs it. Force line buffering; streams that cannot
    # reconfigure (StringIO under test, exotic wrappers) keep their behaviour.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)
        except Exception:
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    # --json is machine-readable by contract, so it is never colourised.
    style.set_mode("never" if getattr(args, "json", False)
                   else getattr(args, "color", "auto"))
    try:
        return args.func(args)
    except AuthError as exc:
        print(f"error: {config.redact(str(exc))}", file=sys.stderr)
        print("your credential may be revoked or out of scope; run `fn2 auth login` again.",
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
