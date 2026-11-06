"""Exercise cookbook commands through the shipped CLI. All responses are fixtures."""
import contextlib
import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "skills" / "fn2" / "examples"
spec = importlib.util.spec_from_file_location("cookbook", EXAMPLES / "cookbook.py")
cookbook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cookbook)
from fn2cli import cli, config  # noqa: E402
from fn2cli.client import Client  # noqa: E402

AGENT = "11111111-1111-4111-8111-111111111111"
RUN = "22222222-2222-4222-8222-222222222222"
CASES = [
    ["earnings", "--ticker", "IBM", "--earlier", "FY2025 Q2", "--later", "FY2025 Q3", "--as-of", "2025-11-01"],
    ["reconcile", "--ticker", "IBM", "--period", "FY2025 Q3", "--as-of", "2025-11-01"],
    ["watchlist", "--tickers", "AAPL", "MSFT", "NVDA"],
]


class Response(io.BytesIO):
    def getcode(self):
        return 200


class CookbookTests(unittest.TestCase):
    def capture(self, function, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = function(argv)
        self.assertEqual(code, 0)
        return out.getvalue()

    def test_all_previews_are_offline_and_never_resolve_credentials(self):
        with mock.patch.object(config, "resolve", side_effect=AssertionError("credential access")), \
             mock.patch("urllib.request.urlopen", side_effect=AssertionError("network access")):
            for argv in CASES:
                with self.subTest(recipe=argv[0]):
                    plan = json.loads(self.capture(cookbook.main, argv))
                    self.assertTrue(plan["preview_only"])
                    self.assertIsNone(plan["schedule"])
                    self.assertNotIn("--execute", plan["cli_argv"])
                    self.assertIn("source ledger", plan["cli_argv"][2])
                    self.assertEqual(cli.build_parser().parse_args(plan["cli_argv"]).command, "start")

    def test_three_recipes_create_and_retrieve_via_real_http_contract(self):
        settings = config.Settings("offline-fixture-credential", "https://fn2.ai", "https://fn2.ai/start", "env")
        for argv in CASES:
            requests = []

            def transport(client, request):
                path = urlsplit(request.full_url).path
                body = json.loads(request.data) if request.data else None
                requests.append((request.method, path, body))
                self.assertEqual(request.get_header("Authorization"), "Bearer offline-fixture-credential")
                if request.method == "POST" and path == "/api/v1/agents":
                    response = {"id": AGENT, "status": "pending"}
                elif path == "/api/v1/agents/" + AGENT + "/runs":
                    response = {"runs": [{"run_id": RUN, "status": "completed"}]}
                elif path == "/api/v1/agents/" + AGENT + "/runs/" + RUN:
                    response = {"run_id": RUN, "status": "completed", "result": {"text": "OFFLINE FIXTURE: no research performed"}}
                else:
                    self.fail("unexpected HTTP request: " + request.method + " " + path)
                return Response(json.dumps(response).encode())

            with self.subTest(recipe=argv[0]), mock.patch.object(config, "resolve", return_value=settings), \
                 mock.patch.object(Client, "_urlopen", new=transport):
                receipt = json.loads(self.capture(cookbook.main, argv + ["--execute"]))
                self.assertEqual(receipt["id"], AGENT)
                self.assertEqual(len(requests), 1)  # no duplicate create or hidden research request
                body = requests[0][2]
                self.assertNotIn("schedule", body)
                self.assertNotIn("delivery", body)
                self.assertNotIn("model", body)  # use the service default, never a stale fixed ID
                self.assertNotIn("$ticker", body["prompt"])
                self.assertNotIn("$as_of", body["prompt"])
                self.assertEqual(body["labels"], ["cookbook:" + argv[0]])
                result = self.capture(cli.main, ["--json", "result", AGENT])
                self.assertIn("OFFLINE FIXTURE", result)
                self.assertNotIn("offline-fixture-credential", result)

    def test_bounded_schedule_and_pause_use_existing_api_fields(self):
        end = str(dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=7))
        argv = CASES[2] + ["--schedule", "--ends", end, "--model", "account-model-id"]
        plan = json.loads(self.capture(cookbook.main, argv))
        expected = {"frequency": "market_open", "offset_minutes": -30,
                    "timezone": "America/New_York", "ends_at": end}
        self.assertEqual(plan["schedule"], expected)
        requests = []

        def transport(client, request):
            requests.append((request.method, urlsplit(request.full_url).path, json.loads(request.data)))
            return Response(json.dumps({"id": AGENT}).encode())

        settings = config.Settings("offline-fixture-credential", "https://fn2.ai", "https://fn2.ai/start", "env")
        with mock.patch.object(config, "resolve", return_value=settings), mock.patch.object(Client, "_urlopen", new=transport):
            self.capture(cookbook.main, argv + ["--execute"])
            self.capture(cli.main, ["pause", AGENT])
        self.assertEqual(requests[0][:2], ("POST", "/api/v1/agents"))
        self.assertEqual(requests[0][2]["schedule"], expected)
        self.assertEqual(requests[0][2]["model"], "account-model-id")
        self.assertNotIn("delivery", requests[0][2])
        self.assertEqual(requests[1], ("PATCH", "/api/v1/agents/" + AGENT, {"status": "paused"}))

    def test_invalid_or_unbounded_inputs_fail_before_network(self):
        bad = [CASES[2] + ["--schedule"],
               CASES[2] + ["--schedule", "--ends", "2020-01-01"],
               CASES[2] + ["--schedule", "--ends", "2099-01-01"],
               CASES[2] + ["--ends", "2099-01-01"],
               CASES[0] + ["--later", "FY2025 Q2"],
               CASES[0] + ["--as-of", "2099-01-01"],
               CASES[0] + ["--ticker", "IBM;echo secret"],
               CASES[1] + ["--as-of", "2025-02-30"]]
        with mock.patch.object(config, "resolve", side_effect=AssertionError("credential access")), \
             mock.patch("urllib.request.urlopen", side_effect=AssertionError("network access")):
            for argv in bad:
                with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    cookbook.main(argv + ["--execute"])
                self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
