"""Credential and endpoint resolution.

Precedence, highest first:

    1. ``FN2_API_KEY`` in the process environment
    2. a ``.env`` file (``$FN2_DOTENV`` or ``./.env``)
    3. the credentials file (``$FN2_CONFIG_HOME`` or ``~/.config/fn2/credentials.json``)

The credentials file is the recommended home for the key: it is written with
``0600`` permissions so it never lands in shell history or a shared ``.env``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

DEFAULT_BASE_URL = "https://fn2.ai"
# Friendly entry point printed during onboarding. It is deliberately a single
# constant so the hosted short link can be re-pointed without code changes.
DEFAULT_ONBOARD_URL = "https://fn2.ai/skill"
KEY_PREFIX = "fn2_"

_ENV_API_KEY = "FN2_API_KEY"
_ENV_BASE_URL = "FN2_BASE_URL"
_ENV_ONBOARD_URL = "FN2_ONBOARD_URL"
_ENV_DOTENV = "FN2_DOTENV"
_ENV_CONFIG_HOME = "FN2_CONFIG_HOME"


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings for a single invocation."""

    api_key: Optional[str]
    base_url: str
    onboard_url: str
    source: str  # where the key came from: "env", "dotenv", "file", or "none"

    @property
    def authenticated(self) -> bool:
        return bool(self.api_key)


def config_home() -> Path:
    """Directory that holds fn2 state, honouring XDG conventions."""
    override = os.environ.get(_ENV_CONFIG_HOME)
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "fn2"


def credentials_path() -> Path:
    return config_home() / "credentials.json"


def _parse_dotenv(text: str) -> Dict[str, str]:
    """Parse a minimal ``KEY=VALUE`` .env file. Comments and blanks ignored."""
    values: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def load_dotenv() -> Dict[str, str]:
    """Read the active .env file if one exists; returns an empty dict otherwise."""
    override = os.environ.get(_ENV_DOTENV)
    path = Path(override).expanduser() if override else Path.cwd() / ".env"
    try:
        return _parse_dotenv(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
        return {}


def _load_credentials_file() -> Dict[str, str]:
    try:
        data = json.loads(credentials_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
        return {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def resolve() -> Settings:
    """Collapse env, .env, and the creds file into one immutable Settings."""
    dotenv = load_dotenv()
    creds = _load_credentials_file()

    api_key: Optional[str] = None
    source = "none"
    if os.environ.get(_ENV_API_KEY):
        api_key, source = os.environ[_ENV_API_KEY].strip(), "env"
    elif dotenv.get(_ENV_API_KEY):
        api_key, source = dotenv[_ENV_API_KEY].strip(), "dotenv"
    elif creds.get("api_key"):
        api_key, source = str(creds["api_key"]).strip(), "file"

    base_url = (
        os.environ.get(_ENV_BASE_URL)
        or dotenv.get(_ENV_BASE_URL)
        or creds.get("base_url")
        or DEFAULT_BASE_URL
    ).rstrip("/")

    onboard_url = (
        os.environ.get(_ENV_ONBOARD_URL)
        or dotenv.get(_ENV_ONBOARD_URL)
        or DEFAULT_ONBOARD_URL
    )

    return Settings(api_key=api_key or None, base_url=base_url,
                    onboard_url=onboard_url, source=source)


def save_token(token: str, base_url: Optional[str] = None) -> Path:
    """Persist the API key to the credentials file with strict permissions."""
    token = token.strip()
    home = config_home()
    home.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(home, 0o700)
    except OSError:
        pass  # best effort on filesystems without POSIX modes

    path = credentials_path()
    payload = {"api_key": token}
    if base_url:
        payload["base_url"] = base_url.rstrip("/")

    # Create the file with 0600 before writing so the secret is never briefly
    # world-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def clear_token() -> bool:
    """Delete the stored key. Returns True if a file was removed."""
    path = credentials_path()
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def looks_like_key(token: str) -> bool:
    return bool(token) and token.strip().startswith(KEY_PREFIX)


def mask(token: Optional[str]) -> str:
    """Render a key as ``fn2_...wxyz`` — safe to show in logs and output."""
    if not token:
        return "(none)"
    token = token.strip()
    if len(token) <= 8:
        return KEY_PREFIX + "…"
    return f"{token[:4]}…{token[-4:]}"
