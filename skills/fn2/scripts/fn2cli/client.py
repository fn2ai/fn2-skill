"""The HTTP layer: one small class over ``urllib`` with typed errors.

Everything network-facing lives here so the rest of the package never touches
``urllib`` directly and stays trivially testable (the tests swap ``_urlopen``).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from . import __version__

_TIMEOUT_SECONDS = 45
_USER_AGENT = f"fn2-skill/{__version__} (+https://fn2.ai)"


class ApiError(RuntimeError):
    """A structured failure from the fn2 API or the transport beneath it."""

    def __init__(self, message: str, *, status: Optional[int] = None,
                 code: Optional[str] = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.payload = payload
        self.retry_after: Optional[Any] = None
        self.request_id: Optional[str] = None

    def __str__(self) -> str:
        # Belt to _http_error's braces. An error path that raises while being
        # rendered turns a handled failure into a traceback, which is the one
        # thing an error type must never do — so coerce rather than assume the
        # message is a string.
        prefix = f"HTTP {self.status}: " if self.status else ""
        return prefix + (str(self.args[0]) if self.args else "request failed")


class AuthError(ApiError):
    """Raised on 401/403 so the CLI can point the user at ``fn2 login``."""


class Client:
    """A thin, reusable fn2 API client.

    Parameters
    ----------
    base_url:
        Root of the deployment, e.g. ``https://fn2.ai``.
    api_key:
        A ``fn2_...`` key. Optional so public endpoints (none today, but the
        auth routes exist) can be reached without one.
    """

    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    # -- transport -------------------------------------------------------
    def _urlopen(self, request: urllib.request.Request):
        # Seam for tests; never call urllib elsewhere.
        return urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS)

    def request(self, method: str, path: str, *, body: Optional[dict] = None,
                auth: bool = True, params: Optional[dict] = None) -> Any:
        url = self.base_url + path
        if params:
            query = urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )
            if query:
                url = f"{url}?{query}"

        headers = {"Accept": "application/json", "User-Agent": _USER_AGENT}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if auth:
            if not self.api_key:
                raise AuthError(
                    "no FN2 AI credential configured; run `fn2 auth login` first",
                    status=401, code="no_credentials",
                )
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._urlopen(req) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                status = resp.getcode()
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except urllib.error.URLError as exc:
            raise ApiError(f"could not reach {self.base_url}: {exc.reason}",
                           code="network") from exc

        if status == 204 or not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ApiError(f"fn2 returned non-JSON ({status}): {raw[:280]}",
                           status=status, code="bad_response") from exc

    def _http_error(self, exc: urllib.error.HTTPError) -> ApiError:
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - defensive
            pass
        payload: Any = None
        message = exc.reason or "request failed"
        code = None
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                message = raw[:280]
        retry_after = None
        request_id = exc.headers.get("X-Request-Id") if exc.headers else None
        if isinstance(payload, dict):
            # TWO error envelopes reach this client and they disagree about
            # what `error` holds:
            #
            #   Flask  {"error": "Agent not found", "code": "not_found"}
            #   nginx  {"error": true, "message": "No token provided",
            #           "code": "UNAUTHORIZED"}
            #
            # The gateway's `error` is a BOOLEAN FLAG, not the text. Taking it
            # verbatim put `True` in the message and every later `str(exc)`
            # raised `TypeError: can only concatenate str (not "bool")` — so
            # any gateway-originated failure crashed the CLI with a traceback
            # instead of printing the reason. Accept `error` only when it is
            # actually a string; otherwise fall through to `message`.
            for key in ("error", "message"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    message = value
                    break
            code = payload.get("code")
            retry_after = payload.get("retry_after")
            request_id = payload.get("request_id") or request_id
        if retry_after is None and exc.headers:
            retry_after = exc.headers.get("Retry-After")
        # Say WHEN to try again rather than leaving the caller to guess.
        if retry_after:
            message = f"{message} (retry after {retry_after}s)"
        if request_id and exc.code >= 500:
            message = f"{message} [request {request_id}]"
        cls = AuthError if exc.code in (401, 403) else ApiError
        error = cls(str(message), status=exc.code, code=code, payload=payload)
        error.retry_after = retry_after
        error.request_id = request_id
        return error

    # -- verb sugar ------------------------------------------------------
    def get(self, path: str, **kw) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Optional[dict] = None, **kw) -> Any:
        return self.request("POST", path, body=body, **kw)

    def patch(self, path: str, body: Optional[dict] = None, **kw) -> Any:
        return self.request("PATCH", path, body=body, **kw)

    def delete(self, path: str, **kw) -> Any:
        return self.request("DELETE", path, **kw)
