"""Credential and pending-login storage.

Two backends, tried in priority order:

    1. macOS Keychain via the ``security`` CLI (service ``fn2-skill``,
       account = the API base host). Used when running on darwin and the
       ``security`` binary is on PATH.
    2. An owner-only file: ``~/.config/fn2/credentials.json`` (honours
       ``FN2_CONFIG_HOME``), directory ``0700``, file ``0600``, symlinks
       refused, permissions re-checked on every read.

The credentials file always exists once signed in — it carries the non-secret
metadata (base URL, scopes, expiry, backend marker). The secret itself lives in
the Keychain when available, otherwise inline in the file.

A separate pending-login state file (``device_login_pending.json``, ``0600``)
lets an interrupted ``fn2 auth login`` resume deterministically. It stores the
device_code / user_code / expiry / interval — **never** an access token.

Keychain subprocess hygiene: the secret must never appear in argv (argv is
world-readable via ``ps``). ``security -i`` reads its command line from stdin,
so writes go through stdin only. Reads use ``find-generic-password -w`` where
the secret only ever appears on the child's stdout.
"""

from __future__ import annotations

import errno
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

KEYCHAIN_SERVICE = "fn2-skill"
PENDING_FILENAME = "device_login_pending.json"

_ENV_CONFIG_HOME = "FN2_CONFIG_HOME"

# Conservative allowlist for values embedded in the `security -i` script line.
# fn2 tokens are prefix + base62/base64url; hosts are DNS labels.
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.\-]+$")


class StorageError(RuntimeError):
    """A storage backend refused to read or write."""


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------
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


def pending_path() -> Path:
    return config_home() / PENDING_FILENAME


def host_of(base_url: str) -> str:
    return (urllib.parse.urlsplit(base_url).hostname or "").lower()


# ---------------------------------------------------------------------------
# macOS Keychain adapter (via the `security` CLI)
# ---------------------------------------------------------------------------
def keychain_available() -> bool:
    return sys.platform == "darwin" and shutil.which("security") is not None


def _run_security(argv, *, input_text: Optional[str] = None) -> "subprocess.CompletedProcess":
    return subprocess.run(
        argv,
        input=input_text.encode("utf-8") if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def keychain_store(account: str, secret: str) -> None:
    """Store the secret. The secret travels via stdin (`security -i`), not argv."""
    for value, what in ((account, "account"), (secret, "credential")):
        if not value or not _SAFE_VALUE.match(value):
            raise StorageError(f"refusing to store: unexpected characters in {what}")
    script = (
        f'add-generic-password -U -s "{KEYCHAIN_SERVICE}" -a "{account}" -w "{secret}"\n'
    )
    proc = _run_security(["security", "-i"], input_text=script)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise StorageError(f"keychain write failed: {detail or 'security exited non-zero'}")


def keychain_read(account: str) -> Optional[str]:
    if not account or not _SAFE_VALUE.match(account):
        return None
    proc = _run_security(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"]
    )
    if proc.returncode != 0:
        return None
    token = proc.stdout.decode("utf-8", errors="replace").strip()
    return token or None


def keychain_delete(account: str) -> bool:
    if not account or not _SAFE_VALUE.match(account):
        return False
    proc = _run_security(
        ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account]
    )
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# owner-only JSON files (credentials + pending state)
# ---------------------------------------------------------------------------
def _read_owner_json(path: Path) -> Dict[str, Any]:
    if path.is_symlink():
        _warn(f"{path} is a symlink; refusing to read it. Remove the link and retry.")
        return {}
    try:
        mode = os.stat(path).st_mode & 0o777
    except (FileNotFoundError, NotADirectoryError, OSError):
        return {}
    if mode & 0o077:
        _warn(
            f"{path} is group/world-accessible (mode {mode:03o}). "
            f"Fix with: chmod 600 {path}  (see `fn2 doctor`)"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
        return {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_owner_json(path: Path, payload: Dict[str, Any]) -> Path:
    home = path.parent
    home.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(home, 0o700)
    except OSError as exc:
        # A pre-existing dir we cannot tighten (e.g. owned by another user) is a
        # real exposure for a credential file — fail loudly, don't write blind.
        raise StorageError(
            f"Cannot secure {home} (chmod 700 failed: {exc}). "
            f"Move FN2_CONFIG_HOME somewhere you own and retry."
        )
    # The parent must be a directory you exclusively own: reject a symlinked or
    # group/world-writable parent so a local attacker can't pre-stage the target.
    try:
        st = os.lstat(home)
    except OSError as exc:
        raise StorageError(f"Cannot stat {home}: {exc}")
    if stat.S_ISLNK(st.st_mode):
        raise StorageError(f"{home} is a symlink; refusing to write into it.")
    if st.st_mode & 0o022:
        raise StorageError(
            f"{home} is group/world-writable (mode {st.st_mode & 0o777:03o}). "
            f"Fix with: chmod 700 {home}"
        )
    # O_NOFOLLOW closes the check-then-open race: if `path` is (or becomes) a
    # symlink, the open fails with ELOOP instead of following it to an attacker
    # target. O_CREAT|0600 keeps contents from ever being briefly world-readable.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags, 0o600)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise StorageError(
                f"{path} is a symlink; refusing to write through it. Remove the link and retry."
            )
        raise
    # os.fdopen takes ownership of fd and closes it on context exit (incl. errors).
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _unlink(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# credential record
# ---------------------------------------------------------------------------
def load_record() -> Dict[str, Any]:
    """Non-secret credential metadata (may include the token on the file backend)."""
    return _read_owner_json(credentials_path())


def save_record(record: Dict[str, Any]) -> Path:
    return _write_owner_json(credentials_path(), record)


def describe_backend(backend: str) -> str:
    if backend == "keychain":
        return f"macOS Keychain (service '{KEYCHAIN_SERVICE}')"
    return str(credentials_path())


def store_credential(token: str, *, base_url: str, kind: str,
                     extra: Optional[Dict[str, Any]] = None) -> str:
    """Persist a credential using the backend priority. Returns the backend name."""
    token = token.strip()
    record: Dict[str, Any] = {"kind": kind, "base_url": base_url.rstrip("/")}
    if extra:
        record.update({k: v for k, v in extra.items() if v is not None})
    record.pop("api_key", None)
    record.pop("access_token", None)
    if keychain_available():
        keychain_store(host_of(base_url), token)
        record["storage"] = "keychain"
    else:
        record["storage"] = "file"
        record["api_key"] = token
    save_record(record)
    return record["storage"]


def stored_token(base_url: str) -> Tuple[Optional[str], Optional[str]]:
    """Read the stored credential: keychain first, then the file. -> (token, source)."""
    if keychain_available():
        token = keychain_read(host_of(base_url))
        if token:
            return token, "keychain"
    record = load_record()
    token = str(record.get("api_key") or "").strip()
    if token:
        return token, "file"
    return None, None


def clear_credential(base_url: str) -> bool:
    """Delete the stored credential everywhere. Returns True if anything was removed."""
    removed = False
    if keychain_available():
        removed = keychain_delete(host_of(base_url)) or removed
    removed = _unlink(credentials_path()) or removed
    return removed


# ---------------------------------------------------------------------------
# pending device-login state
# ---------------------------------------------------------------------------
def save_pending(state: Dict[str, Any]) -> Path:
    """Persist resumable login state. The access token must never land here."""
    forbidden = {"access_token", "token", "api_key"}
    if forbidden & set(state):
        raise StorageError("pending-login state must never contain a credential")
    return _write_owner_json(pending_path(), state)


def load_pending() -> Optional[Dict[str, Any]]:
    state = _read_owner_json(pending_path())
    return state or None


def clear_pending() -> bool:
    return _unlink(pending_path())
