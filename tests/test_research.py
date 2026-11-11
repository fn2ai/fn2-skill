"""Offline tests for the direct research commands.

Every response is a fixture shaped like the public API's; nothing here opens a
socket. The HTTP seam (``Client._urlopen``) is swapped for a transport that
routes by path and records each request, so the tests assert on the request
that would have been sent as well as on what the reader is shown.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import shlex
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock
from urllib.parse import parse_qsl, urlsplit

_SCRIPTS = (pathlib.Path(__file__).resolve().parent.parent /
            "skills" / "fn2" / "scripts")
sys.path.insert(0, str(_SCRIPTS))

from fn2cli import api, cli, deviceauth, render, storage  # noqa: E402
from fn2cli.client import Client  # noqa: E402

TOKEN = "fn2d_" + "A" * 36 + "wxyz"
APIKEY = "fn2_" + "C" * 36 + "wxyz"
AGENT = "ebab1623-5957-4e49-a929-085afee5e496"
TID = "0f8b2c1e-5d4a-4b7c-9e21-3a6f8d1c2b40"
TID_PRIOR = "7a1d9e02-3c4b-4f5a-8b6c-1d2e3f4a5b6c"

V1 = "/api/v1"

QUOTA_SENTENCE = (
    "The Free plan includes 25 FN2 research requests per week, and you've "
    "used all 25. Your quota resets on Monday, 16 November (UTC). Upgrade at "
    "https://fn2.ai/preferences#billing for a higher weekly limit.")

STALE_NOTE = (
    "The newest result FN2 holds for BRK.B was reported on 2024-08-03, 831 "
    "days before 2026-11-11, and no upcoming report is scheduled. The company "
    "has very likely reported since; do not present this as its latest "
    "quarter without saying so.")

NOTES = [
    "Estimates are sell-side analyst consensus from a market-data vendor. "
    "They are not company guidance.",
    "The next report date is a scheduled estimate, not a company confirmation.",
]

EARNINGS = {
    "symbol": "NFLX",
    "as_of": "2026-11-11",
    "count": 2,
    "possibly_stale": False,
    "reported": [
        {
            "fiscal_period": "Q3 '26", "fiscal_year": 2026, "fiscal_quarter": 3,
            "fiscal_date_ending": "2026-09-30", "report_date": "2026-10-20",
            "session": "amc",
            "eps": {"actual": 0.87, "estimate": 0.82, "surprise": 0.05,
                    "surprise_pct": 6.1, "outcome": "beat"},
            "revenue": {"actual": 12874180000, "estimate": 12869330000,
                        "surprise": 4850000, "surprise_pct": 0.04,
                        "outcome": "beat"},
            "call": {"transcript_id": TID, "call_date": "2026-10-20"},
        },
        {
            "fiscal_period": "Q2 '26", "fiscal_year": 2026, "fiscal_quarter": 2,
            "fiscal_date_ending": "2026-06-30", "report_date": "2026-07-16",
            "session": "bmo",
            "eps": {"actual": 0.70, "estimate": 0.71, "surprise": -0.01,
                    "surprise_pct": -1.41, "outcome": "miss"},
            "revenue": {"actual": 11079166000, "estimate": 11079166000,
                        "surprise": 0, "surprise_pct": 0.0, "outcome": "match"},
            "call": {"transcript_id": TID_PRIOR, "call_date": "2026-07-16"},
        },
    ],
    "next": {
        "report_date": "2027-01-19", "session": "unknown",
        "fiscal_date_ending": "2026-12-31", "fiscal_period": "Q4 '26",
        "fiscal_year": 2026, "fiscal_quarter": 4, "eps_estimate": 0.95,
        "revenue_estimate": 13100000000, "date_status": "estimated",
    },
    "notes": list(NOTES),
}

# What production really returns for a thinly covered symbol: EPS without
# revenue, no fiscal label, no matched call, no scheduled report.
EARNINGS_SPARSE = {
    "symbol": "BRK.B",
    "as_of": "2026-11-11",
    "count": 1,
    "possibly_stale": True,
    "reported": [{
        "fiscal_period": None, "fiscal_year": None, "fiscal_quarter": None,
        "fiscal_date_ending": "2024-06-30", "report_date": "2024-08-03",
        "session": "unknown",
        "eps": {"actual": 21122.0, "estimate": None, "surprise": None,
                "surprise_pct": None, "outcome": None},
        "revenue": {"actual": None, "estimate": None, "surprise": None,
                    "surprise_pct": None, "outcome": None},
        "call": None,
    }],
    "next": None,
    "notes": [STALE_NOTE] + NOTES,
}

CALLS = {
    "symbol": "NFLX",
    "count": 2,
    "calls": [
        {"transcript_id": TID, "call_date": "2026-10-20", "fiscal_year": 2026,
         "fiscal_quarter": 3, "characters": 36427},
        {"transcript_id": TID_PRIOR, "call_date": "2026-07-16",
         "fiscal_year": None, "fiscal_quarter": None, "characters": 41210},
    ],
    "coverage_note": "Newest first. These are the calls FN2 holds text for, "
                     "which may not be every call the company held.",
}

PAGE_ONE = ("Operator: Good afternoon and welcome.\n\n"
            "Spence Neumann: Operating margin was 28.2% in the quarter.\n")
PAGE_TWO = "Greg Peters: Our ads business is on track to double this year.\n"


def _transcript_page(params):
    offset = int(params.get("offset", 0))
    first = offset == 0
    text = PAGE_ONE if first else PAGE_TWO
    return {
        "transcript_id": TID, "symbol": "NFLX", "call_date": "2026-10-20",
        "fiscal_year": 2026, "fiscal_quarter": 3, "characters": 36427,
        "offset": offset, "returned": len(text),
        "next_offset": 23950 if first else None, "text": text,
    }


SEARCH = {
    "query": "ad tier", "symbol": "NFLX", "after": "2026-01-01",
    "transcript_id": TID, "count": 1,
    "results": [{
        "symbol": "NFLX", "company_name": "Netflix, Inc.",
        "fiscal_quarter": 3, "fiscal_year": 2026, "call_date": "2026-10-20",
        "speaker": "Greg Peters",
        "text": "Our ads business is on track to double this year.\n"
                "We now have 94 million monthly active users on the ad tier.",
        "highlights": ["on the <em>ad</em> <em>tier</em>"],
        "transcript_id": TID, "block_id": 41, "score": 12.3,
    }],
    "coverage_note": "Transcript coverage varies by company and period. An "
                     "empty result means FN2 has no matching call text, not "
                     "that the company said nothing.",
}

# The API returns periods oldest first; the view must not depend on that.
FINANCIALS = {
    "ticker": "NFLX", "variant": "quarterly",
    "periods": [
        {"period_end": "2026-06-30", "fiscal_year": 2026, "fiscal_period": "Q2",
         "form_type": "10-Q", "filing_date": "2026-07-17",
         "values": {"market_cap": None, "revenue": 11079166000,
                    "operating_income": 3774000000, "operating_margin": 34.0641,
                    "net_income": 3125000000, "diluted_eps": 7.19,
                    "revenue_growth": None, "operating_cash_flow": None,
                    "enterprise_value": None},
         "quality": {"cross_check_disagreements": []}},
        {"period_end": "2026-09-30", "fiscal_year": 2026, "fiscal_period": "Q3",
         "form_type": "10-Q", "filing_date": "2026-10-17",
         "values": {"market_cap": None, "revenue": 11510307000,
                    "operating_income": 3248000000, "operating_margin": 28.2182,
                    "net_income": 2547000000, "diluted_eps": 5.87,
                    "revenue_growth": 17.1626,
                    "operating_cash_flow": 2827000000,
                    "enterprise_value": None},
         "quality": {"cross_check_disagreements": ["free_cash_flow"]}},
    ],
    "coverage": {"periods_returned": 2},
    "unavailable": {"market_cap": "historical source unavailable",
                    "enterprise_value": "historical market cap unavailable",
                    "forward_estimates": "trustworthy source unavailable"},
}

QUOTE = {
    "symbol": "NFLX", "session": "closed", "source": "fmp",
    "regular": {"price": 1112.17, "change": -8.9, "change_pct": -0.7939,
                "previous_close": 1121.07,
                "as_of": "2026-11-10T16:00:00-05:00"},
    "extended": {"price": 1113.5, "as_of": "2026-11-10T19:58:00-05:00",
                 "change_vs_close_pct": 0.1196},
}

# 2026-11-09 and 2026-11-10 at 00:00 US Eastern (05:00 UTC): daily bars. Both
# share one time of day and the calendar date is the same in ET and in UTC, so
# they print as bare dates even on a platform without zone data.
HISTORY = {
    "range": "6M", "truncated": True,
    "point_format": ["timestamp_ms", "close", "volume", "open", "high", "low"],
    "points": [[1794200400000, 1121.07, 2345678.0, 1118.0, 1125.5, 1110.25],
               [1794286800000, 1112.17, 1987654, 1120.0, 1122.0, 1108.9]],
}

FRED_SERIES = {
    "series_id": "DGS10",
    # Flask serialises DATE columns as HTTP dates and NUMERIC as strings.
    "metadata": {"series_id": "DGS10",
                 "title": "Market Yield on U.S. Treasury Securities at "
                          "10-Year Constant Maturity",
                 "category": "rates", "frequency": "Daily",
                 "frequency_short": "D", "units": "Percent", "units_short": "%",
                 "seasonal_adjustment_short": "NSA",
                 "observation_start": "Tue, 02 Jan 1962 00:00:00 GMT",
                 "observation_end": "Tue, 10 Nov 2026 00:00:00 GMT",
                 "last_updated_fred": "Tue, 10 Nov 2026 21:16:00 GMT"},
    "count": 2,
    "observations": [
        {"date": "2026-11-09", "value": "4.11", "yoy_pct": "-3.52",
         "mom_pct": None, "qoq_pct": None},
        {"date": "2026-11-10", "value": 4.13, "yoy_pct": 1.2,
         "mom_pct": None, "qoq_pct": None},
    ],
}

FRED_CATALOG = {
    "count": 2,
    "series": [
        {"series_id": "UNRATE", "title": "Unemployment Rate",
         "category": "labor", "frequency_short": "M", "units_short": "%",
         "observation_start": "Thu, 01 Jan 1948 00:00:00 GMT",
         "observation_end": "Thu, 01 Oct 2026 00:00:00 GMT"},
        {"series_id": "DGS10", "title": "10-Year Treasury Yield",
         "category": "rates", "frequency_short": "D", "units_short": "%",
         "observation_start": "1962-01-02", "observation_end": "2026-11-10"},
    ],
    "note": "Pass series_id to fetch observations for one series.",
}

RECALL = {
    "query": "holdings", "agent_id": AGENT, "count": 1,
    "memories": [{
        "id": "m1", "item_key": "portfolio/nvda", "tag": "holdings",
        "content": "User holds 120 NVDA at an average cost of 98.40.",
        "updated_at": "2026-11-01T14:02:00Z", "agent_id": AGENT,
        "agent_name": "Watchlist brief",
    }],
}

USAGE = {
    "plan": "free",
    "tokens": {"used": 1200, "limit": 100000, "remaining": 98800,
               "unlimited": False, "resets_at": "2026-12-01T00:00:00Z"},
    "research_requests": {"used": 3, "limit": 25, "remaining": 22,
                          "unlimited": False, "period": "week",
                          "resets_at": "2026-11-16T00:00:00Z"},
}

ROUTES = {
    V1 + "/research/earnings": EARNINGS,
    V1 + "/research/transcripts": CALLS,
    V1 + "/research/transcripts/read": _transcript_page,
    V1 + "/research/transcripts/search": SEARCH,
    V1 + "/research/financials": FINANCIALS,
    V1 + "/research/prices": lambda p: (
        {"symbol": "NFLX", "quote": QUOTE, "history": HISTORY}
        if p.get("range") else {"symbol": "NFLX", "quote": QUOTE}),
    V1 + "/research/fred": lambda p: (
        FRED_SERIES if p.get("series_id") else FRED_CATALOG),
    V1 + "/research/recall": RECALL,
    V1 + "/usage": USAGE,
    V1 + "/agents": {"agents": [{"id": AGENT, "name": "Watchlist brief"}],
                     "total": 1},
}


class _Response(io.BytesIO):
    def getcode(self):
        return 200


def _problem(status, message, code, **extra):
    """An API error in the problem-details envelope the research routes use."""
    body = {"error": message, "code": code, "request_id": "req_test",
            "retryable": False, "retry_after": None, "field_errors": None,
            "type": f"https://fn2.ai/errors/{code}"}
    body.update(extra)
    return status, body


class _Sandbox(unittest.TestCase):
    """Isolated FN2_* environment, a temp config home, and the offline API."""

    _ENV_KEYS = ("FN2_API_TOKEN", "FN2_API_KEY", "FN2_BASE_URL",
                 "FN2_CONFIG_HOME", "FN2_ALLOW_DEV_BASE", "FN2_ONBOARD_URL")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        saved = {k: os.environ.get(k) for k in self._ENV_KEYS}
        self.addCleanup(self._restore_env, saved)
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["FN2_CONFIG_HOME"] = self._tmp.name
        keychain = mock.patch.object(storage, "keychain_available",
                                     return_value=False)
        keychain.start()
        self.addCleanup(keychain.stop)
        self.requests = []
        self.routes = dict(ROUTES)
        transport = mock.patch.object(Client, "_urlopen", new=self._transport())
        transport.start()
        self.addCleanup(transport.stop)

    @staticmethod
    def _restore_env(saved):
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _transport(self):
        test = self

        def transport(client, request):
            split = urlsplit(request.full_url)
            params = dict(parse_qsl(split.query))
            test.requests.append((request.method, split.path, params,
                                  request.get_header("Authorization")))
            if split.path not in test.routes:
                test.fail(f"unexpected HTTP request: {request.method} {split.path}")
            result = test.routes[split.path]
            if callable(result):
                result = result(params)
            if isinstance(result, tuple):
                status, body = result
                raise urllib.error.HTTPError(
                    request.full_url, status, "error", {},
                    io.BytesIO(json.dumps(body).encode()))
            return _Response(json.dumps(result).encode())

        return transport

    def sign_in(self, scopes=("agents", "models", "research"), token=TOKEN,
                kind="device"):
        extra = {"scopes": list(scopes)} if scopes is not None else {}
        storage.store_credential(token, base_url="https://fn2.ai", kind=kind,
                                 extra=extra)

    def run_cli(self, *argv):
        """-> (exit code, stdout, stderr). Argument errors exit like a shell."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as exit_:
                code = exit_.code
                if isinstance(code, str):
                    print(code, file=sys.stderr)
                    code = 1
        self.assertNotIn(TOKEN, out.getvalue() + err.getvalue())
        self.assertNotIn(APIKEY, out.getvalue() + err.getvalue())
        return code, out.getvalue(), err.getvalue()

    def ok(self, *argv):
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 0, err)
        return out

    def last(self):
        return self.requests[-1]


# ---------------------------------------------------------------------------
# api layer: one function per endpoint
# ---------------------------------------------------------------------------
class _Recorder:
    def __init__(self):
        self.calls = []

    def get(self, path, **kw):
        self.calls.append((path, kw.get("params")))
        return {}


class ResearchApiTests(unittest.TestCase):
    def test_each_function_maps_to_its_endpoint_and_parameters(self):
        stub = _Recorder()
        api.earnings(stub, "NFLX", limit=4)
        api.list_transcripts(stub, "NFLX", limit=8)
        api.read_transcript(stub, symbol="NFLX", fiscal_year=2026,
                            fiscal_quarter=3, offset=100, max_chars=5000)
        api.read_transcript(stub, transcript_id=TID)
        api.search_transcripts(stub, "ad tier", symbol="NFLX",
                               after="2026-01-01", transcript_id=TID, limit=3)
        api.financials(stub, "NFLX", variant="quarterly", limit=6)
        api.prices(stub, "NFLX", history_range="1M")
        api.fred(stub, "DGS10", limit=30)
        api.fred(stub)
        api.recall(stub, query="holdings", agent_id=AGENT, tag="t", limit=5)
        self.assertEqual(stub.calls, [
            (V1 + "/research/earnings", {"symbol": "NFLX", "limit": 4}),
            (V1 + "/research/transcripts", {"symbol": "NFLX", "limit": 8}),
            (V1 + "/research/transcripts/read",
             {"symbol": "NFLX", "fiscal_year": 2026, "fiscal_quarter": 3,
              "transcript_id": None, "offset": 100, "max_chars": 5000}),
            (V1 + "/research/transcripts/read",
             {"symbol": None, "fiscal_year": None, "fiscal_quarter": None,
              "transcript_id": TID, "offset": None, "max_chars": None}),
            (V1 + "/research/transcripts/search",
             {"query": "ad tier", "symbol": "NFLX", "after": "2026-01-01",
              "transcript_id": TID, "limit": 3}),
            (V1 + "/research/financials",
             {"symbol": "NFLX", "variant": "quarterly", "limit": 6}),
            (V1 + "/research/prices", {"symbol": "NFLX", "range": "1M"}),
            (V1 + "/research/fred", {"series_id": "DGS10", "limit": 30}),
            (V1 + "/research/fred", {"series_id": None, "limit": None}),
            (V1 + "/research/recall",
             {"query": "holdings", "agent_id": AGENT, "tag": "t", "limit": 5}),
        ])


# ---------------------------------------------------------------------------
# earnings
# ---------------------------------------------------------------------------
class EarningsTests(_Sandbox):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_request_and_complete_human_view(self):
        out = self.ok("earnings", "nflx")
        method, path, params, auth = self.last()
        self.assertEqual((method, path), ("GET", V1 + "/research/earnings"))
        self.assertEqual(params, {"symbol": "NFLX", "limit": "4"})
        self.assertEqual(auth, "Bearer " + TOKEN)
        self.assertEqual(len(self.requests), 1)

        # The quarter and the report date, stated from the data.
        self.assertIn("[1] Q3 '26 = fiscal 2026 Q3, quarter ended 2026-09-30 | "
                      "reported 2026-10-20, after market close", out)
        self.assertIn("reported 2026-07-16, before market open", out)
        # Exact figures: never abbreviated to 12.87B, never rounded.
        self.assertIn("EPS      actual 0.87 | consensus 0.82 | "
                      "surprise +0.05 (+6.1%) | beat consensus", out)
        self.assertIn("revenue  actual 12,874,180,000 | consensus "
                      "12,869,330,000 | surprise +4,850,000 (+0.04%) | "
                      "beat consensus", out)
        self.assertIn("surprise -0.01 (-1.41%) | missed consensus", out)
        self.assertIn("surprise 0 (0%) | matched consensus", out)
        # Full transcript ids: they are the argument to the next command.
        self.assertIn(f"call     held 2026-10-20 | transcript id {TID}", out)
        self.assertIn(f"transcript id {TID_PRIOR}", out)
        self.assertIn("fn2 transcript NFLX --id", out)
        # Consensus is labelled for what it is, and the server's notes relayed.
        self.assertIn("NOT company guidance", out)
        for note in NOTES:
            self.assertIn(note, out)
        self.assertNotIn("POSSIBLY STALE", out)

    def test_next_report_is_an_estimate_and_unknown_session_is_not_guessed(self):
        out = self.ok("earnings", "NFLX")
        line = next(l for l in out.splitlines() if l.startswith("next report:"))
        self.assertIn("2027-01-19", line)
        self.assertIn("unknown", line)
        self.assertIn("scheduled estimate, not company-confirmed", line)
        self.assertIn("Q4 '26 = fiscal 2026 Q4, quarter ending 2026-12-31", line)
        self.assertNotIn("after market close", line)
        self.assertNotIn("before market open", line)
        self.assertIn("consensus EPS 0.95 | consensus revenue 13,100,000,000",
                      out)

    def test_possibly_stale_is_the_first_line_and_missing_data_is_said(self):
        self.routes[V1 + "/research/earnings"] = EARNINGS_SPARSE
        out = self.ok("earnings", "BRK.B")
        lines = out.splitlines()
        self.assertEqual(lines[0], "POSSIBLY STALE: " + STALE_NOTE)
        self.assertEqual(out.count(STALE_NOTE), 1)  # promoted, not repeated
        # Every absent field is an explicit statement, never an omitted row.
        self.assertIn("fiscal quarter label not available, quarter ended "
                      "2024-06-30", out)
        self.assertIn("reported 2024-08-03, before or after market: unknown",
                      out)
        self.assertIn("EPS      actual 21,122 | consensus not available | "
                      "surprise not available | beat/miss not available", out)
        self.assertIn("revenue  not available", out)
        self.assertIn("call     not available", out)
        self.assertIn("next report: not available", out)
        for note in NOTES:
            self.assertIn(note, out)

    def test_stale_flag_without_a_note_still_warns_first(self):
        self.routes[V1 + "/research/earnings"] = dict(EARNINGS_SPARSE, notes=[])
        out = self.ok("earnings", "BRK.B")
        self.assertTrue(out.startswith("POSSIBLY STALE: "), out[:80])

    def test_limit_is_sent_and_bounded_before_any_request(self):
        self.ok("earnings", "NFLX", "--limit", "12")
        self.assertEqual(self.last()[2]["limit"], "12")
        before = len(self.requests)
        for bad in ("0", "13", "many"):
            code, _, err = self.run_cli("earnings", "NFLX", "--limit", bad)
            self.assertEqual(code, 2)
            self.assertIn("1 to 12", err)
        self.assertEqual(len(self.requests), before)

    def test_json_is_the_api_payload_untouched(self):
        for argv in (("earnings", "NFLX", "--json"), ("--json", "earnings", "NFLX")):
            self.assertEqual(json.loads(self.ok(*argv)), EARNINGS)

    def test_unknown_symbol_relays_the_api_sentence(self):
        self.routes[V1 + "/research/earnings"] = _problem(
            404, "FN2 has no earnings results or scheduled report for ZZZZ. "
                 "Coverage is US-listed companies.", "not_found")
        code, out, err = self.run_cli("earnings", "ZZZZ")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("HTTP 404: FN2 has no earnings results or scheduled "
                      "report for ZZZZ.", err)
        self.assertEqual(len(self.requests), 1)


# ---------------------------------------------------------------------------
# calls + transcript
# ---------------------------------------------------------------------------
class CallTests(_Sandbox):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_calls_lists_full_ids_and_says_when_the_limit_was_hit(self):
        out = self.ok("calls", "NFLX", "--limit", "2")
        self.assertEqual(self.last()[1:3], (V1 + "/research/transcripts",
                                            {"symbol": "NFLX", "limit": "2"}))
        self.assertIn("2 shown, newest first (limit 2 reached", out)
        self.assertIn(TID, out)
        self.assertIn(TID_PRIOR, out)
        self.assertIn("36,427", out)
        row = next(l for l in out.splitlines() if TID_PRIOR in l)
        self.assertIn("not available", row)  # no fiscal label on that call
        self.assertIn(CALLS["coverage_note"], out)
        self.assertIn("fn2 transcript NFLX --id", out)

        out = self.ok("transcripts", "NFLX")  # alias, default limit
        self.assertEqual(self.last()[2], {"symbol": "NFLX", "limit": "8"})
        self.assertNotIn("limit 8 reached", out)

    def test_transcript_by_symbol_reads_the_latest_call_verbatim(self):
        out = self.ok("transcript", "NFLX")
        self.assertEqual(self.last()[1:3], (
            V1 + "/research/transcripts/read",
            {"symbol": "NFLX", "offset": "0", "max_chars": "24000"}))
        self.assertIn(f"NFLX earnings call | held 2026-10-20 | fiscal 2026 Q3 "
                      f"(the transcript's own label) | transcript id {TID}", out)
        self.assertIn(f"characters 0 to {len(PAGE_ONE)} of 36,427", out)
        self.assertIn(PAGE_ONE.strip("\n"), out)

    def test_next_page_line_is_printed_twice_and_runs_as_written(self):
        out = self.ok("transcript", "NFLX")
        hint = f"next page: fn2 transcript NFLX --id {TID} --offset 23950"
        lines = out.splitlines()
        self.assertEqual(lines.count(hint), 2)
        # Above the text (survives a cut-off) and as the last line.
        self.assertLess(lines.index(hint), lines.index(
            "----- call text begins (verbatim) -----"))
        self.assertEqual(lines[-1], hint)

        # Running the printed command fetches the continuation of the SAME call.
        out = self.ok(*shlex.split(hint.split("fn2 ", 1)[1]))
        self.assertEqual(self.last()[2], {
            "symbol": "NFLX", "transcript_id": TID, "offset": "23950",
            "max_chars": "24000"})
        self.assertIn(PAGE_TWO.strip(), out)
        self.assertIn(f"characters 23,950 to {23950 + len(PAGE_TWO):,} of "
                      "36,427", out)
        self.assertNotIn("next page:", out)
        self.assertEqual(out.count("end of call: this page reaches the end of "
                                   "the transcript; there is no next page."), 2)

    def test_a_chosen_page_size_is_carried_into_the_next_page_line(self):
        out = self.ok("transcript", "NFLX", "--max-chars", "5000")
        self.assertEqual(self.last()[2]["max_chars"], "5000")
        self.assertIn(f"--id {TID} --offset 23950 --max-chars 5000", out)

    def test_transcript_by_id_or_by_fiscal_period(self):
        self.ok("transcript", "--id", TID.upper())
        self.assertEqual(self.last()[2], {
            "transcript_id": TID, "offset": "0", "max_chars": "24000"})
        self.ok("transcript", "NFLX", "--year", "2026", "--quarter", "3")
        self.assertEqual(self.last()[2], {
            "symbol": "NFLX", "fiscal_year": "2026", "fiscal_quarter": "3",
            "offset": "0", "max_chars": "24000"})

    def test_a_transcript_for_another_company_is_called_out(self):
        out = self.ok("transcript", "AAPL", "--id", TID)
        self.assertIn("this transcript belongs to NFLX, not the AAPL you "
                      "named", out)

    def test_an_offset_past_the_end_says_so(self):
        self.routes[V1 + "/research/transcripts/read"] = {
            "transcript_id": TID, "symbol": "NFLX", "call_date": "2026-10-20",
            "fiscal_year": 2026, "fiscal_quarter": 3, "characters": 36427,
            "offset": 36427, "returned": 0, "next_offset": None, "text": ""}
        out = self.ok("transcript", "NFLX", "--offset", "99999")
        self.assertIn("no text at offset 36,427: the call has 36,427 "
                      "characters", out)

    def test_bad_arguments_fail_before_any_request(self):
        cases = [
            (("transcript",), "name a ticker"),
            (("transcript", "NFLX", "--year", "2026"), "go together"),
            (("transcript", "NFLX", "--quarter", "3"), "go together"),
            (("transcript", "--id", TID, "--year", "2026", "--quarter", "3"),
             "already names one call"),
            (("transcript", "--year", "2026", "--quarter", "3"), "name a ticker"),
            (("transcript", "NFLX", "--id", "latest"), "transcript id"),
            (("transcript", "NFLX", "--quarter", "5", "--year", "2026"),
             "1 to 4"),
            (("transcript", "NFLX", "--quarter", "3", "--year", "26"),
             "1900 to 2200"),
            (("transcript", "NFLX", "--max-chars", "999"), "1,000 to 60,000"),
            (("transcript", "NFLX", "--offset", "-1"), "0 to"),
            (("calls", "NFLX", "--limit", "41"), "1 to 40"),
            (("calls", "N F L X"), "ticker"),
        ]
        for argv, expected in cases:
            with self.subTest(argv=argv):
                code, out, err = self.run_cli(*argv)
                self.assertNotEqual(code, 0)
                self.assertIn(expected, err)
        self.assertEqual(self.requests, [])

    def test_missing_call_relays_the_api_sentence(self):
        self.routes[V1 + "/research/transcripts/read"] = _problem(
            404, "FN2 holds no earnings-call text for NFLX fiscal 2019 Q1. "
                 "List the calls held for a ticker to see which periods are "
                 "available.", "not_found")
        code, _, err = self.run_cli("transcript", "NFLX", "--year", "2019",
                                    "--quarter", "1")
        self.assertEqual(code, 1)
        self.assertIn("FN2 holds no earnings-call text for NFLX fiscal 2019 Q1",
                      err)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
class SearchTests(_Sandbox):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_filters_are_sent_and_hits_are_attributable_and_verbatim(self):
        out = self.ok("search", "ad tier", "--symbol", "nflx", "--after",
                      "2026-01-01", "--call", TID, "--limit", "3")
        self.assertEqual(self.last()[1:3], (
            V1 + "/research/transcripts/search",
            {"query": "ad tier", "symbol": "NFLX", "after": "2026-01-01",
             "transcript_id": TID, "limit": "3"}))
        self.assertIn('transcript search "ad tier": 1 hit, ranked by '
                      "relevance, NOT by date", out)
        self.assertIn(f"filters: symbol NFLX | calls on or after 2026-01-01 | "
                      f"inside transcript {TID}", out)
        self.assertIn(f"[1] NFLX (Netflix, Inc.) | call 2026-10-20, fiscal "
                      f"2026 Q3 (transcript label) | Greg Peters | transcript "
                      f"{TID} block 41 | matched your words: ad, tier", out)
        self.assertNotIn("CAUTION", out)
        # The whole speaker turn, not a fragment and not the <em> highlight.
        self.assertIn("    Our ads business is on track to double this year.\n"
                      "    We now have 94 million monthly active users on the "
                      "ad tier.", out)
        self.assertNotIn("<em>", out)
        self.assertIn(SEARCH["coverage_note"], out)

    def test_hits_that_matched_by_meaning_only_are_marked_and_cautioned(self):
        """A null `highlights` means no query word is in the passage: it is the
        nearest neighbour, returned even when the call never raised the topic
        (searching a call for "buyback" that it never mentions)."""
        keyword = SEARCH["results"][0]
        semantic = dict(keyword, highlights=None, speaker="Spence Neumann",
                        block_id=57, text="We remain focused on healthy "
                                          "revenue growth and expanding margins.")
        self.routes[V1 + "/research/transcripts/search"] = dict(
            SEARCH, count=2, results=[semantic, dict(semantic, block_id=58)])
        out = self.ok("search", "buyback", "--call", TID)
        self.assertIn("CAUTION: none of these 2 hits contains your query "
                      "words; all matched by meaning only.", out)
        self.assertIn("read each one before citing it", out)
        self.assertIn('"Not discussed" can be the right answer', out)
        self.assertEqual(out.count("| matched by meaning only"), 2)
        self.assertNotIn("matched your words", out)
        # Warned about, but still shown in full: the reader decides.
        self.assertIn("    We remain focused on healthy revenue growth", out)

        self.routes[V1 + "/research/transcripts/search"] = dict(
            SEARCH, count=2, results=[keyword, semantic])
        out = self.ok("search", "ad tier", "--call", TID)
        self.assertIn("CAUTION: 1 of 2 hits matched by meaning only (marked "
                      "below)", out)
        first, second = [l for l in out.splitlines() if l.startswith("[")]
        self.assertTrue(first.endswith("| matched your words: ad, tier"), first)
        self.assertTrue(second.endswith("| matched by meaning only"), second)

    def test_an_unquoted_query_is_joined_and_defaults_apply(self):
        self.ok("search", "content", "spend", "outlook")
        self.assertEqual(self.last()[2], {"query": "content spend outlook",
                                          "limit": "5"})

    def test_no_hits_is_an_explicit_statement_with_the_coverage_caveat(self):
        self.routes[V1 + "/research/transcripts/search"] = dict(
            SEARCH, count=0, results=[], transcript_id=None, after=None)
        out = self.ok("search", "quantum toaster", "--symbol", "NFLX")
        self.assertIn('transcript search "ad tier": no matching call text in '
                      "FN2", out)
        self.assertIn("not that the company said nothing", out)

    def test_an_unrecognised_symbol_that_widened_the_search_is_flagged(self):
        # The API drops a symbol it cannot parse and searches every company.
        self.routes[V1 + "/research/transcripts/search"] = dict(
            SEARCH, symbol=None, transcript_id=None, after=None)
        out = self.ok("search", "ad tier", "--symbol", "NETFLIXINC")
        self.assertIn("WARNING: FN2 did not recognise 'NETFLIXINC' as a "
                      "ticker, so this search was NOT limited to one company.",
                      out)
        self.assertIn("filters: none (all companies, all dates)", out)

    def test_limit_reached_is_stated(self):
        out = self.ok("search", "ad tier", "--limit", "1")
        self.assertIn("1 hit (limit 1 reached; raise --limit for more)", out)

    def test_bad_arguments_fail_before_any_request(self):
        for argv, expected in (
                (("search", "x"), "at least 2 characters"),
                (("search", "ads", "--after", "last year"), "YYYY-MM-DD"),
                (("search", "ads", "--after", "2026-1-5"), "YYYY-MM-DD"),
                (("search", "ads", "--call", "the-latest"), "transcript id"),
                (("search", "ads", "--limit", "21"), "1 to 20")):
            with self.subTest(argv=argv):
                code, _, err = self.run_cli(*argv)
                self.assertNotEqual(code, 0)
                self.assertIn(expected, err)
        self.assertEqual(self.requests, [])


# ---------------------------------------------------------------------------
# financials / price / fred / recall
# ---------------------------------------------------------------------------
class DataTests(_Sandbox):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_financials_variants_map_to_the_api(self):
        for flags, variant in (((), "annual"), (("--annual",), "annual"),
                               (("--quarterly",), "quarterly"),
                               (("--ttm",), "ttm")):
            self.ok("financials", "NFLX", *flags)
            self.assertEqual(self.last()[1:3], (
                V1 + "/research/financials",
                {"symbol": "NFLX", "variant": variant, "limit": "5"}))
        code, _, err = self.run_cli("financials", "NFLX", "--quarterly", "--ttm")
        self.assertEqual(code, 2)
        self.assertIn("not allowed with", err)

    def test_financials_view_is_newest_first_exact_and_explicit(self):
        out = self.ok("financials", "NFLX", "--quarterly", "--limit", "2")
        lines = out.splitlines()

        def row(label):
            return next(l for l in lines if l.startswith(label)).split()

        # Newest period is the first column whatever order the API used.
        self.assertEqual(row("period end")[-2:], ["2026-09-30", "2026-06-30"])
        self.assertEqual(row("filed")[-2:], ["2026-10-17", "2026-07-17"])
        self.assertEqual(row("revenue ")[-2:],
                         ["11,510,307,000", "11,079,166,000"])
        self.assertEqual(row("operating income")[-2:],
                         ["3,248,000,000", "3,774,000,000"])
        self.assertEqual(row("operating margin %")[-2:], ["28.2182", "34.0641"])
        self.assertEqual(row("diluted EPS")[-2:], ["5.87", "7.19"])
        # A missing value is a dash with a legend, never a zero.
        self.assertEqual(row("revenue growth YoY %")[-2:], ["17.1626", "-"])
        self.assertEqual(row("operating cash flow")[-2:], ["2,827,000,000", "-"])
        self.assertIn("It does not mean zero", out)
        self.assertIn("not thousands or millions", out)
        # What this source cannot provide is said once, with FN2's reason.
        self.assertFalse(any(l.startswith("market cap") for l in lines))
        self.assertIn("not available from this source: market cap (historical "
                      "source unavailable)", out)
        self.assertIn("data-quality flag, period ending 2026-09-30", out)
        self.assertIn("fiscal fourth quarter", out)

    def test_ttm_is_not_steered_to_and_its_refusal_is_relayed_as_sent(self):
        sentence = ("FN2 has no trailing-twelve-month figures for NFLX. A TTM "
                    "period needs four consecutive quarterly (10-Q) filings, "
                    "and a fiscal fourth quarter is reported on the annual "
                    "10-K instead. Use the annual or quarterly variant.")
        self.routes[V1 + "/research/financials"] = _problem(404, sentence,
                                                            "not_found")
        code, out, err = self.run_cli("financials", "NFLX", "--ttm")
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err.strip(), "error: HTTP 404: " + sentence)
        self.assertEqual(self.last()[2]["variant"], "ttm")

        code, out, _ = self.run_cli("financials", "--help")
        self.assertIn("rarely available", " ".join(out.split()))
        self.assertIn("prefer --quarterly or --annual", " ".join(out.split()))
        root = pathlib.Path(__file__).resolve().parent.parent
        skill = (root / "skills" / "fn2" / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("--ttm", skill)  # the prompt no longer suggests it
        reference = (root / "skills" / "fn2" / "references" /
                     "research.md").read_text(encoding="utf-8")
        self.assertIn("`--ttm` exists but is rarely available", reference)

    def test_financials_says_when_fn2_withheld_a_growth_figure(self):
        reason = ("implied diluted share count changed 9.98x year over year "
                  "(a stock split or similar); per-share figures are not "
                  "comparable")
        payload = json.loads(json.dumps(FINANCIALS))
        newest = payload["periods"][1]
        newest["values"]["diluted_eps_growth"] = None
        newest["quality"]["growth_withheld"] = {"diluted_eps_growth": reason}
        self.routes[V1 + "/research/financials"] = payload
        out = self.ok("financials", "NFLX", "--quarterly")
        row = next(l for l in out.splitlines()
                   if l.startswith("diluted EPS growth YoY %"))
        self.assertEqual(row.split()[-2:], ["-", "-"])
        self.assertIn("withheld by FN2, period ending 2026-09-30: diluted EPS "
                      f"growth YoY %. Reason: {reason}. Do not compute it from "
                      "the per-share rows.", out)

    def test_financials_keeps_fields_the_cli_has_never_heard_of(self):
        payload = json.loads(json.dumps(FINANCIALS))
        payload["periods"][1]["values"]["share_buybacks"] = 1900000000
        self.routes[V1 + "/research/financials"] = payload
        out = self.ok("financials", "NFLX", "--quarterly")
        line = next(l for l in out.splitlines() if l.startswith("share_buybacks"))
        self.assertEqual(line.split()[-2:], ["1,900,000,000", "-"])

    def test_price_quote_only(self):
        out = self.ok("price", "NFLX")
        self.assertEqual(self.last()[1:3], (V1 + "/research/prices",
                                            {"symbol": "NFLX"}))
        self.assertIn("NFLX quote | market session now: closed | source: fmp | "
                      "delayed market data, not a real-time trading feed", out)
        self.assertIn("regular   price 1,112.17 | change -8.9 (-0.7939%) | "
                      "previous close 1,121.07 | as of "
                      "2026-11-10T16:00:00-05:00", out)
        self.assertIn("extended  price 1,113.5 | +0.1196% vs the regular price "
                      "above | as of 2026-11-10T19:58:00-05:00", out)
        self.assertIn("history   not requested", out)

    def test_price_history_prints_every_bar_and_flags_server_truncation(self):
        out = self.ok("quote", "NFLX", "--range", "6m")  # alias; case-folded
        self.assertEqual(self.last()[2], {"symbol": "NFLX", "range": "6M"})
        self.assertIn("history 6M: 2 bars, oldest first", out)
        self.assertIn("FN2 returned only the most recent 2 bars", out)
        rows = [l.split() for l in out.splitlines() if l.startswith("2026-11-")]
        self.assertEqual(rows, [
            ["2026-11-09", "1,118", "1,125.5", "1,110.25", "1,121.07",
             "2,345,678"],
            ["2026-11-10", "1,120", "1,122", "1,108.9", "1,112.17",
             "1,987,654"],
        ])

    def test_price_without_an_extended_print_or_history_says_so(self):
        quote = dict(QUOTE, extended=None, session="open")
        self.routes[V1 + "/research/prices"] = {
            "symbol": "NFLX", "quote": quote,
            "history": {"range": "1D", "points": [],
                        "note": "No history available for this range."}}
        out = self.ok("price", "NFLX", "--range", "1D")
        self.assertIn("extended  not available", out)
        self.assertIn("history 1D: not available. No history available for "
                      "this range.", out)

    def test_price_range_is_validated_before_any_request(self):
        code, _, err = self.run_cli("price", "NFLX", "--range", "2W")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err)
        self.assertEqual(self.requests, [])

    def test_fred_series(self):
        out = self.ok("fred", "dgs10", "--limit", "2")
        self.assertEqual(self.last()[1:3], (V1 + "/research/fred",
                                            {"series_id": "DGS10", "limit": "2"}))
        self.assertIn("FRED DGS10 | Market Yield on U.S. Treasury Securities",
                      out)
        self.assertIn("frequency: Daily | units: Percent | seasonal "
                      "adjustment: NSA | category: rates", out)
        # HTTP-date metadata is normalised to ISO days.
        self.assertIn("FRED's own range: 1962-01-02 to 2026-11-10 | FRED last "
                      "updated 2026-11-10", out)
        self.assertIn("2 observations, oldest first (limit 2: the most recent",
                      out)
        rows = [l.split() for l in out.splitlines() if l.startswith("2026-11-")]
        self.assertEqual(rows, [["2026-11-09", "4.11", "-3.52"],
                                ["2026-11-10", "4.13", "+1.2"]])
        self.assertIn("not available for these observations: MOM %, QOQ %", out)

    def test_fred_without_a_series_lists_the_catalog(self):
        out = self.ok("fred")
        self.assertEqual(self.last()[2], {})  # no series, and no limit
        self.assertIn("FRED series FN2 tracks: 2 listed", out)
        row = next(l for l in out.splitlines() if l.startswith("UNRATE"))
        self.assertIn("1948-01-01", row)
        self.assertIn("2026-10-01", row)

    def test_fred_limit_defaults_to_60_and_is_refused_without_a_series(self):
        self.ok("fred", "DGS10")
        self.assertEqual(self.last()[2], {"series_id": "DGS10", "limit": "60"})
        before = len(self.requests)
        code, _, err = self.run_cli("fred", "--limit", "5")
        self.assertEqual(code, 1)
        self.assertIn("needs a SERIES_ID", err)  # not silently ignored
        self.assertEqual(len(self.requests), before)

    def test_research_commands_honour_the_origin_pin(self):
        code, _, err = self.run_cli("--base-url", "https://fn2.ai.evil.example",
                                    "earnings", "NFLX")
        self.assertEqual(code, 1)
        self.assertIn("refusing endpoint", err)
        self.assertEqual(self.requests, [])

    def test_recall_resolves_an_agent_name_and_shows_the_note(self):
        out = self.ok("recall", "holdings", "--agent", "watchlist", "--tag",
                      "holdings", "--limit", "5")
        self.assertEqual([r[1] for r in self.requests],
                         [V1 + "/agents", V1 + "/research/recall"])
        self.assertEqual(self.last()[2], {"query": "holdings",
                                          "agent_id": AGENT, "tag": "holdings",
                                          "limit": "5"})
        self.assertIn('saved memory (query "holdings", tag holdings, agent '
                      f"{AGENT}): 1 note", out)
        self.assertIn('tag holdings | key portfolio/nvda | agent "Watchlist '
                      'brief" (ebab1623) | updated 2026-11-01 14:02 UTC', out)
        self.assertIn("    User holds 120 NVDA at an average cost of 98.40.",
                      out)

    def test_recall_with_nothing_saved_is_not_an_error(self):
        self.routes[V1 + "/research/recall"] = {
            "query": None, "agent_id": None, "count": 0, "memories": []}
        out = self.ok("recall")
        self.assertEqual(self.last()[2], {"limit": "12"})
        self.assertIn("nothing found", out)
        self.assertIn("this is not an error", out)

    def test_every_research_command_passes_json_through(self):
        cases = {
            ("calls", "NFLX"): CALLS,
            ("transcript", "NFLX"): _transcript_page({}),
            ("search", "ad tier"): SEARCH,
            ("financials", "NFLX"): FINANCIALS,
            ("price", "NFLX"): {"symbol": "NFLX", "quote": QUOTE},
            ("fred", "DGS10"): FRED_SERIES,
            ("fred",): FRED_CATALOG,
            ("recall",): RECALL,
        }
        for argv, payload in cases.items():
            with self.subTest(argv=argv):
                self.assertEqual(json.loads(self.ok(*argv, "--json")), payload)

    def test_signed_out_points_at_the_sign_in(self):
        storage.clear_credential("https://fn2.ai")
        code, _, err = self.run_cli("earnings", "NFLX")
        self.assertEqual(code, 1)
        self.assertIn("fn2 auth login", err)
        self.assertEqual(self.requests, [])


# ---------------------------------------------------------------------------
# scope: sign-in asks for `research`; an older sign-in is told how to add it
# ---------------------------------------------------------------------------
MISSING_SCOPE = (403, {"error": "Missing scope: research"})


class ScopeTests(_Sandbox):
    def test_device_login_requests_research(self):
        self.assertEqual(deviceauth.DEFAULT_SCOPES,
                         ("agents", "models", "research"))
        sent = []

        class Stub:
            def post(self, path, body=None, auth=True):
                sent.append(body)
                return {}

        deviceauth.start(Stub(), harness="claude", client_os="linux")
        self.assertEqual(sent[0]["scopes"], ["agents", "models", "research"])

    def test_login_stores_the_granted_scopes(self):
        approved = {"status": "approved", "access_token": TOKEN,
                    "scopes": ["agents", "models", "research"],
                    "device_id": "d1", "expires_at": "2027-02-09T00:00:00Z",
                    "account": {"email_masked": "a***@e***.com"}}
        start = {"device_code": "fn2dc_" + "B" * 43, "user_code": "BCDF-GHJK",
                 "verification_uri": "https://fn2.ai/start", "interval": 5,
                 "expires_in": 900}
        with mock.patch.object(deviceauth, "start", return_value=start), \
             mock.patch.object(deviceauth, "poll_until_complete",
                               return_value=approved):
            out = self.ok("auth", "login", "--no-browser")
        self.assertIn("scopes: agents, models, research", out)
        self.assertEqual(storage.load_record()["scopes"],
                         ["agents", "models", "research"])

    def test_pre_research_sign_in_is_told_to_sign_in_again(self):
        self.sign_in(scopes=("agents", "models"))
        self.routes[V1 + "/research/earnings"] = MISSING_SCOPE
        code, out, err = self.run_cli("earnings", "NFLX")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("error: HTTP 403: Missing scope: research", err)
        self.assertIn("does not carry the `research` scope (it has: agents, "
                      "models)", err)
        self.assertIn("fn2 auth login --no-wait", err)
        self.assertIn("agents and schedules are untouched", err)
        self.assertIn("Then run this command again.", err)
        # Not the dead-credential message, and never a silent retry.
        self.assertNotIn("may be revoked", err)
        self.assertEqual(len(self.requests), 1)

    def test_every_research_command_gets_the_same_guidance(self):
        self.sign_in(scopes=("agents", "models"))
        commands = {
            "/research/earnings": ("earnings", "NFLX"),
            "/research/transcripts": ("calls", "NFLX"),
            "/research/transcripts/read": ("transcript", "NFLX"),
            "/research/transcripts/search": ("search", "ad tier"),
            "/research/financials": ("financials", "NFLX"),
            "/research/prices": ("price", "NFLX"),
            "/research/fred": ("fred", "DGS10"),
            "/research/recall": ("recall",),
        }
        for path, argv in commands.items():
            with self.subTest(command=argv[0]):
                self.routes[V1 + path] = MISSING_SCOPE
                code, _, err = self.run_cli(*argv)
                self.assertEqual(code, 1)
                self.assertIn("fn2 auth login --no-wait", err)

    def test_environment_credential_cannot_be_fixed_by_signing_in(self):
        os.environ["FN2_API_TOKEN"] = TOKEN
        self.routes[V1 + "/research/earnings"] = MISSING_SCOPE
        code, _, err = self.run_cli("earnings", "NFLX")
        self.assertEqual(code, 1)
        self.assertIn("the credential in FN2_API_TOKEN does not carry the "
                      "`research` scope", err)
        self.assertIn("cannot change an environment variable", err)
        self.assertNotIn("--no-wait", err)

    def test_stored_api_key_is_told_where_scopes_are_set(self):
        self.sign_in(scopes=None, token=APIKEY, kind="api_key")
        self.routes[V1 + "/research/earnings"] = MISSING_SCOPE
        code, _, err = self.run_cli("earnings", "NFLX")
        self.assertEqual(code, 1)
        self.assertIn("this API key was created without the `research` scope",
                      err)
        self.assertIn("Preferences > Developer", err)
        self.assertIn("fn2 auth login", err)

    def test_structured_scope_errors_are_understood_too(self):
        self.sign_in(scopes=("agents", "models"))
        self.routes[V1 + "/research/earnings"] = (403, {
            "error": "Forbidden", "code": "insufficient_scope",
            "required_scope": "research"})
        code, _, err = self.run_cli("earnings", "NFLX")
        self.assertIn("does not carry the `research` scope", err)

    def test_other_auth_failures_keep_the_generic_hint(self):
        self.sign_in()
        for status, body in ((401, {"error": "Invalid token"}),
                             (403, {"error": "Device token not permitted for "
                                             "this endpoint"})):
            with self.subTest(status=status):
                self.routes[V1 + "/research/earnings"] = (status, body)
                code, _, err = self.run_cli("earnings", "NFLX")
                self.assertEqual(code, 1)
                self.assertIn("may be revoked or out of scope", err)
                self.assertNotIn("--no-wait", err)

    def test_permissions_shows_research_as_missing_or_granted(self):
        self.sign_in(scopes=("agents", "models"))
        out = self.ok("permissions")
        granted, _, rest = out.partition("not granted yet:")
        self.assertEqual([l.split()[0] for l in granted.splitlines()[1:] if l],
                         ["agents", "models"])
        self.assertTrue(rest.lstrip().startswith("research"), rest)
        self.assertIn("fn2 auth login", rest)
        payload = json.loads(self.ok("permissions", "--json"))
        self.assertEqual([s["scope"] for s in payload["scopes"]],
                         ["agents", "models"])
        self.assertEqual(payload["missing_scopes"][0]["scope"], "research")
        self.assertIs(payload["research_access"], False)

        self.sign_in()
        out = self.ok("permissions")
        self.assertNotIn("not granted yet", out)
        line = next(l for l in out.splitlines() if l.strip().startswith("research"))
        self.assertIn("research  Read FN2 AI research data directly", line)
        payload = json.loads(self.ok("permissions", "--json"))
        self.assertEqual(payload["missing_scopes"], [])
        self.assertIs(payload["research_access"], True)

    def test_an_api_key_with_unknown_scopes_is_not_credited_with_research(self):
        self.sign_in(scopes=None, token=APIKEY, kind="api_key")
        out = self.ok("permissions")
        self.assertNotIn("not granted yet", out)  # unknown is not "missing"
        self.assertFalse(any(l.strip().startswith("research")
                             for l in out.splitlines()))
        self.assertIn("need `research`", out)
        self.assertIsNone(json.loads(self.ok("permissions", "--json"))
                          ["research_access"])

    def test_auth_status_flags_a_sign_in_without_research(self):
        self.sign_in(scopes=("agents", "models"))
        out = self.ok("auth", "status")
        self.assertIn("scopes     agents, models", out)
        self.assertIn("research   not granted. Run `fn2 auth login` again",
                      out)
        self.assertIs(json.loads(self.ok("auth", "status", "--json"))
                      ["research_access"], False)

        self.sign_in()
        out = self.ok("auth", "status")
        self.assertNotIn("not granted", out)
        self.assertIs(json.loads(self.ok("auth", "status", "--json"))
                      ["research_access"], True)

    def test_the_servers_view_of_device_scopes_wins_over_the_local_record(self):
        # The stored record says research; the live credential does not have it.
        self.sign_in()
        self.routes[V1 + "/usage"] = dict(USAGE, device={
            "label": "claude on linux", "scopes": ["agents", "models"]})
        self.assertIn("research   not granted", self.ok("auth", "status"))
        self.assertIn("research scope not granted", self.ok("whoami"))

    def test_whoami_shows_the_weekly_research_allowance(self):
        self.sign_in()
        out = self.ok("whoami")
        self.assertIn("research   3 used / 25 per week / 22 left (resets "
                      "2026-11-16 00:00 UTC)", out)
        self.assertNotIn("not granted", out)

        self.routes[V1 + "/usage"] = dict(USAGE, research_requests={
            "used": 1234, "limit": None, "remaining": None, "unlimited": True,
            "period": "week", "resets_at": None})
        self.assertIn("research   1,234 requests used this week (unlimited)",
                      self.ok("whoami"))

        # An older server without the block: no row, no crash.
        self.routes[V1 + "/usage"] = {"plan": "free"}
        self.assertNotIn("research", self.ok("whoami"))


# ---------------------------------------------------------------------------
# quota and upstream errors
# ---------------------------------------------------------------------------
class QuotaTests(_Sandbox):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_exhausted_allowance_is_relayed_verbatim_and_never_retried(self):
        self.routes[V1 + "/research/earnings"] = _problem(
            429, QUOTA_SENTENCE, "api_quota_exceeded",
            quota={"used": 25, "limit": 25, "remaining": 0, "period": "week",
                   "resets_at": "2026-11-16T00:00:00+00:00"},
            plan="free", is_trial=False,
            upgrade_url="https://fn2.ai/preferences#billing")
        code, out, err = self.run_cli("earnings", "NFLX")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        lines = err.splitlines()
        # The API's sentence, whole and unprefixed by an HTTP status.
        self.assertEqual(lines[0], "error: " + QUOTA_SENTENCE)
        self.assertIn("do not retry", lines[1])
        self.assertIn("fn2 whoami", lines[1])
        self.assertEqual(len(self.requests), 1)

    def test_a_quota_check_outage_is_retryable_and_does_not_claim_exhaustion(self):
        self.routes[V1 + "/research/prices"] = _problem(
            503, "Unable to verify your usage limits right now. Please try "
                 "again shortly.", "quota_check_failed", retryable=True,
            retry_after=30)
        code, _, err = self.run_cli("price", "NFLX")
        self.assertEqual(code, 1)
        self.assertIn("Unable to verify your usage limits right now", err)
        self.assertIn("retry after 30s", err)
        self.assertNotIn("do not retry", err)
        self.assertEqual(len(self.requests), 1)

    def test_an_unavailable_source_says_when_to_retry(self):
        self.routes[V1 + "/research/transcripts/search"] = _problem(
            503, "Transcript search is temporarily unavailable. Please try "
                 "again shortly.", "upstream_unavailable", retryable=True,
            retry_after=15)
        code, _, err = self.run_cli("search", "ad tier")
        self.assertEqual(code, 1)
        self.assertIn("Transcript search is temporarily unavailable", err)
        self.assertIn("retry after 15s", err)
        self.assertIn("req_test", err)


# ---------------------------------------------------------------------------
# long output: said up front, never cut silently
# ---------------------------------------------------------------------------
class LongOutputTests(_Sandbox):
    def setUp(self):
        super().setUp()
        self.sign_in()
        block = "Ted Sarandos: " + "We keep investing in great stories. " * 20
        self.long_text = "\n\n".join(block for _ in range(60))
        self.routes[V1 + "/research/transcripts/read"] = {
            "transcript_id": TID, "symbol": "NFLX", "call_date": "2026-10-20",
            "fiscal_year": 2026, "fiscal_quarter": 3,
            "characters": len(self.long_text), "offset": 0,
            "returned": len(self.long_text), "next_offset": None,
            "text": self.long_text}

    def test_output_past_the_assistant_ceiling_warns_on_the_first_line(self):
        self.assertGreater(len(self.long_text), cli._ASSISTANT_OUTPUT_LIMIT)
        out = self.ok("transcript", "NFLX", "--max-chars", "60000")
        first = out.splitlines()[0]
        self.assertTrue(first.startswith("note: this output is "), first)
        self.assertIn("30,000", first)
        self.assertIn("--max-chars", first)
        # Warned, but still complete: nothing is dropped by the CLI itself.
        self.assertIn(self.long_text, out)
        self.assertTrue(out.rstrip().endswith("there is no next page."))

    def test_the_default_page_fits_under_the_ceiling_with_its_framing(self):
        page = ("Operator: " + "x" * 189 + "\n") * 120  # exactly 24,000
        self.assertEqual(len(page), cli._TRANSCRIPT_PAGE)
        self.routes[V1 + "/research/transcripts/read"] = {
            "transcript_id": TID, "symbol": "NFLX", "call_date": "2026-10-20",
            "fiscal_year": 2026, "fiscal_quarter": 3, "characters": 160000,
            "offset": 0, "returned": len(page), "next_offset": 24000,
            "text": page}
        out = self.ok("transcript", "NFLX")
        self.assertFalse(out.startswith("note:"))
        self.assertLess(len(out), cli._ASSISTANT_OUTPUT_LIMIT)

    def test_a_terminal_reader_gets_no_note(self):
        with mock.patch.object(cli, "_stdout_is_terminal", return_value=True):
            out = self.ok("transcript", "NFLX", "--max-chars", "60000")
        self.assertFalse(out.startswith("note:"))
        self.assertIn(self.long_text, out)

    def test_json_is_never_prefixed(self):
        out = self.ok("transcript", "NFLX", "--max-chars", "60000", "--json")
        self.assertEqual(json.loads(out)["text"], self.long_text)

    def test_text_a_legacy_code_page_cannot_encode_does_not_abort_the_read(self):
        text = "Greg Peters: Margin ≥ 30% — as we told 投资者 last quarter.\n"
        self.routes[V1 + "/research/transcripts/read"] = {
            "transcript_id": TID, "symbol": "NFLX", "call_date": "2026-10-20",
            "fiscal_year": 2026, "fiscal_quarter": 3, "characters": len(text),
            "offset": 0, "returned": len(text), "next_offset": None,
            "text": text}
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252", newline="\n")
        with contextlib.redirect_stdout(stream), \
                contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["transcript", "NFLX"])
            stream.flush()
        self.assertEqual(code, 0)
        printed = raw.getvalue().decode("cp1252")
        # What cp1252 can hold is intact; what it cannot is escaped, not lost.
        self.assertIn("Margin \\u2265 30% — as we told \\u6295\\u8d44\\u8005",
                      printed)
        self.assertIn("end of call", printed)


# ---------------------------------------------------------------------------
# render: exact numbers, and no crash on sparse payloads
# ---------------------------------------------------------------------------
class RenderTests(unittest.TestCase):
    def test_numbers_are_exact_never_rounded_or_abbreviated(self):
        fmt = render.fmt_number
        self.assertEqual(fmt(12874180000), "12,874,180,000")
        self.assertEqual(fmt(12874180000.0), "12,874,180,000")
        self.assertEqual(fmt(0.87), "0.87")
        self.assertEqual(fmt(1234.5678), "1,234.5678")
        self.assertEqual(fmt(-4850000), "-4,850,000")
        self.assertEqual(fmt("4.110"), "4.110")          # NUMERIC as a string
        self.assertEqual(fmt("12874180000"), "12,874,180,000")
        self.assertEqual(fmt("n/a"), "n/a")
        self.assertEqual(fmt(0), "0")
        self.assertIsNone(fmt(None))
        self.assertIsNone(fmt(True))
        self.assertIsNone(fmt(""))
        self.assertEqual(fmt(0.05, signed=True), "+0.05")
        self.assertEqual(fmt(-0.05, signed=True), "-0.05")
        self.assertEqual(fmt(0, signed=True), "0")
        self.assertEqual(fmt("1.2", signed=True), "+1.2")

    def test_views_tolerate_empty_and_partial_payloads(self):
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink):
            for view in (render.earnings, render.calls, render.transcript,
                         render.transcript_search, render.financials,
                         render.price, render.fred, render.recall):
                view({})
            render.earnings({"symbol": "X", "reported": [{}], "next": {}})
            render.earnings({"symbol": "X", "reported": [
                {"eps": None, "revenue": "bad", "call": {"transcript_id": None}}]})
            render.calls({"calls": [{}]})
            render.transcript({"text": "A: b", "next_offset": 10})
            render.transcript_search({"results": [{}]})
            render.financials({"periods": [{"values": None}, {}]})
            render.price({"quote": {"regular": None},
                          "history": {"points": [["x", 1], [], None]}})
            render.fred({"series_id": "X", "observations": [{}]})
            render.fred({"series": [{}]})
            render.recall({"memories": [{}]})
            render.usage({"research_requests": {}})
        self.assertIn("not available", sink.getvalue())

    def test_an_empty_earnings_payload_states_that_nothing_is_held(self):
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink):
            render.earnings({"symbol": "XYZ", "reported": [], "next": None})
        self.assertIn("XYZ earnings: no reported quarters in FN2's data",
                      sink.getvalue())
        self.assertIn("next report: not available", sink.getvalue())

    def test_daily_bars_print_as_dates_without_zone_data(self):
        sink = io.StringIO()
        with mock.patch.object(render, "_market_zone",
                               return_value=(render.dt.timezone.utc, "UTC")), \
                contextlib.redirect_stdout(sink):
            render.price({"symbol": "NFLX", "quote": QUOTE, "history": HISTORY})
        rows = [l.split() for l in sink.getvalue().splitlines()
                if l.startswith("2026-11-")]
        self.assertEqual([r[0] for r in rows], ["2026-11-09", "2026-11-10"])
        self.assertEqual(len(rows[0]), 6)  # date + OHLCV, no time column

    def test_intraday_history_shows_times_and_names_the_zone(self):
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink):
            render.price({"symbol": "NFLX", "quote": QUOTE, "history": {
                "range": "1D",
                "point_format": ["timestamp_ms", "close", "volume", "open",
                                 "high", "low"],
                # 2026-11-10 14:30 and 14:35 UTC
                "points": [[1794321000000, 1.5, 10, 1.0, 2.0, 0.5],
                           [1794321300000, 1.6, 11, 1.5, 2.1, 1.4]]}})
        out = sink.getvalue()
        self.assertRegex(out, r"history 1D: 2 bars, oldest first, times in "
                              r"(ET|UTC)")
        self.assertRegex(out, r"(?m)^2026-11-10 (09:30|14:30)\s+1\s+2\s+0\.5"
                              r"\s+1\.5\s+10$")


if __name__ == "__main__":
    unittest.main()
