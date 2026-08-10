"""ANSI styling for the human views. Presentation only, and off by default.

Colour is enabled when stdout is a terminal and nothing has asked us not to.
Precedence, highest first:

    1. an explicit ``--color always|never`` (``set_mode``)
    2. ``NO_COLOR`` in the environment  (https://no-color.org)
    3. ``FORCE_COLOR`` in the environment
    4. ``TERM=dumb``
    5. whether ``sys.stdout`` is a tty

Piping to a file or another process therefore yields plain text, and so does
``--json``: every escape sequence enters through :func:`paint`, which returns
its input unchanged when colour is off.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Optional

RESET = "\033[0m"

_CODES = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
}

# Every sequence we emit, so widths can be measured on the visible text.
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

_mode: str = "auto"


def set_mode(mode: Optional[str]) -> None:
    """Set "auto", "always", or "never". Anything else is treated as auto."""
    global _mode
    _mode = mode if mode in ("auto", "always", "never") else "auto"


def enabled() -> bool:
    if _mode == "never":
        return False
    if _mode == "always":
        return True
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("TERM") == "dumb":
        return False
    try:
        return bool(sys.stdout.isatty())
    except (AttributeError, ValueError):  # closed or replaced stream
        return False


def paint(text: str, *styles: str) -> str:
    """Wrap `text` in `styles`, or return it untouched when colour is off."""
    if not text or not styles or not enabled():
        return text
    codes = ";".join(_CODES[s] for s in styles if s in _CODES)
    if not codes:
        return text
    return f"\033[{codes}m{text}{RESET}"


def strip(text: str) -> str:
    return _ANSI_RE.sub("", text)


def width(text: str) -> int:
    """Visible width, ignoring escape sequences, for column padding."""
    return len(strip(text))


def pad(text: str, size: int) -> str:
    """`str.ljust` that counts visible characters only."""
    return text + " " * max(0, size - width(text))


# -- glyphs --------------------------------------------------------------
# A legacy Windows console is cp1252, where printing "✓" raises
# UnicodeEncodeError and takes the whole command down. Ask the stream what it
# can encode and fall back to ASCII rather than crashing on a tick mark.
_GLYPHS = {
    "ok": ("✓", "OK"),
    "pause": ("⏸", "||"),
    "play": ("▶", ">"),
    "trash": ("🗑", "x"),
    "star": ("★", "*"),
    "ellipsis": ("…", "..."),
}

_unicode_ok: Optional[bool] = None


def unicode_safe() -> bool:
    """Whether stdout can encode the glyphs above."""
    global _unicode_ok
    if _unicode_ok is None:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        try:
            "".join(fancy for fancy, _ in _GLYPHS.values()).encode(encoding)
            _unicode_ok = True
        except (UnicodeEncodeError, LookupError):
            _unicode_ok = False
    return _unicode_ok


def glyph(name: str) -> str:
    fancy, plain = _GLYPHS[name]
    return fancy if unicode_safe() else plain


def reset_glyph_cache() -> None:
    """Re-probe the stream. Only tests need this."""
    global _unicode_ok
    _unicode_ok = None


# -- semantic helpers ----------------------------------------------------
_STATUS_STYLES = {
    "active": ("green",),
    "running": ("green",),
    "completed": ("blue",),
    "queued": ("cyan",),
    "pending": ("cyan",),
    "paused": ("yellow",),
    "failed": ("red",),
    "error": ("red",),
    "cancelled": ("dim",),
}


def status(value: str) -> str:
    return paint(str(value), *_STATUS_STYLES.get(str(value).lower(), ("dim",)))


def label(text: str) -> str:
    return paint(text, "dim")


def ok(text: str) -> str:
    return paint(text, "green")


def bad(text: str) -> str:
    return paint(text, "red")


def head(text: str) -> str:
    return paint(text, "bold")


def tick() -> str:
    return ok(glyph("ok"))
