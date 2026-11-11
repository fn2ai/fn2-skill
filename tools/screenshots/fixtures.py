"""Demo API payloads for the documentation screenshots.

These are real fn2 API response *shapes* with demo identifiers substituted:
every field name, status value, schedule object, and usage envelope matches
what `https://fn2.ai/api/v1/...` actually returns. The screenshots are produced
by running the real CLI against this route table (see `capture.py`), so nothing
in `docs/media/` is a mockup — it is the shipped renderer's own output.

Timestamps are anchored to the most recent US market session at generation
time, so regenerated screenshots never look stale.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict

UTC = dt.timezone.utc

# Stable demo identifiers. Not real account data.
AGENT_SENTIMENT = "ebab1623-5957-4e49-a929-085afee5e496"
AGENT_PREMARKET = "2949113c-71ea-4075-b534-e6464d2ed8f6"
AGENT_EARNINGS = "3a374644-8290-48cb-aa0b-3927288f8d15"
AGENT_MACRO = "e4c4a9e0-8652-4ae2-9f17-a0be2d4a4c26"
AGENT_NVDA = "f2996d1a-03f4-4886-b0f1-5dd2b0ed30fe"

AGENT_ASK = "7b04c9de-1a68-4f21-8e5c-63d9a7f0b214"

RUN_LATEST = "6c1f4b2a-9d33-4e07-8f5b-2a71c0e94d18"
RUN_ASK = "c50a7f36-88d2-4b19-9e74-1d6a3520fbc8"
RUNS_OLDER = [
    "b38e7a05-41c6-4fd9-9a2e-70d5183bc4f7",
    "0f92d6c1-7be4-4a35-b8d0-51c6e2af9330",
    "4ad50e88-2c17-49b6-96f3-c8b0471de2a5",
    "9e6b31f7-58a0-4c92-a4d1-3f7280be5c6b",
]

DEMO_TOKEN = "fn2d_R7xQ2m4vKpN8sT1wYb6ZcE3hJ9uD5aF0gL2nP7q2"
DEMO_ACCOUNT = {"email_masked": "yo•••@example.com", "plan": "pro"}

MODEL = "z-ai/glm-5.2"

ASK_PROMPT = (
    "What did NVIDIA executives say about data-center demand on the most recent "
    "earnings call? Quote them, and note how the stock reacted."
)

# Verbatim from the transcripts the agent cites: NVIDIA Q1 FY2027 call,
# 20 May 2026. Quotes are the executives' own words.
ASK_TEXT = """\
NVIDIA Q1 FY2027 earnings call, 20 May 2026.

Jensen Huang, CEO:
  "This was an extraordinary quarter. Demand has gone parabolic. The
   reason is simple. Agentic AI has arrived."

Colette Kress, CFO:
  "Demand for AI infrastructure continues to expand at an unprecedented
   pace. The build out of AI factories is accelerating."
  "We are continuing to work vigorously on our supply chain ecosystem to
   address the incredible demand we see ahead of us."
  "AI infrastructure spending is on track to reach $3 trillion to
   $4 trillion annually by the end of this decade."

Stock: NVDA closed 217.55, down 2.86% on the day. Next print 26 Aug,
after the close.

Research commentary, not personalized investment advice."""

SENTIMENT_PROMPT = (
    "You are a market sentiment analyst. At the open, assess the market mood and "
    "deliver a concise, actionable briefing: pre-market movers, index check "
    "(SPY/QQQ/IWM), sector leaders and laggards, a macro snapshot from FRED, "
    "overnight headlines, and what prediction markets are pricing. Lead with a "
    "clear Bullish / Bearish / Mixed call; traders need the signal in under "
    "30 seconds."
)

# Trimmed from a real run of the agent above. Kept verbatim in structure and
# tone; the numbers are the ones that run reported.
RESULT_TEXT = """\
SENTIMENT CALL: MIXED. Cautiously bullish tape, elevated underlying risk.

Indices open flat with small caps lagging. Energy leads on geopolitical
risk, tech is bifurcated, and the macro picture flashes a caution flag.

INDEX CHECK (opening prints)
  SPY  772.67  -0.08%     QQQ  722.41  -0.09%     IWM  300.30  -0.42%
  Small caps are the relative laggard, a risk-off tell at the margin.

LEADERS & LAGGARDS
  CVX   188.87  +1.24%   energy bid on Strait of Hormuz headlines
  MSFT  505.69  +1.14%   the lone large-cap tech green
  JPM   357.34  -0.05%   banks flat, consistent with the mixed macro read
  AAPL  306.54  -2.17%   standout decliner, worth a catalyst check

MACRO (FRED)
  Fed funds 3.63%  CPI 3.46% YoY  10Y 4.69%  curve +0.46%  VIX 15.15
  Consumer sentiment 49.5, an extreme low, down 18.5% YoY. Low sentiment
  with record equity prices and a 15 handle on VIX is the divergence
  to watch.

PREDICTION MARKETS
  No Fed cuts in 2026  85.8%   |   one cut  9.5%   |   two or more  3.4%
  Equities sit at highs while markets price essentially zero cuts. If
  next week's CPI confirms that path, earnings carry the tape alone.

Research commentary, not personalized investment advice."""


# ---------------------------------------------------------------------------
# time anchors
# ---------------------------------------------------------------------------
def _iso(moment: dt.datetime) -> str:
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _last_weekday_at(now: dt.datetime, hour: int, minute: int) -> dt.datetime:
    """Most recent weekday occurrence of hour:minute UTC that is in the past."""
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate >= now:
        candidate -= dt.timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= dt.timedelta(days=1)
    return candidate


def _next_weekday_at(now: dt.datetime, hour: int, minute: int) -> dt.datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += dt.timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += dt.timedelta(days=1)
    return candidate


def build(now: dt.datetime) -> Dict[str, Any]:
    """Return the route table the capture harness serves to the CLI."""
    open_utc, close_utc = (13, 30), (20, 5)
    last_open = _last_weekday_at(now, *open_utc)
    last_close = _last_weekday_at(now, *close_utc)
    next_open = _next_weekday_at(now, *open_utc)
    next_close = _next_weekday_at(now, *close_utc)

    sentiment = {
        "id": AGENT_SENTIMENT,
        "name": "Market Open Sentiment",
        "status": "active",
        "recurring": True,
        "run_count": 54,
        "model": MODEL,
        "labels": ["markets", "daily"],
        "prompt": SENTIMENT_PROMPT,
        "created_at": _iso(now - dt.timedelta(days=76)),
        "last_run_at": _iso(last_open + dt.timedelta(seconds=31)),
        "delivery": {"email": True},
        "schedule": {
            "frequency": "market_open",
            "market_event": "open",
            "offset_minutes": -30,
            "timezone": "America/New_York",
            "next_run_at": _iso(next_open),
            "cron": None,
            "run_at": None,
            "ends_at": None,
        },
    }
    premarket = {
        "id": AGENT_PREMARKET,
        "name": "Pre-market watchlist brief",
        "status": "active",
        "recurring": True,
        "run_count": 12,
        "model": MODEL,
        "created_at": _iso(now - dt.timedelta(days=17)),
        "last_run_at": _iso(last_open - dt.timedelta(minutes=30)),
        "schedule": {
            "frequency": "market_open",
            "market_event": "open",
            "offset_minutes": -30,
            "timezone": "America/New_York",
            "next_run_at": _iso(next_open - dt.timedelta(minutes=30)),
        },
    }
    earnings = {
        "id": AGENT_EARNINGS,
        "name": "Earnings reaction recap",
        "status": "active",
        "recurring": True,
        "run_count": 23,
        "model": MODEL,
        "created_at": _iso(now - dt.timedelta(days=41)),
        "last_run_at": _iso(last_close + dt.timedelta(seconds=44)),
        "schedule": {
            "frequency": "market_close",
            "market_event": "close",
            "offset_minutes": 5,
            "timezone": "America/New_York",
            "next_run_at": _iso(next_close),
        },
    }
    macro = {
        "id": AGENT_MACRO,
        "name": "Macro & rates digest",
        "status": "paused",
        "recurring": True,
        "run_count": 8,
        "model": MODEL,
        "created_at": _iso(now - dt.timedelta(days=29)),
        "last_run_at": _iso(now - dt.timedelta(days=6, hours=2)),
        "schedule": {
            "frequency": "custom",
            "cron": "0 7 * * 1-5",
            "timezone": "America/New_York",
            "next_run_at": None,
        },
    }
    nvda = {
        "id": AGENT_NVDA,
        "name": "NVDA 5% move alert",
        "status": "completed",
        "recurring": False,
        "run_count": 1,
        "model": MODEL,
        "created_at": _iso(now - dt.timedelta(days=8)),
        "last_run_at": _iso(last_close),
        "schedule": {"run_at": _iso(last_close), "frequency": None, "cron": None},
    }
    agents = [sentiment, premarket, earnings, macro, nvda]

    def run(run_id: str, started: dt.datetime, seconds: float,
            out_tokens: int) -> Dict[str, Any]:
        return {
            "agent_id": AGENT_SENTIMENT,
            "run_id": run_id,
            "status": "completed",
            "created_at": _iso(started),
            "started_at": _iso(started),
            "completed_at": _iso(started + dt.timedelta(seconds=seconds)),
            "duration_seconds": seconds,
            "model": MODEL,
            "error": None,
            "usage": {
                "input_tokens": 64253,
                "output_tokens": out_tokens,
                "total_tokens": 64253 + out_tokens,
            },
        }

    runs = [run(RUN_LATEST, last_open, 29.8, 4450)]
    for offset, (rid, secs, out) in enumerate(
        zip(RUNS_OLDER, (39.8, 32.7, 34.3, 36.2), (3459, 4149, 3164, 3555)), start=1
    ):
        day = last_open
        for _ in range(offset):
            day -= dt.timedelta(days=1)
            while day.weekday() >= 5:
                day -= dt.timedelta(days=1)
        runs.append(run(rid, day, secs, out))

    latest = dict(runs[0], result={"text": RESULT_TEXT})
    asked = {
        "agent_id": AGENT_ASK,
        "run_id": RUN_ASK,
        "status": "completed",
        "created_at": _iso(now - dt.timedelta(seconds=48)),
        "started_at": _iso(now - dt.timedelta(seconds=48)),
        "completed_at": _iso(now - dt.timedelta(seconds=9)),
        "duration_seconds": 38.6,
        "model": MODEL,
        "error": None,
        "usage": {"input_tokens": 51204, "output_tokens": 902,
                  "total_tokens": 52106},
        "result": {"text": ASK_TEXT},
    }

    created = {
        "id": AGENT_PREMARKET,
        "name": "Pre-market watchlist brief",
        "status": "active",
        "recurring": True,
        "run_count": 0,
        "schedule": premarket["schedule"],
    }

    usage = {
        "plan": "pro",
        "tokens": {
            "used": 4988400,
            "limit": 37000000,
            "remaining": 32011600,
            "unlimited": False,
            "resets_at": _iso(now + dt.timedelta(days=15)),
        },
        "device": {
            "label": "Claude Code on macOS",
            "scopes": ["agents", "models", "research"],
            "expires_at": _iso(now + dt.timedelta(days=90)),
        },
    }

    models = [
        {"model_id": "z-ai/glm-5.2", "display_name": "GLM 5.2",
         "model_class": "frontier", "required_plan": None, "is_default": True},
        {"model_id": "anthropic/claude-sonnet-5", "display_name": "Claude Sonnet 5",
         "model_class": "frontier", "required_plan": None, "is_default": False},
        {"model_id": "openai/gpt-5", "display_name": "GPT-5",
         "model_class": "frontier", "required_plan": None, "is_default": False},
        {"model_id": "deepseek/deepseek-v4-flash", "display_name": "Balanced",
         "model_class": "good", "required_plan": None, "is_default": False},
    ]

    device_start = {
        "device_code": "fn2dc_8pQ4wZ1nR6tL0vX3",
        "user_code": "KRQD-7T2M",
        "verification_uri": "https://fn2.ai/start",
        "interval": 5,
        "expires_in": 900,
    }
    device_approved = {
        "status": "approved",
        "access_token": DEMO_TOKEN,
        "device_id": "dev_2n8QpL",
        "scopes": ["agents", "models", "research"],
        "expires_at": _iso(now + dt.timedelta(days=90)),
        "account": DEMO_ACCOUNT,
    }

    return {
        "agents": agents,
        "agent_by_id": {a["id"]: a for a in agents},
        "runs": runs,
        "run_detail": {RUN_LATEST: latest, RUN_ASK: asked},
        "created_agent": created,
        "created_ids": [AGENT_PREMARKET, AGENT_EARNINGS, AGENT_NVDA],
        "ask_agent_id": AGENT_ASK,
        "ask_run_id": RUN_ASK,
        "usage": usage,
        "models": models,
        "device_start": device_start,
        "device_poll": [{"status": "authorization_pending"}, device_approved],
        "queued_run": {"run_id": RUN_LATEST, "status": "queued"},
        "token": DEMO_TOKEN,
    }
