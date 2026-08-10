"""Credential and endpoint resolution + origin pinning + redaction.

Credential precedence, highest first:

    1. ``FN2_API_TOKEN`` in the process environment (canonical headless
       override; accepts device tokens ``fn2d_…`` and API keys ``fn2_…``)
    2. ``FN2_API_KEY`` in the environment (legacy alias)
    3. the macOS Keychain (service ``fn2-skill``) when available
    4. ``~/.config/fn2/credentials.json`` (``$FN2_CONFIG_HOME`` honoured)

There is **no** ``.env`` support — dotenv reading was removed in 0.2.0 so a
working-directory file can never inject a credential or endpoint.

Origin pinning: the API base must be ``https://`` on ``fn2.ai`` or a
``*.fn2.ai`` subdomain. Anything else is refused (the credential is never
sent there) unless ``FN2_ALLOW_DEV_BASE=1``, which prints a loud warning.
"""

from __future__ import annotations

import os
import re
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import storage

DEFAULT_BASE_URL = "https://fn2.ai"
# Friendly entry point printed during onboarding. A single constant so the
# hosted page can be re-pointed without code changes.
DEFAULT_ONBOARD_URL = "https://fn2.ai/start"
KEY_PREFIX = "fn2_"
DEVICE_TOKEN_PREFIX = "fn2d_"
DEVICE_CODE_PREFIX = "fn2dc_"

PINNED_HOST = "fn2.ai"

_ENV_API_TOKEN = "FN2_API_TOKEN"
_ENV_API_KEY = "FN2_API_KEY"  # legacy alias
_ENV_BASE_URL = "FN2_BASE_URL"
_ENV_ONBOARD_URL = "FN2_ONBOARD_URL"
_ENV_ALLOW_DEV_BASE = "FN2_ALLOW_DEV_BASE"

# Order matters: the device-code prefix contains the device-token prefix.
_MASK_PREFIXES = (DEVICE_CODE_PREFIX, DEVICE_TOKEN_PREFIX, KEY_PREFIX)
_SECRET_RE = re.compile(r"fn2(?:dc|d)?_[A-Za-z0-9_\-]{8,}")


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings for a single invocation."""

    api_key: Optional[str]
    base_url: str
    onboard_url: str
    source: str  # "env", "env-legacy", "keychain", "file", or "none"

    @property
    def authenticated(self) -> bool:
        return bool(self.api_key)

    @property
    def credential_kind(self) -> str:
        if not self.api_key:
            return "none"
        if self.api_key.startswith(DEVICE_TOKEN_PREFIX):
            return "device"
        return "api_key"


def config_home() -> Path:
    return storage.config_home()


def credentials_path() -> Path:
    return storage.credentials_path()


def resolve() -> Settings:
    """Collapse env, keychain, and the credentials file into one Settings."""
    record = storage.load_record()

    base_url = (
        os.environ.get(_ENV_BASE_URL)
        or record.get("base_url")
        or DEFAULT_BASE_URL
    ).rstrip("/")

    api_key: Optional[str] = None
    source = "none"
    if os.environ.get(_ENV_API_TOKEN, "").strip():
        api_key, source = os.environ[_ENV_API_TOKEN].strip(), "env"
    elif os.environ.get(_ENV_API_KEY, "").strip():
        api_key, source = os.environ[_ENV_API_KEY].strip(), "env-legacy"
    else:
        token, token_source = storage.stored_token(base_url)
        if token:
            api_key, source = token, token_source or "file"

    onboard_url = os.environ.get(_ENV_ONBOARD_URL) or DEFAULT_ONBOARD_URL

    return Settings(api_key=api_key or None, base_url=base_url,
                    onboard_url=onboard_url, source=source)


# ---------------------------------------------------------------------------
# origin pinning
# ---------------------------------------------------------------------------
def origin_pinned(base_url: str) -> bool:
    """True when the URL is https:// on fn2.ai or a *.fn2.ai subdomain."""
    parts = urllib.parse.urlsplit(base_url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (
        host == PINNED_HOST or host.endswith("." + PINNED_HOST)
    )


def dev_base_allowed() -> bool:
    return os.environ.get(_ENV_ALLOW_DEV_BASE) == "1"


def origin_verdict(base_url: str) -> str:
    """"pinned" | "dev-allowed" | "refused" — non-fatal, for `fn2 doctor`."""
    if origin_pinned(base_url):
        return "pinned"
    if dev_base_allowed():
        return "dev-allowed"
    return "refused"


def enforce_base_url(base_url: str) -> None:
    """Hard-stop before any credential could travel to a non-pinned origin."""
    verdict = origin_verdict(base_url)
    if verdict == "pinned":
        return
    if verdict == "dev-allowed":
        print(
            f"WARNING: FN2_ALLOW_DEV_BASE=1. Talking to UNPINNED endpoint {base_url}.\n"
            "         Your FN2 AI credential will be sent there. Only do this against a\n"
            "         development server you control.",
            file=sys.stderr,
        )
        return
    raise SystemExit(
        f"error: refusing endpoint {base_url!r}. FN2 AI credentials are only sent to "
        f"https://{PINNED_HOST} (or *.{PINNED_HOST}).\n"
        "For local development against a server you control, set FN2_ALLOW_DEV_BASE=1."
    )


# ---------------------------------------------------------------------------
# credential persistence (thin wrappers over storage, kept for the manual path)
# ---------------------------------------------------------------------------
def save_token(token: str, base_url: Optional[str] = None) -> Path:
    """Persist an API key via the storage priority. Returns the record path."""
    storage.store_credential(token.strip(), base_url=(base_url or DEFAULT_BASE_URL),
                             kind="api_key")
    return storage.credentials_path()


def clear_token(base_url: Optional[str] = None) -> bool:
    return storage.clear_credential(base_url or DEFAULT_BASE_URL)


# ---------------------------------------------------------------------------
# shapes, masking, redaction
# ---------------------------------------------------------------------------
def looks_like_key(token: str) -> bool:
    """A personal API key (the manual `login --token` path)."""
    return bool(token) and token.strip().startswith(KEY_PREFIX)


def looks_like_credential(token: str) -> bool:
    """Any bearer credential we accept: device token or API key."""
    stripped = (token or "").strip()
    return stripped.startswith(DEVICE_TOKEN_PREFIX) or stripped.startswith(KEY_PREFIX)


def mask(token: Optional[str]) -> str:
    """Render a credential as ``fn2d_…wxyz`` — safe for logs and output."""
    if not token:
        return "(none)"
    token = token.strip()
    for prefix in _MASK_PREFIXES:
        if token.startswith(prefix):
            if len(token) <= len(prefix) + 8:
                return prefix + "…"
            return f"{prefix}…{token[-4:]}"
    if len(token) <= 8:
        return KEY_PREFIX + "…"
    return f"{token[:4]}…{token[-4:]}"


def redact(text: str) -> str:
    """Mask every fn2 secret-shaped substring in arbitrary text."""
    if not text:
        return text
    return _SECRET_RE.sub(lambda m: mask(m.group(0)), text)
