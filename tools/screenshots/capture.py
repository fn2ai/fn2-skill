"""Run the real fn2 CLI against demo fixtures and capture its output.

Nothing here re-implements the CLI. `fn2cli.cli.main()` is invoked exactly as a
shell would invoke it; only two seams are swapped:

  * `Client._urlopen` — the transport seam the unit tests already use — answers
    from `fixtures.build()` instead of the network.
  * the macOS Keychain adapter is simulated in memory, so the captured output
    shows the backend a Mac user actually gets.

Everything else — argument parsing, schedule translation, storage, redaction,
table layout — is the shipped code. The text in `docs/media/` is therefore the
program's own output, not a mockup.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "fn2" / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures  # noqa: E402  (path set above)
from fn2cli import cli, client as client_mod, deviceauth, storage  # noqa: E402


class _Tty(io.StringIO):
    """A capture buffer that claims to be a terminal, like the real thing."""

    def isatty(self) -> bool:
        return True


class _Response:
    """The subset of an http.client.HTTPResponse that Client.request touches."""

    def __init__(self, payload: Any, status: int = 200):
        self._raw = json.dumps(payload).encode("utf-8")
        self._status = status

    def read(self) -> bytes:
        return self._raw

    def getcode(self) -> int:
        return self._status

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


class DemoBackend:
    """Routes the CLI's HTTP calls onto the fixture data."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self._poll = list(data["device_poll"])
        self._created = 0

    def __call__(self, request: Any) -> _Response:
        # Bound onto Client as a plain attribute, so `self` is never passed.
        method = request.get_method()
        parts = urllib.parse.urlsplit(request.full_url)
        path = parts.path
        body = json.loads(request.data.decode("utf-8")) if request.data else {}
        return _Response(self.route(method, path, body))

    # -- routing ---------------------------------------------------------
    def route(self, method: str, path: str, body: Dict[str, Any]) -> Any:
        d = self.data
        segments = [s for s in path.split("/") if s]

        if path.endswith("/skill/device-auth/start"):
            return d["device_start"]
        if path.endswith("/skill/device-auth/poll"):
            return self._poll.pop(0) if len(self._poll) > 1 else self._poll[0]
        if path.endswith("/skill/device-auth/logout"):
            return {"revoked": True}
        if path.endswith("/public-config"):
            return {"app": "fn2", "signup_enabled": True}
        if path.endswith("/api/v1/usage"):
            return d["usage"]
        if path.endswith("/api/v1/models"):
            return d["models"]

        # /api/v1/agents...
        if "agents" in segments:
            tail = segments[segments.index("agents") + 1:]
            if not tail:
                if method == "POST":
                    return self._create(body)
                return {"agents": d["agents"], "total": len(d["agents"])}
            agent_id = tail[0]
            agent = d["agent_by_id"].get(agent_id, d["agents"][0])
            if len(tail) == 1:
                if method == "PATCH":
                    return {**agent, **body}
                if method == "DELETE":
                    return {}
                return agent
            if tail[1] == "run":
                return d["queued_run"]
            if tail[1] == "runs":
                if len(tail) > 2:
                    return d["run_detail"]
                return {"runs": d["runs"], "has_more": True}
        raise AssertionError(f"no demo fixture for {method} {path}")

    def _create(self, body: Dict[str, Any]) -> Dict[str, Any]:
        created = dict(self.data["created_agent"])
        ids = self.data["created_ids"]
        created["id"] = ids[self._created % len(ids)]
        self._created += 1
        if body.get("schedule"):
            created["schedule"] = {**created.get("schedule", {}), **body["schedule"]}
        if body.get("name"):
            created["name"] = body["name"]
        return created


@contextlib.contextmanager
def demo_environment(home: Path, now: Optional[dt.datetime] = None):
    """Patch the two seams, point storage at `home`, and yield a runner."""
    now = now or dt.datetime.now(dt.timezone.utc)
    data = fixtures.build(now)
    backend = DemoBackend(data)

    config_home = home / ".config" / "fn2"
    config_home.mkdir(parents=True, exist_ok=True)
    os.chmod(config_home, 0o700)

    saved_env = {k: os.environ.get(k) for k in
                 ("FN2_API_TOKEN", "FN2_API_KEY", "FN2_CONFIG_HOME", "FN2_BASE_URL")}
    os.environ.pop("FN2_API_TOKEN", None)
    os.environ.pop("FN2_API_KEY", None)
    os.environ.pop("FN2_BASE_URL", None)
    os.environ["FN2_CONFIG_HOME"] = str(config_home)

    keyring: Dict[str, str] = {}
    saved = (
        client_mod.Client._urlopen,
        storage.keychain_available,
        storage.keychain_store,
        storage.keychain_read,
        storage.keychain_delete,
        deviceauth.poll_until_complete,
        cli._open_browser,
    )
    client_mod.Client._urlopen = backend
    storage.keychain_available = lambda: True
    storage.keychain_store = lambda account, secret: keyring.__setitem__(account, secret)
    storage.keychain_read = lambda account: keyring.get(account)
    storage.keychain_delete = lambda account: keyring.pop(account, None) is not None
    _poll_until_complete = saved[5]
    deviceauth.poll_until_complete = (
        lambda *a, **kw: _poll_until_complete(*a, **{**kw, "sleep": lambda _s: None})
    )
    cli._open_browser = lambda _uri: True

    # Start each session already connected, the way a returning user is. The
    # `auth login` scene simply signs in again over the top.
    approved = data["device_poll"][-1]
    storage.store_credential(
        data["token"], base_url="https://fn2.ai", kind="device",
        extra={"scopes": approved["scopes"], "device_id": approved["device_id"],
               "expires_at": approved["expires_at"],
               "account": fixtures.DEMO_ACCOUNT},
    )

    try:
        yield _Runner(data)
    finally:
        (client_mod.Client._urlopen, storage.keychain_available, storage.keychain_store,
         storage.keychain_read, storage.keychain_delete, deviceauth.poll_until_complete,
         cli._open_browser) = saved
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class _Runner:
    """Invokes `fn2 <argv>` and returns exactly what the user would see."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data

    def run(self, argv: List[str]) -> str:
        out = _Tty()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                cli.main(argv)
            except SystemExit as exc:  # argparse/`raise SystemExit(msg)`
                if exc.code not in (0, None) and isinstance(exc.code, str):
                    out.write(str(exc.code) + "\n")
        return out.getvalue().rstrip("\n")


def run_session(commands: List[Tuple[str, List[str]]], *, home: Path,
                now: Optional[dt.datetime] = None,
                before: Optional[Callable[[_Runner], None]] = None,
                ) -> List[Dict[str, str]]:
    """Run `commands` in one demo environment. Returns [{command, output}]."""
    with demo_environment(home, now) as runner:
        if before is not None:
            before(runner)
        return [{"command": shown, "output": runner.run(argv)}
                for shown, argv in commands]
