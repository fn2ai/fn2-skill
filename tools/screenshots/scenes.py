"""What each screenshot shows.

A scene is either a `terminal` session (a list of commands whose output is
captured from the real CLI) or a `chat` transcript (an assistant harness
driving the skill, with the tool output likewise captured).
"""

from __future__ import annotations

import textwrap
from typing import Any, Dict, List

import fixtures

AGENT = fixtures.AGENT_SENTIMENT
RUN = fixtures.RUN_LATEST
SHORT = AGENT[:8]

HERO_PROMPT = "Pre-market brief on my watchlist: gaps, news, and what to watch"


def _terminal(name: str, title: str, caption: str,
              commands: List[Any], cols: int = 70) -> Dict[str, Any]:
    return {"name": name, "kind": "terminal", "title": title, "caption": caption,
            "cols": cols, "commands": commands}


def build() -> List[Dict[str, Any]]:
    """Return every scene. `commands` entries are (shown, argv) pairs."""
    return [
        {
            "name": "hero-assistant",
            "kind": "chat",
            "title": "Claude Code · fn2 skill",
            "caption": "Ask in plain English; the skill does the API work.",
            "cols": 86,
            "capture": [
                ("fn2 start \"" + HERO_PROMPT + "\" \\\n      --when \"before market open\" --email",
                 ["start", HERO_PROMPT, "--when", "before market open", "--email"]),
            ],
            "messages": [
                {"role": "user",
                 "text": "schedule a pre-market brief on my watchlist before the open "
                         "and email it to me"},
                {"role": "assistant",
                 "text": "I'll create an fn2 agent on the market-open cadence — it "
                         "resolves against the exchange calendar, so it skips holidays "
                         "and half-days on its own."},
                {"role": "tool", "capture": 0},
                {"role": "assistant",
                 "text": "Done. It runs every trading day 30 minutes before the bell "
                         "and emails the brief to your verified address. Pause it any "
                         "time with \"pause the pre-market brief\"."},
            ],
        },
        _terminal(
            "auth-login", "fn2 auth login",
            "Sign in from the terminal without copying a secret.",
            [("fn2 auth login", ["auth", "login"]),
             ("fn2 auth status", ["auth", "status"])],
        ),
        _terminal(
            "agents", "fn2 agents",
            "Every agent, its cadence, and when it last ran.",
            [("fn2 agents", ["agents"])],
        ),
        _terminal(
            "status", f"fn2 status {SHORT}…",
            "One agent in full: cadence, prompt, and recent runs.",
            [(f"fn2 status {AGENT}", ["status", AGENT, "--runs", "5"])],
        ),
        _terminal(
            "result", "fn2 result",
            "Read a completed run without leaving the terminal.",
            [(f"fn2 result {AGENT} {RUN}", ["result", AGENT, RUN])],
        ),
        _terminal(
            "scheduling", "fn2 start --when",
            "Cadences in plain English, resolved against the exchange calendar.",
            [("fn2 start \"Overnight recap on NVDA and peers\"",
              ["start", "Overnight recap on NVDA and peers"]),
             ("fn2 start \"EOD watchlist recap\" --when \"market close\" --email",
              ["start", "EOD watchlist recap", "--when", "market close", "--email"]),
             ("fn2 start \"Macro digest\" --when \"weekdays at 7am\" --tz America/New_York",
              ["start", "Macro digest", "--when", "weekdays at 7am",
               "--tz", "America/New_York"]),
             (f"fn2 schedule {AGENT} \"hourly\"",
              ["schedule", AGENT, "hourly"])],
        ),
        _terminal(
            "account", "fn2 whoami · fn2 models",
            "Plan, quota, device scopes, and the models you can run on.",
            [("fn2 whoami", ["whoami"]),
             ("fn2 models", ["models"])],
        ),
        _terminal(
            "security", "fn2 permissions · fn2 doctor",
            "A scoped, revocable credential — and a one-command health check.",
            [("fn2 permissions", ["permissions"]),
             ("fn2 doctor", ["doctor"])],
        ),
    ]


def wrap(text: str, cols: int) -> List[str]:
    lines: List[str] = []
    for paragraph in text.split("\n"):
        lines.extend(textwrap.wrap(paragraph, width=cols) or [""])
    return lines
