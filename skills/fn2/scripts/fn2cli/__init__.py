"""fn2cli — a dependency-free client for the fn2.ai public agents API.

The package is intentionally split into single-responsibility modules so the
skill stays easy to audit:

    config     credential + base-URL resolution, origin pinning, redaction
    storage    macOS Keychain / owner-only file backends + pending-login state
    deviceauth the browser device-authorization flow (start / poll / logout)
    client     the thin urllib HTTP layer and error types
    api        one function per fn2 endpoint, no formatting
    schedule   natural-language cadence -> fn2 schedule object
    render     human/JSON output helpers
    cli        argument parsing and command dispatch

Nothing here imports anything outside the Python standard library.
"""

from __future__ import annotations

__version__ = "0.4.0"

__all__ = ["__version__"]
