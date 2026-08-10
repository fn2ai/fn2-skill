"""Offline unit tests for the fn2 skill. No network, no credentials on disk."""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

# Make the bundled package importable without installation.
_SCRIPTS = (pathlib.Path(__file__).resolve().parent.parent /
            "skills" / "fn2" / "scripts")
sys.path.insert(0, str(_SCRIPTS))

from fn2cli import api, cli, config, render, schedule, style  # noqa: E402
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

    def test_market_open_is_server_owned_offset(self):
        # Server owns the XNYS calendar: a market phase + signed offset, not a
        # client-hardcoded cron (which fired on holidays).
        sched = schedule.parse_when("before market open")
        self.assertEqual(sched.kind, "recurring")
        self.assertEqual(sched.payload["frequency"], "market_open")
        self.assertEqual(sched.payload["offset_minutes"], -30)
        self.assertEqual(sched.payload["timezone"], "America/New_York")
        self.assertNotIn("cron", sched.payload)

    def test_market_close_is_server_owned_offset(self):
        sched = schedule.parse_when("after close")
        self.assertEqual(sched.payload["frequency"], "market_close")
        self.assertEqual(sched.payload["offset_minutes"], 5)

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
        # One-shot market run: the client names the phase + offset; the SERVER
        # resolves the concrete next-session instant (no client-side run_at).
        sched = schedule.parse_when("before next market open")
        self.assertEqual(sched.kind, "once")
        self.assertEqual(sched.payload["market_event"], "open")
        self.assertEqual(sched.payload["offset_minutes"], -30)
        self.assertNotIn("run_at", sched.payload)

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
    _ENV_KEYS = ("FN2_API_TOKEN", "FN2_API_KEY", "FN2_BASE_URL",
                 "FN2_CONFIG_HOME", "FN2_DOTENV", "FN2_ALLOW_DEV_BASE")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._env = {k: os.environ.get(k) for k in self._ENV_KEYS}
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["FN2_CONFIG_HOME"] = self._tmp.name
        self._keychain = mock.patch.object(
            config.storage, "keychain_available", return_value=False)
        self._keychain.start()
        self.addCleanup(self._keychain.stop)

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

    def test_env_token_beats_legacy_and_file(self):
        config.save_token("fn2_fromfile00000000", "https://test.fn2.ai")
        os.environ["FN2_API_KEY"] = "fn2_fromlegacy000000"
        os.environ["FN2_API_TOKEN"] = "fn2d_fromenv00000000"
        settings = config.resolve()
        self.assertEqual(settings.api_key, "fn2d_fromenv00000000")
        self.assertEqual(settings.source, "env")
        self.assertEqual(settings.credential_kind, "device")

    def test_legacy_alias_beats_file(self):
        config.save_token("fn2_fromfile00000000", "https://test.fn2.ai")
        os.environ["FN2_API_KEY"] = "fn2_fromlegacy000000"
        settings = config.resolve()
        self.assertEqual(settings.api_key, "fn2_fromlegacy000000")
        self.assertEqual(settings.source, "env-legacy")

    def test_save_is_0600_and_roundtrips(self):
        path = config.save_token("fn2_secretkey00000000")
        self.assertEqual(config.resolve().api_key, "fn2_secretkey00000000")
        self.assertEqual(config.resolve().source, "file")
        mode = os.stat(path).st_mode & 0o777
        self.assertEqual(mode, 0o600)
        self.assertTrue(config.clear_token())
        self.assertFalse(config.resolve().authenticated)

    def test_dotenv_support_is_gone(self):
        self.assertFalse(hasattr(config, "load_dotenv"))
        dotenv = os.path.join(self._tmp.name, "some.env")
        with open(dotenv, "w", encoding="utf-8") as fh:
            fh.write("FN2_API_KEY = fn2_fromdotenv0000000\n")
        os.environ["FN2_DOTENV"] = dotenv  # must be inert now
        settings = config.resolve()
        self.assertIsNone(settings.api_key)
        self.assertEqual(settings.source, "none")

    def test_mask_and_key_shape(self):
        self.assertTrue(config.looks_like_key("fn2_abcdef"))
        self.assertFalse(config.looks_like_key("nope"))
        self.assertTrue(config.looks_like_credential("fn2d_" + "a" * 40))
        self.assertEqual(config.mask("fn2_abcdefwxyz"), "fn2_…wxyz")
        self.assertEqual(config.mask("fn2d_" + "a" * 36 + "wxyz"), "fn2d_…wxyz")
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

    def test_create_agent_email_maps_to_verified_self_delivery(self):
        stub = _StubClient()
        api.create_agent(stub, prompt="hi", email=True)
        # `email=True` → verified-account delivery flag; never a raw address.
        self.assertEqual(stub.calls[0][2]["body"],
                         {"prompt": "hi", "delivery": {"email": True}})

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

    def test_market_schedules_read_as_english(self):
        describe = render.describe_schedule
        self.assertEqual(
            describe({"schedule": {"frequency": "market_open", "offset_minutes": -30}}),
            "30m before open")
        self.assertEqual(
            describe({"schedule": {"frequency": "market_close", "offset_minutes": 5}}),
            "5m after close")
        # A missing/zero offset must still name the boundary, not crash.
        self.assertEqual(
            describe({"schedule": {"frequency": "market_close"}}), "at the close")
        # Non-market cadences are untouched.
        self.assertEqual(describe({"schedule": {"frequency": "weekdays"}}), "weekdays")
        self.assertEqual(
            describe({"schedule": {"frequency": "custom", "cron": "0 9 * * 1-5"}}),
            "cron 0 9 * * 1-5")

    def test_model_without_plan_lock_says_any(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            render.models([{"model_id": "m", "required_plan": None},
                           {"model_id": "n", "required_plan": "pro"}])
        rows = buffer.getvalue().splitlines()
        self.assertIn("any", rows[2])
        self.assertIn("pro", rows[3])

    def test_usage_labels_align_with_whoami(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            render.usage({"plan": "pro", "tokens": {"used": 1, "limit": 2,
                                                    "remaining": 1}})
        # `whoami` prints "endpoint   …" above this block; every label column
        # in the account views is 11 characters wide.
        for line in buffer.getvalue().splitlines():
            label = line.split(" ", 1)[0]
            self.assertEqual(line[:11], label.ljust(11), line)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Gateway error envelopes (the nginx `error: true` trap)
# ---------------------------------------------------------------------------

def _http_error(status, body):
    import io
    import urllib.error
    return urllib.error.HTTPError(
        "https://fn2.ai/api/v1/whatever", status, "Unauthorized", {},
        io.BytesIO(body.encode("utf-8")))


def test_gateway_error_envelope_does_not_put_a_bool_in_the_message():
    """nginx and Flask disagree about what `error` holds.

        Flask  {"error": "Agent not found", "code": "not_found"}
        nginx  {"error": true, "message": "No token provided", ...}

    The gateway's `error` is a BOOLEAN FLAG. Taking it verbatim put `True` in
    the message, and the next `str(exc)` raised
    `TypeError: can only concatenate str (not "bool")` — so every
    gateway-originated failure crashed the CLI with a traceback instead of
    printing the reason. `fn2 doctor` on a signed-out machine hit this on the
    first command a new user runs.
    """
    from fn2cli.client import AuthError, Client

    exc = Client("https://fn2.ai")._http_error(_http_error(
        401, '{"code":"UNAUTHORIZED","error":true,"message":"No token provided"}'))

    assert isinstance(exc, AuthError)
    assert exc.code == "UNAUTHORIZED"
    # The message is the human text, never the flag.
    assert exc.args[0] == "No token provided"
    assert str(exc) == "HTTP 401: No token provided"


def test_flask_error_envelope_still_reads_the_error_string():
    from fn2cli.client import Client

    exc = Client("https://fn2.ai")._http_error(_http_error(
        404, '{"error":"Agent not found","code":"not_found"}'))
    assert str(exc) == "HTTP 404: Agent not found"


def test_rendering_an_error_never_raises_whatever_the_payload_holds():
    """An error type that raises while being rendered turns a handled failure
    into a traceback. Coerce; never assume."""
    from fn2cli.client import ApiError, Client

    for body in ('{"error":true}', '{"error":123}', '{"error":null}',
                 '{"error":{"nested":"object"}}', '{}', 'not json at all'):
        exc = Client("https://fn2.ai")._http_error(_http_error(500, body))
        assert isinstance(str(exc), str)      # must not raise

    assert isinstance(str(ApiError(True, status=401)), str)
    assert isinstance(str(ApiError(None)), str)


def test_doctor_probes_an_endpoint_the_public_gateway_actually_allows():
    """The probe runs from a SIGNED-OUT machine, which is when doctor is run.

    /api/v1/market/status is public in stock-server but sits behind stock-web's
    nginx JWT gate, so it 401s for anyone without a session — the check could
    never pass before sign-in, the exact state doctor exists to diagnose.
    """
    import inspect

    from fn2cli import cli

    # Comments in cmd_doctor deliberately NAME the old path to explain why it
    # was wrong, so assert against code lines only — otherwise the explanation
    # trips the check it exists to justify.
    code = "\n".join(
        line for line in inspect.getsource(cli.cmd_doctor).splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "/api/v1/public-config" in code
    assert "market/status" not in code


# ---------------------------------------------------------------------------
# style (colour is opt-in and never changes column widths)
# ---------------------------------------------------------------------------
class StyleTests(unittest.TestCase):
    def tearDown(self):
        style.set_mode("auto")

    def test_off_when_not_a_tty(self):
        style.set_mode("auto")
        buffer = io.StringIO()  # StringIO.isatty() is False
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(style.paint("hi", "red"), "hi")

    def test_no_color_env_beats_a_tty(self):
        style.set_mode("auto")
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            with mock.patch("sys.stdout") as fake:
                fake.isatty.return_value = True
                self.assertEqual(style.paint("hi", "red"), "hi")

    def test_always_emits_and_strips_back(self):
        style.set_mode("always")
        painted = style.paint("active", "green")
        self.assertNotEqual(painted, "active")
        self.assertEqual(style.strip(painted), "active")
        self.assertEqual(style.width(painted), len("active"))

    def test_columns_ignore_escape_sequences(self):
        style.set_mode("always")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            render.table(["A", "B"], [[style.paint("xx", "green"), "1"],
                                      ["yyyy", "2"]])
        rows = [style.strip(line) for line in buffer.getvalue().splitlines()]
        # Column B starts at the same offset on every row.
        self.assertEqual(rows[2].index("1"), rows[3].index("2"))

    def test_json_output_is_never_colourised(self):
        from fn2cli import cli
        with mock.patch("sys.stdout") as fake:
            fake.isatty.return_value = True
            with self.assertRaises(SystemExit):
                cli.main(["--json", "--version"])
        style.set_mode("never")
        self.assertEqual(style.paint("x", "red"), "x")


# ---------------------------------------------------------------------------
# agent references: `fn2 agents` prints 8 chars, so 8 chars must work
# ---------------------------------------------------------------------------
class _AgentListStub:
    """A Client whose only job is to answer GET /agents."""

    def __init__(self, agents):
        self.agents = agents
        self.calls = 0

    def get(self, path, **kw):
        self.calls += 1
        return {"agents": self.agents, "total": len(self.agents)}


AGENTS = [
    {"id": "ebab1623-5957-4e49-a929-085afee5e496", "name": "Market Open Sentiment"},
    {"id": "e4c4a9e0-8652-4ae2-9f17-a0be2d4a4c26", "name": "Macro & rates digest"},
    {"id": "3a374644-8290-48cb-aa0b-3927288f8d15", "name": "Earnings reaction recap"},
]


class AgentReferenceTests(unittest.TestCase):
    def test_full_id_costs_no_request(self):
        stub = _AgentListStub(AGENTS)
        self.assertEqual(cli._resolve_agent(stub, AGENTS[0]["id"]), AGENTS[0]["id"])
        self.assertEqual(stub.calls, 0)

    def test_printed_short_id_resolves(self):
        stub = _AgentListStub(AGENTS)
        self.assertEqual(cli._resolve_agent(stub, "ebab1623"), AGENTS[0]["id"])

    def test_name_resolves_exactly_and_by_substring(self):
        stub = _AgentListStub(AGENTS)
        self.assertEqual(cli._resolve_agent(stub, "Macro & rates digest"), AGENTS[1]["id"])
        self.assertEqual(cli._resolve_agent(stub, "earnings"), AGENTS[2]["id"])

    def test_ambiguity_refuses_rather_than_guesses(self):
        stub = _AgentListStub(AGENTS)
        with self.assertRaises(SystemExit) as caught:
            cli._resolve_agent(stub, "e")
        message = str(caught.exception)
        self.assertIn("matches 2 agents", message)
        self.assertIn("ebab1623", message)

    def test_unknown_reference_names_the_fix(self):
        stub = _AgentListStub(AGENTS)
        with self.assertRaises(SystemExit) as caught:
            cli._resolve_agent(stub, "nope")
        self.assertIn("fn2 agents", str(caught.exception))


# ---------------------------------------------------------------------------
# --wait: uses the API's own long-poll instead of a client-side hammer loop
# ---------------------------------------------------------------------------
class _RunStub:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.waits = []

    def get(self, path, params=None, **kw):
        self.waits.append((params or {}).get("wait"))
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return {"run_id": "r1", "status": status}


class WaitTests(unittest.TestCase):
    def test_polls_until_terminal_and_passes_a_server_wait(self):
        stub = _RunStub(["pending", "running", "completed"])
        run = cli._await_run(stub, "a1", "r1", 300, lambda _m: None)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(len(stub.waits), 3)
        # The server caps its long-poll at 25s; never ask for more.
        self.assertTrue(all(0 <= w <= 25 for w in stub.waits), stub.waits)

    def test_gives_up_at_the_deadline_without_hanging(self):
        stub = _RunStub(["running"])
        said = []
        run = cli._await_run(stub, "a1", "r1", 0, said.append)
        self.assertEqual(run["status"], "running")
        self.assertEqual(len(stub.waits), 1)
        self.assertIn("fn2 result", said[0])


# ---------------------------------------------------------------------------
# glyphs: a cp1252 console must not take the command down over a tick mark
# ---------------------------------------------------------------------------
class GlyphTests(unittest.TestCase):
    def tearDown(self):
        style.reset_glyph_cache()

    def test_ascii_fallback_when_the_stream_cannot_encode(self):
        style.reset_glyph_cache()
        with mock.patch("sys.stdout") as fake:
            fake.encoding = "cp1252"
            self.assertEqual(style.glyph("ok"), "OK")
            self.assertEqual(style.glyph("star"), "*")

    def test_unicode_when_the_stream_can(self):
        style.reset_glyph_cache()
        with mock.patch("sys.stdout") as fake:
            fake.encoding = "utf-8"
            self.assertEqual(style.glyph("ok"), "\u2713")

    def test_every_glyph_survives_a_pure_ascii_stream(self):
        style.reset_glyph_cache()
        with mock.patch("sys.stdout") as fake:
            fake.encoding = "ascii"
            for name in ("ok", "pause", "play", "trash", "star", "ellipsis"):
                style.glyph(name).encode("ascii")  # must not raise


# ---------------------------------------------------------------------------
# errors: say when to retry, and which request to quote
# ---------------------------------------------------------------------------
class ErrorEnvelopeTests(unittest.TestCase):
    def test_retry_after_is_surfaced(self):
        client = Client("https://fn2.ai", "fn2_key")
        error = client._http_error(_http_error(
            429, json.dumps({"error": "quota exceeded", "code": "quota",
                             "retry_after": 42})))
        self.assertIn("retry after 42s", str(error))
        self.assertEqual(error.retry_after, 42)

    def test_request_id_is_attached_for_server_errors(self):
        client = Client("https://fn2.ai", "fn2_key")
        error = client._http_error(_http_error(
            503, json.dumps({"error": "upstream", "request_id": "req_abc"})))
        self.assertIn("req_abc", str(error))
