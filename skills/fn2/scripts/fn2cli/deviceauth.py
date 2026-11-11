"""Device-authorization flow client (RFC 8628-shaped).

Maps the three CLI-facing endpoints from the frozen contract
(docs/skill-device-auth.md §3 in stock-server):

    POST /api/v1/skill/device-auth/start    -> device_code / user_code / interval
    POST /api/v1/skill/device-auth/poll     -> pending | slow_down | approved |
                                               denied | expired
    POST /api/v1/skill/device-auth/logout   -> self-revoke the device credential

No printing here — the CLI owns all output. The poll loop honours the
server-provided interval, escalates on ``slow_down``, and bounds the total
wait to the request lifetime plus a small grace.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, Iterable, Optional

from . import __version__

START_PATH = "/api/v1/skill/device-auth/start"
POLL_PATH = "/api/v1/skill/device-auth/poll"
LOGOUT_PATH = "/api/v1/skill/device-auth/logout"

CLIENT_ID = "fn2-skill"
# `research` is the read-only market-data surface (earnings, transcripts,
# prices, financials, FRED, saved memory). Sign-ins made before 0.8.0 asked
# for the first two only; the CLI tells those users to sign in again when a
# research command comes back 403.
DEFAULT_SCOPES = ("agents", "models", "research")
DEFAULT_INTERVAL = 5
GRACE_SECONDS = 30
# Hard ceiling on any single sleep. The server caps its slow_down bump at 30s
# (contract §7); we allow a little headroom but never trust the wire value
# unbounded — a compromised/buggy backend must not be able to wedge the CLI.
MAX_INTERVAL = 60

_TERMINAL_STATUSES = frozenset({"approved", "denied", "expired"})


def detect_harness(environ: Optional[Dict[str, str]] = None) -> str:
    """Best-effort detection of the hosting assistant from the environment."""
    env = os.environ if environ is None else environ
    if "CLAUDECODE" in env or "CLAUDE_CODE" in env:
        return "claude"
    if any(key.startswith("CODEX_") for key in env):
        return "codex"
    if any(key.startswith(("HERMES_", "PI_")) for key in env):
        return "pi"
    return "other"


def detect_os(platform: Optional[str] = None) -> str:
    plat = platform if platform is not None else sys.platform
    if plat == "darwin":
        return "macos"
    if plat.startswith("linux"):
        return "linux"
    if plat in ("win32", "cygwin"):
        return "windows"
    return "other"


def start(client, *, harness: Optional[str] = None, client_os: Optional[str] = None,
          scopes: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Open a device-authorization request. Unauthenticated by design."""
    body = {
        "client": CLIENT_ID,
        "client_version": __version__,
        "harness": harness or detect_harness(),
        "os": client_os or detect_os(),
        "scopes": list(scopes) if scopes else list(DEFAULT_SCOPES),
    }
    return client.post(START_PATH, body=body, auth=False)


def poll(client, device_code: str) -> Dict[str, Any]:
    return client.post(POLL_PATH, body={"device_code": device_code}, auth=False)


def logout(client) -> Dict[str, Any]:
    """Self-revoke the device credential the client is configured with."""
    return client.post(LOGOUT_PATH, auth=True)


def poll_until_complete(client, device_code: str, *, interval: Any = DEFAULT_INTERVAL,
                        deadline: Optional[float] = None, sleep=time.sleep,
                        now=time.time) -> Dict[str, Any]:
    """Poll until a terminal status, honouring interval + slow_down.

    ``deadline`` is an absolute epoch (the request's ``expires_at``); the loop
    stops ``GRACE_SECONDS`` past it and reports ``expired`` locally so a dead
    request can never spin forever. A ``KeyboardInterrupt`` propagates — the
    pending-state file survives, so ``fn2 auth login`` resumes.
    """
    def _clamp(value: Any) -> int:
        """Bound a server-supplied interval into [1, MAX_INTERVAL], never trusting
        the wire value unbounded, and never letting one sleep outlive the deadline."""
        try:
            secs = max(1, int(value))
        except (TypeError, ValueError):
            secs = DEFAULT_INTERVAL
        secs = min(secs, MAX_INTERVAL)
        if deadline is not None:
            remaining = (deadline + GRACE_SECONDS) - now()
            if remaining <= 0:
                return 0
            secs = min(secs, max(1, int(remaining)))
        return secs

    wait = _clamp(interval)

    while True:
        if deadline is not None and now() >= deadline + GRACE_SECONDS:
            return {"status": "expired"}
        sleep(wait)
        response = poll(client, device_code)
        # The poll contract is "200 always with a {status: …} object"; a truthy
        # non-dict body (compromised/buggy backend) must not crash the loop.
        if not isinstance(response, dict):
            response = {}
        status = response.get("status")
        if status == "slow_down":
            # Re-read the server's (bumped) interval; fall back to +5s per RFC 8628.
            bumped = response.get("interval")
            wait = _clamp(bumped if bumped else wait + 5)
            continue
        if status in _TERMINAL_STATUSES:
            return response
        # authorization_pending (or an unknown future status) -> keep waiting.
        wait = _clamp(wait)
