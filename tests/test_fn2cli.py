"""Offline unit tests for the fn2 skill. No network, no credentials on disk."""

from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import urllib.error

# Make the bundled package importable without installation.
_SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from fn2cli import api, config, render, schedule  # noqa: E402
from fn2cli.client import ApiError, AuthError, Client  # noqa: E402


# ---------------------------------------------------------------------------
# schedule
# ---------------------------------------------------------------------------
class ScheduleTests(unittest.TestCase):
    def test_empty_is_run_now(self):
        for value in (None, "", "   "):
            self.assertEqual(schedule.parse_when(value).kind, "now")
            self.assertIsNone(schedule.parse_when(value).payload)

    def test_named_frequencies(self):
        for phrase, freq in (("daily", "daily"), ("every weekday", "weekdays"),
                             ("hourly", "hourly")):
            sched = schedule.parse_when(phrase)
            self.assertEqual(sched.kind, "recurring")
            self.assertEqual(sched.payload["frequency"], freq)
            self.assertEqual(sched.payload["timezone"], "UTC")

    def test_market_open_is_weekday_cron_in_et(self):
        sched = schedule.parse_when("before market open")
        self.assertEqual(sched.kind, "recurring")
        self.assertEqual(sched.payload["cron"], "0 9 * * 1-5")
        self.assertEqual(sched.payload["timezone"], "America/New_York")

    def test_time_qualified_weekdays(self):
        sched = schedule.parse_when("weekdays at 8:30am")
        self.assertEqual(sched.payload["cron"], "30 8 * * 1-5")

    def test_pm_time_and_24h(self):
        self.assertEqual(schedule.parse_when("daily at 4pm").payload["cron"], "0 16 * * *")
        self.assertEqual(schedule.parse_when("daily 16:00").payload["cron"], "0 16 * * *")

    def test_explicit_cron_requires_five_fields(self):
        self.assertEqual(schedule.parse_when("cron:0 9 * * 1-5").payload["cron"],
                         "0 9 * * 1-5")
        with self.assertRaises(schedule.ScheduleError):
            schedule.parse_when("cron:0 9 * *")

    def test_next_market_open_is_one_off(self):
        sched = schedule.parse_when("before next market open")
        self.assertEqual(sched.kind, "once")
        self.assertIn("run_at", sched.payload)
        self.assertTrue(sched.payload["run_at"].endswith("Z"))

    def test_iso_one_off(self):
        sched = schedule.parse_when("2026-07-22T13:00")
        self.assertEqual(sched.kind, "once")
        self.assertEqual(sched.payload["run_at"], "2026-07-22T13:00:00Z")

    def test_unparseable_raises(self):
        with self.assertRaises(schedule.ScheduleError):
            schedule.parse_when("whenever the vibes are right")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
class ConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._env = {k: os.environ.get(k) for k in
                     ("FN2_API_KEY", "FN2_BASE_URL", "FN2_CONFIG_HOME", "FN2_DOTENV")}
        os.environ["FN2_CONFIG_HOME"] = self._tmp.name
        os.environ["FN2_DOTENV"] = os.path.join(self._tmp.name, "nope.env")
        os.environ.pop("FN2_API_KEY", None)
        os.environ.pop("FN2_BASE_URL", None)

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_default_base_url_and_no_key(self):
        settings = config.resolve()
        self.assertEqual(settings.base_url, config.DEFAULT_BASE_URL)
        self.assertFalse(settings.authenticated)
        self.assertEqual(settings.source, "none")

    def test_env_beats_file(self):
        config.save_token("fn2_fromfile00000000", "https://file.example")
        os.environ["FN2_API_KEY"] = "fn2_fromenv000000000"
        settings = config.resolve()
        self.assertEqual(settings.api_key, "fn2_fromenv000000000")
        self.assertEqual(settings.source, "env")

    def test_save_is_0600_and_roundtrips(self):
        path = config.save_token("fn2_secretkey00000000")
        self.assertEqual(config.resolve().api_key, "fn2_secretkey00000000")
        mode = os.stat(path).st_mode & 0o777
        self.assertEqual(mode, 0o600)
        self.assertTrue(config.clear_token())
        self.assertFalse(config.resolve().authenticated)

    def test_dotenv_is_read(self):
        dotenv = os.path.join(self._tmp.name, "some.env")
        with open(dotenv, "w", encoding="utf-8") as fh:
            fh.write("# comment\nFN2_API_KEY = fn2_fromdotenv0000000\n")
        os.environ["FN2_DOTENV"] = dotenv
        settings = config.resolve()
        self.assertEqual(settings.api_key, "fn2_fromdotenv0000000")
        self.assertEqual(settings.source, "dotenv")

    def test_mask_and_key_shape(self):
        self.assertTrue(config.looks_like_key("fn2_abcdef"))
        self.assertFalse(config.looks_like_key("nope"))
        self.assertEqual(config.mask("fn2_abcdefwxyz"), "fn2_…wxyz")
        self.assertEqual(config.mask(None), "(none)")


# ---------------------------------------------------------------------------
# client (transport swapped out)
# ---------------------------------------------------------------------------
class _FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200):
        super().__init__(body)
        self._status = status

    def getcode(self):
        return self._status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class ClientTests(unittest.TestCase):
    def _client(self, response=None, error=None):
        client = Client("https://fn2.example", "fn2_key")

        def fake_urlopen(request):
            if error is not None:
                raise error
            client.last_request = request
            return response

        client._urlopen = fake_urlopen  # type: ignore[assignment]
        return client

    def test_get_parses_json(self):
        client = self._client(_FakeResponse(b'{"ok": true}'))
        self.assertEqual(client.get("/api/v1/usage"), {"ok": True})
        self.assertEqual(client.last_request.get_header("Authorization"), "Bearer fn2_key")

    def test_204_is_empty_dict(self):
        client = self._client(_FakeResponse(b"", status=204))
        self.assertEqual(client.delete("/api/v1/agents/x"), {})

    def test_missing_key_raises_auth(self):
        client = Client("https://fn2.example", None)
        with self.assertRaises(AuthError):
            client.get("/api/v1/agents")

    def test_401_becomes_auth_error(self):
        err = urllib.error.HTTPError(
            "u", 401, "Unauthorized", {},
            io.BytesIO(json.dumps({"error": "bad key", "code": "invalid"}).encode()))
        client = self._client(error=err)
        with self.assertRaises(AuthError) as ctx:
            client.get("/api/v1/agents")
        self.assertEqual(ctx.exception.status, 401)
        self.assertEqual(ctx.exception.code, "invalid")

    def test_500_becomes_api_error(self):
        err = urllib.error.HTTPError("u", 500, "boom", {}, io.BytesIO(b"nope"))
        client = self._client(error=err)
        with self.assertRaises(ApiError) as ctx:
            client.get("/api/v1/agents")
        self.assertNotIsInstance(ctx.exception, AuthError)
        self.assertEqual(ctx.exception.status, 500)


# ---------------------------------------------------------------------------
# api layer (records calls against a stub client)
# ---------------------------------------------------------------------------
class _StubClient:
    def __init__(self):
        self.calls = []

    def _record(self, method, path, **kw):
        self.calls.append((method, path, kw))
        return {"ok": True}

    def get(self, path, **kw):
        return self._record("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self._record("POST", path, body=body, **kw)

    def patch(self, path, body=None, **kw):
        return self._record("PATCH", path, body=body, **kw)

    def delete(self, path, **kw):
        return self._record("DELETE", path, **kw)


class ApiTests(unittest.TestCase):
    def test_create_agent_body(self):
        stub = _StubClient()
        api.create_agent(stub, prompt="hi", name="n", model="m",
                         labels=["a"], schedule={"frequency": "daily"})
        method, path, kw = stub.calls[0]
        self.assertEqual((method, path), ("POST", "/api/v1/agents"))
        self.assertEqual(kw["body"], {"prompt": "hi", "name": "n", "model": "m",
                                      "labels": ["a"], "schedule": {"frequency": "daily"}})

    def test_create_agent_omits_empty(self):
        stub = _StubClient()
        api.create_agent(stub, prompt="hi")
        self.assertEqual(stub.calls[0][2]["body"], {"prompt": "hi"})

    def test_run_and_result_paths(self):
        stub = _StubClient()
        api.run_agent(stub, "abc")
        api.get_run(stub, "abc", "r1")
        self.assertEqual(stub.calls[0][:2], ("POST", "/api/v1/agents/abc/run"))
        self.assertEqual(stub.calls[1][:2], ("GET", "/api/v1/agents/abc/runs/r1"))

    def test_update_drops_none(self):
        stub = _StubClient()
        api.update_agent(stub, "abc", status="paused", name=None)
        self.assertEqual(stub.calls[0][2]["body"], {"status": "paused"})


# ---------------------------------------------------------------------------
# render (smoke — must not crash on sparse data)
# ---------------------------------------------------------------------------
class RenderTests(unittest.TestCase):
    def test_views_tolerate_missing_fields(self):
        render.agents({"agents": [{"id": "x"}], "total": 1})
        render.agent_detail({"id": "x"})
        render.runs({"runs": [{"run_id": "r"}]})
        render.run_result({"run_id": "r", "result": {"text": "hello"}})
        render.usage({"plan": "free", "tokens": {"used": 1, "limit": 2, "remaining": 1}})
        render.models([{"model_id": "m", "is_default": True}])

    def test_rel_ts_handles_bad_input(self):
        self.assertEqual(render.rel_ts(None), "never")
        self.assertEqual(render.rel_ts("not-a-date"), "not-a-date")


if __name__ == "__main__":
    unittest.main()
