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
ASK_AGENT = fixtures.AGENT_ASK
ASK_RUN = fixtures.RUN_ASK

ALERT_PROMPT = (
    "Check AAPL's move since the last close. If it fell more than 5%, explain "
    "what drove it and what changed for the thesis; otherwise reply 'no alert'."
)


def _terminal(name: str, title: str, caption: str,
              commands: List[Any], cols: int = 70) -> Dict[str, Any]:
    return {"name": name, "kind": "terminal", "title": title, "caption": caption,
            "cols": cols, "commands": commands}


def build() -> List[Dict[str, Any]]:
    """Return every scene. `commands` entries are (shown, argv) pairs."""
    return [
        {
            "name": "ask-anything",
            "kind": "chat",
            "title": "claude",
            "caption": "Ask in natural language; the answer is quoted and cited.",
            "cols": 88,
            "hint": 'Try "brief me like this every weekday before the open"',
            "capture": [
                (f'fn2 start "{fixtures.ASK_PROMPT}"',
                 ["start", fixtures.ASK_PROMPT]),
                (f"fn2 result {ASK_AGENT} {ASK_RUN}",
                 ["result", ASK_AGENT, ASK_RUN]),
            ],
            "messages": [
                {"role": "user",
                 "text": "what did NVIDIA say about data-center demand on the "
                         "last earnings call?"},
                {"role": "assistant",
                 "text": "Running that as a one-off FN2 AI agent, then reading "
                         "the result."},
                {"role": "tool", "capture": 0},
                {"role": "tool", "capture": 1},
                {"role": "assistant",
                 "text": "Huang called demand \"parabolic\" and put it down to "
                         "agentic AI; Kress sized AI-infrastructure spend at $3T "
                         "to $4T a year by 2030 and flagged supply chain as the "
                         "constraint. The stock closed 217.55, off 2.9%, with the "
                         "next print on 26 Aug."},
            ],
        },
        {
            "name": "alerts",
            "kind": "chat",
            "title": "claude",
            "caption": "Standing watches, in one sentence.",
            "cols": 88,
            "hint": 'Try "pause that until earnings"',
            "capture": [
                (f'fn2 start "{ALERT_PROMPT}" --when "market close" --email',
                 ["start", ALERT_PROMPT, "--when", "market close", "--email"]),
            ],
            "messages": [
                {"role": "user", "text": "notify me when AAPL drops more than 5% in a day"},
                {"role": "assistant",
                 "text": "I'll put a watch on the close and have it email you."},
                {"role": "tool", "capture": 0},
                {"role": "assistant",
                 "text": "It runs 5 minutes after every close and emails you the "
                         "verdict. Quiet days are a one-line note; the exchange "
                         "calendar is resolved server side, so holidays and "
                         "half-days are skipped."},
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
            "status", "fn2 status",
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
            "Cadences in everyday words, resolved against the exchange calendar.",
            [("fn2 start \"EOD watchlist recap\" --when \"market close\" --email",
              ["start", "EOD watchlist recap", "--when", "market close", "--email"]),
             ("fn2 start \"Macro digest\" --when \"weekdays at 7am\" --tz America/New_York",
              ["start", "Macro digest", "--when", "weekdays at 7am",
               "--tz", "America/New_York"]),
             (f"fn2 schedule {AGENT} \"hourly\"",
              ["schedule", AGENT, "hourly"])],
        ),
        _terminal(
            "account", "fn2 whoami",
            "Plan, quota, device scopes, and the models you can run on.",
            [("fn2 whoami", ["whoami"]),
             ("fn2 models", ["models"])],
        ),
        _terminal(
            "security", "fn2 doctor",
            "A scoped, revocable credential, and a one-command health check.",
            [("fn2 permissions", ["permissions"]),
             ("fn2 doctor", ["doctor"])],
        ),
    ]


def wrap(text: str, cols: int) -> List[str]:
    lines: List[str] = []
    for paragraph in text.split("\n"):
        lines.extend(textwrap.wrap(paragraph, width=cols) or [""])
    return lines
