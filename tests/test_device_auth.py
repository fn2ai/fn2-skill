"""Offline tests for the device-authorization flow, storage, pinning, redaction.

No network, no real keychain: the HTTP seam (Client._urlopen / module
functions) and subprocess are mocked, exactly like the existing tests.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

# Make the bundled package importable without installation.
_SCRIPTS = (pathlib.Path(__file__).resolve().parent.parent /
            "skills" / "fn2" / "scripts")
sys.path.insert(0, str(_SCRIPTS))

from fn2cli import cli, config, deviceauth, storage  # noqa: E402
from fn2cli.client import ApiError, AuthError, Client  # noqa: E402

TOKEN = "fn2d_" + "A" * 36 + "wxyz"
APIKEY = "fn2_" + "C" * 36 + "wxyz"
DEVICE_CODE = "fn2dc_" + "B" * 43

APPROVED = {
    "status": "approved",
    "access_token": TOKEN,
    "token_type": "bearer",
    "scopes": ["agents", "models"],
    "device_id": "d1e2f3",
    "expires_at": "2026-10-19T00:00:00Z",
    "account": {"email_masked": "a***@e***.com"},
}

START_RESPONSE = {
    "device_code": DEVICE_CODE,
    "user_code": "BCDF-GHJK",
    "verification_uri": "https://fn2.ai/start",
    "interval": 5,
    "expires_in": 900,
}


class _EnvSandbox(unittest.TestCase):
    """Isolated FN2_* env + FN2_CONFIG_HOME in a tempdir."""

    _ENV_KEYS = ("FN2_API_TOKEN", "FN2_API_KEY", "FN2_BASE_URL",
                 "FN2_CONFIG_HOME", "FN2_ALLOW_DEV_BASE", "FN2_ONBOARD_URL")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._env = {k: os.environ.get(k) for k in self._ENV_KEYS}
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["FN2_CONFIG_HOME"] = self._tmp.name
        self._keychain = mock.patch.object(
            storage, "keychain_available", return_value=False)
        self._keychain.start()
        self.addCleanup(self._keychain.stop)

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run_cli(argv):
    """Run cli.main capturing stdout/stderr. -> (rc, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# harness / os detection
# ---------------------------------------------------------------------------
class DetectionTests(unittest.TestCase):
    def test_harness_heuristics(self):
        self.assertEqual(deviceauth.detect_harness({"CLAUDECODE": "1"}), "claude")
        self.assertEqual(deviceauth.detect_harness({"CLAUDE_CODE": "1"}), "claude")
        self.assertEqual(deviceauth.detect_harness({"CODEX_HOME": "/x"}), "codex")
        self.assertEqual(deviceauth.detect_harness({"HERMES_HOME": "/x"}), "pi")
        self.assertEqual(deviceauth.detect_harness({"PI_SESSION": "1"}), "pi")
        self.assertEqual(deviceauth.detect_harness({"PATH": "/bin"}), "other")

    def test_os_detection(self):
        self.assertEqual(deviceauth.detect_os("darwin"), "macos")
        self.assertEqual(deviceauth.detect_os("linux"), "linux")
        self.assertEqual(deviceauth.detect_os("win32"), "windows")
        self.assertEqual(deviceauth.detect_os("sunos5"), "other")

    def test_start_body_shape(self):
        calls = []

        class Stub:
            def post(self, path, body=None, auth=True):
                calls.append((path, body, auth))
                return dict(START_RESPONSE)

        deviceauth.start(Stub(), harness="claude", client_os="macos")
        path, body, auth = calls[0]
        self.assertEqual(path, deviceauth.START_PATH)
        self.assertFalse(auth)
        self.assertEqual(body["client"], "fn2-skill")
        self.assertEqual(body["harness"], "claude")
        self.assertEqual(body["os"], "macos")
        self.assertEqual(body["scopes"], ["agents", "models", "research"])
        from fn2cli import __version__
        self.assertEqual(body["client_version"], __version__)


# ---------------------------------------------------------------------------
# poll loop state machine
# ---------------------------------------------------------------------------
class _ScriptedPollClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, path, body=None, auth=True):
        self.calls.append((path, body, auth))
        return self.responses.pop(0)


class PollLoopTests(unittest.TestCase):
    def _loop(self, responses, *, interval=5, deadline=None):
        sleeps = []
        client = _ScriptedPollClient(responses)
        result = deviceauth.poll_until_complete(
            client, DEVICE_CODE, interval=interval, deadline=deadline,
            sleep=sleeps.append, now=lambda: 0.0,
        )
        return result, sleeps, client

    def test_pending_then_slow_down_bumps_interval_then_approved(self):
        result, sleeps, client = self._loop([
            {"status": "authorization_pending"},
            {"status": "slow_down", "interval": 10},
            {"status": "authorization_pending"},
            dict(APPROVED),
        ])
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["access_token"], TOKEN)
        self.assertEqual(sleeps, [5, 5, 10, 10])
        for path, body, auth in client.calls:
            self.assertEqual(path, deviceauth.POLL_PATH)
            self.assertEqual(body, {"device_code": DEVICE_CODE})
            self.assertFalse(auth)

    def test_slow_down_without_interval_adds_five(self):
        _, sleeps, _ = self._loop([
            {"status": "slow_down"},
            dict(APPROVED),
        ])
        self.assertEqual(sleeps, [5, 10])

    def test_denied_and_expired_are_terminal(self):
        result, _, client = self._loop([{"status": "denied"}])
        self.assertEqual(result["status"], "denied")
        self.assertEqual(len(client.calls), 1)
        result, _, client = self._loop([{"status": "expired"}])
        self.assertEqual(result["status"], "expired")

    def test_deadline_bounds_total_wait_without_polling(self):
        client = _ScriptedPollClient([])
        result = deviceauth.poll_until_complete(
            client, DEVICE_CODE, interval=5, deadline=10.0,
            sleep=lambda s: None, now=lambda: 100.0,
        )
        self.assertEqual(result["status"], "expired")
        self.assertEqual(client.calls, [])

    def test_malicious_interval_is_clamped_to_ceiling(self):
        # A compromised/buggy backend must never make the CLI sleep unbounded.
        _, sleeps, _ = self._loop([
            {"status": "slow_down", "interval": 999999999},
            dict(APPROVED),
        ])
        self.assertTrue(all(s <= deviceauth.MAX_INTERVAL for s in sleeps))

    def test_initial_interval_is_clamped(self):
        _, sleeps, _ = self._loop([dict(APPROVED)], interval=999999999)
        self.assertEqual(sleeps, [deviceauth.MAX_INTERVAL])

    def test_wait_never_outlives_deadline(self):
        # deadline in 3s but server asks for a 60s sleep: the sleep is trimmed
        # so the loop terminates at the deadline rather than overshooting.
        client = _ScriptedPollClient([{"status": "authorization_pending"}])
        sleeps = []
        clock = [0.0]
        def _now():
            return clock[0]
        def _sleep(s):
            sleeps.append(s)
            clock[0] += s
        result = deviceauth.poll_until_complete(
            client, DEVICE_CODE, interval=60, deadline=3.0,
            sleep=_sleep, now=_now,
        )
        self.assertEqual(result["status"], "expired")
        self.assertTrue(all(s <= 3 + deviceauth.GRACE_SECONDS for s in sleeps))

    def test_non_dict_poll_body_does_not_crash(self):
        # A truthy non-dict body is treated as "keep waiting", never .get()'d.
        _, sleeps, _ = self._loop([
            ["unexpected"],
            "also-bad",
            dict(APPROVED),
        ])
        self.assertEqual(sleeps[:3], [5, 5, 5])


# ---------------------------------------------------------------------------
# storage: file backend, symlinks, perms, pending state
# ---------------------------------------------------------------------------
class FileStorageTests(_EnvSandbox):
    def test_store_credential_file_backend_0600(self):
        with mock.patch.object(storage, "keychain_available", return_value=False):
            backend = storage.store_credential(
                TOKEN, base_url="https://fn2.ai", kind="device",
                extra={"scopes": ["agents"]})
        self.assertEqual(backend, "file")
        path = storage.credentials_path()
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(path.parent).st_mode & 0o777, 0o700)
        record = json.loads(path.read_text())
        self.assertEqual(record["api_key"], TOKEN)
        self.assertEqual(record["kind"], "device")
        token, source = storage.stored_token("https://fn2.ai")
        self.assertEqual((token, source), (TOKEN, "file"))

    def test_symlinked_credentials_file_refused(self):
        target = pathlib.Path(self._tmp.name) / "elsewhere.json"
        target.write_text('{"api_key": "fn2_sneaky0000000000"}')
        storage.config_home().mkdir(parents=True, exist_ok=True)
        storage.credentials_path().symlink_to(target)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(storage.load_record(), {})
        self.assertIn("symlink", err.getvalue())
        with self.assertRaises(storage.StorageError):
            storage.save_record({"kind": "device"})

    def test_lax_perms_warn_but_still_read(self):
        storage.save_record({"kind": "device", "api_key": TOKEN})
        os.chmod(storage.credentials_path(), 0o644)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            record = storage.load_record()
        self.assertEqual(record.get("api_key"), TOKEN)
        self.assertIn("group/world-accessible", err.getvalue())

    def test_world_writable_parent_dir_refused(self):
        # A group/world-writable config dir lets a local attacker pre-stage the
        # target; refuse to write a credential into it (TOCTOU hardening).
        home = storage.config_home()
        home.mkdir(parents=True, exist_ok=True)
        os.chmod(home, 0o777)  # real: make it loose, before patching chmod
        try:
            # Patch chmod to a no-op so _write_owner_json can't re-tighten it,
            # forcing the writable-parent guard to fire.
            with mock.patch.object(storage.os, "chmod",
                                   side_effect=lambda p, m: None):
                with self.assertRaises(storage.StorageError):
                    storage.save_record({"kind": "device", "api_key": TOKEN})
        finally:
            os.chmod(home, 0o700)

    def test_chmod_failure_on_parent_fails_loudly(self):
        with mock.patch.object(storage.os, "chmod",
                               side_effect=OSError("EPERM")):
            with self.assertRaises(storage.StorageError):
                storage.save_record({"kind": "device", "api_key": TOKEN})

    def test_pending_state_never_stores_a_credential(self):
        with self.assertRaises(storage.StorageError):
            storage.save_pending({"access_token": TOKEN})
        storage.save_pending({"device_code": DEVICE_CODE, "expires_at": 1.0})
        self.assertEqual(os.stat(storage.pending_path()).st_mode & 0o777, 0o600)
        self.assertEqual(storage.load_pending()["device_code"], DEVICE_CODE)
        self.assertTrue(storage.clear_pending())
        self.assertIsNone(storage.load_pending())


# ---------------------------------------------------------------------------
# storage: keychain adapter (subprocess mocked)
# ---------------------------------------------------------------------------
class KeychainAdapterTests(unittest.TestCase):
    def test_store_uses_stdin_never_argv(self):
        with mock.patch.object(storage.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=b"", stderr=b"")
            storage.keychain_store("fn2.ai", TOKEN)
        argv = run.call_args.args[0]
        self.assertEqual(argv, ["security", "-i"])
        self.assertNotIn(TOKEN, " ".join(argv))
        stdin = run.call_args.kwargs["input"].decode()
        self.assertIn("add-generic-password -U", stdin)
        self.assertIn('-s "fn2-skill"', stdin)
        self.assertIn('-a "fn2.ai"', stdin)
        self.assertIn(TOKEN, stdin)

    def test_store_refuses_unsafe_values(self):
        with self.assertRaises(storage.StorageError):
            storage.keychain_store("fn2.ai", 'evil" -x')

    def test_read_returns_stdout_secret(self):
        with mock.patch.object(storage.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=(TOKEN + "\n").encode(),
                                         stderr=b"")
            token = storage.keychain_read("fn2.ai")
        self.assertEqual(token, TOKEN)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:2], ["security", "find-generic-password"])
        self.assertIn("-w", argv)
        self.assertNotIn(TOKEN, argv)

    def test_read_miss_is_none_and_delete_reports(self):
        with mock.patch.object(storage.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=44, stdout=b"", stderr=b"not found")
            self.assertIsNone(storage.keychain_read("fn2.ai"))
            self.assertFalse(storage.keychain_delete("fn2.ai"))


# ---------------------------------------------------------------------------
# origin pinning
# ---------------------------------------------------------------------------
class OriginPinningTests(_EnvSandbox):
    def test_accept_matrix(self):
        for url in ("https://fn2.ai", "https://test.fn2.ai",
                    "https://east.fn2.ai", "https://fn2.ai:443"):
            self.assertTrue(config.origin_pinned(url), url)

    def test_reject_matrix(self):
        for url in ("https://evil.com", "http://fn2.ai", "https://fn2.ai.evil.com",
                    "https://notfn2.ai", "ftp://fn2.ai", "https://", "fn2.ai"):
            self.assertFalse(config.origin_pinned(url), url)

    def test_enforce_refuses_unpinned(self):
        with self.assertRaises(SystemExit):
            config.enforce_base_url("https://evil.com")

    def test_dev_override_warns_but_allows(self):
        os.environ["FN2_ALLOW_DEV_BASE"] = "1"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            config.enforce_base_url("http://localhost:8000")
        self.assertIn("UNPINNED", err.getvalue())

    def test_cli_refuses_unpinned_base_before_any_request(self):
        with self.assertRaises(SystemExit):
            cli.main(["--base-url", "https://evil.com", "agents"])


# ---------------------------------------------------------------------------
# CLI: auth login / resume / restart / denied
# ---------------------------------------------------------------------------
class AuthLoginCliTests(_EnvSandbox):
    def test_login_approved_stores_and_never_prints_token(self):
        with mock.patch.object(deviceauth, "start", return_value=dict(START_RESPONSE)) as start, \
             mock.patch.object(deviceauth, "poll_until_complete",
                               return_value=dict(APPROVED)):
            rc, out, err = _run_cli(["auth", "login", "--no-browser"])
        self.assertEqual(rc, 0)
        self.assertEqual(start.call_count, 1)
        blob = out + err
        self.assertNotIn(TOKEN, blob)
        self.assertIn("fn2d_…wxyz", blob)
        self.assertIn("https://fn2.ai/start", blob)
        self.assertIn("BCDF-GHJK", blob)
        self.assertIn("a***@e***.com", blob)
        record = json.loads(storage.credentials_path().read_text())
        self.assertEqual(record["api_key"], TOKEN)  # file backend on linux
        self.assertEqual(record["scopes"], ["agents", "models"])
        self.assertIsNone(storage.load_pending())

    def test_login_json_masks_token(self):
        with mock.patch.object(deviceauth, "start", return_value=dict(START_RESPONSE)), \
             mock.patch.object(deviceauth, "poll_until_complete",
                               return_value=dict(APPROVED)):
            rc, out, err = _run_cli(["auth", "login", "--no-browser", "--json"])
        self.assertEqual(rc, 0)
        self.assertNotIn(TOKEN, out + err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "approved")
        self.assertEqual(payload["credential"], "fn2d_…wxyz")

    def test_login_resumes_unexpired_pending(self):
        storage.save_pending({
            "device_code": DEVICE_CODE, "user_code": "BCDF-GHJK",
            "verification_uri": "https://fn2.ai/start", "interval": 5,
            "expires_at": time.time() + 600, "base_url": "https://fn2.ai",
        })
        with mock.patch.object(deviceauth, "start") as start, \
             mock.patch.object(deviceauth, "poll_until_complete",
                               return_value=dict(APPROVED)):
            rc, out, err = _run_cli(["auth", "login", "--no-browser"])
        self.assertEqual(rc, 0)
        start.assert_not_called()
        self.assertIn("resuming", out + err)
        self.assertIsNone(storage.load_pending())

    def test_login_restarts_when_pending_expired(self):
        storage.save_pending({
            "device_code": DEVICE_CODE, "user_code": "OLDC-ODES",
            "verification_uri": "https://fn2.ai/start", "interval": 5,
            "expires_at": time.time() - 60, "base_url": "https://fn2.ai",
        })
        with mock.patch.object(deviceauth, "start", return_value=dict(START_RESPONSE)) as start, \
             mock.patch.object(deviceauth, "poll_until_complete",
                               return_value=dict(APPROVED)):
            rc, out, err = _run_cli(["auth", "login", "--no-browser"])
        self.assertEqual(rc, 0)
        self.assertEqual(start.call_count, 1)
        self.assertNotIn("OLDC-ODES", out + err)  # fresh code, not the stale one

    def test_resumed_flow_expiring_mid_poll_restarts_once(self):
        storage.save_pending({
            "device_code": DEVICE_CODE, "user_code": "OLDC-ODES",
            "verification_uri": "https://fn2.ai/start", "interval": 5,
            "expires_at": time.time() + 600, "base_url": "https://fn2.ai",
        })
        with mock.patch.object(deviceauth, "start", return_value=dict(START_RESPONSE)) as start, \
             mock.patch.object(deviceauth, "poll_until_complete",
                               side_effect=[{"status": "expired"}, dict(APPROVED)]):
            rc, out, err = _run_cli(["auth", "login", "--no-browser"])
        self.assertEqual(rc, 0)
        self.assertEqual(start.call_count, 1)  # one fresh start after the stale resume

    def test_login_denied_stores_nothing(self):
        with mock.patch.object(deviceauth, "start", return_value=dict(START_RESPONSE)), \
             mock.patch.object(deviceauth, "poll_until_complete",
                               return_value={"status": "denied"}):
            rc, out, err = _run_cli(["auth", "login", "--no-browser"])
        self.assertEqual(rc, 1)
        self.assertIn("denied", out + err)
        self.assertFalse(storage.credentials_path().exists())
        self.assertIsNone(storage.load_pending())

    def test_login_expired_fresh_flow_reports_expiry(self):
        with mock.patch.object(deviceauth, "start", return_value=dict(START_RESPONSE)) as start, \
             mock.patch.object(deviceauth, "poll_until_complete",
                               return_value={"status": "expired"}):
            rc, out, err = _run_cli(["auth", "login", "--no-browser"])
        self.assertEqual(rc, 1)
        self.assertEqual(start.call_count, 1)  # fresh flow does not auto-restart
        self.assertIn("expired", out + err)


# ---------------------------------------------------------------------------
# CLI: a new sign-in revokes the stored device credential it replaces
# ---------------------------------------------------------------------------
OLD_TOKEN = "fn2d_" + "D" * 36 + "old1"


class SupersededDeviceTests(_EnvSandbox):
    """Signing in again (to add the research scope, or after a year) must not
    leave the replaced credential active on FN2 AI, and must never be failed or
    held up by the clean-up."""

    def _seed(self, token=OLD_TOKEN, kind="device", base_url="https://fn2.ai"):
        storage.store_credential(token, base_url=base_url, kind=kind,
                                 extra={"scopes": ["agents", "models"]})

    def _login(self, *argv, logout=None, approved=None):
        """Run `auth login`; -> (rc, output, the clients logout was called with)."""
        revoked = []

        def fake_logout(client):
            # The new credential is already stored when the old one is revoked.
            revoked.append((client.base_url, client.api_key, client.timeout,
                            storage.stored_token("https://fn2.ai")[0]))
            if logout is not None:
                raise logout
            return {"revoked": True}

        with mock.patch.object(deviceauth, "start", return_value=dict(START_RESPONSE)), \
             mock.patch.object(deviceauth, "poll_until_complete",
                               return_value=dict(approved or APPROVED)), \
             mock.patch.object(deviceauth, "logout", side_effect=fake_logout):
            rc, out, err = _run_cli(["auth", "login", "--no-browser", *argv])
        self.assertNotIn(OLD_TOKEN, out + err)
        self.assertNotIn(TOKEN, out + err)
        self.stdout = out  # --json prints the document here, prose on stderr
        return rc, out + err, revoked

    def test_relogin_revokes_the_stored_device_token_it_replaces(self):
        self._seed()
        rc, blob, revoked = self._login()
        self.assertEqual(rc, 0)
        # Exactly one revoke, of the OLD token, at the same endpoint, after
        # the new credential was stored, on a short timeout.
        self.assertEqual(revoked, [("https://fn2.ai", OLD_TOKEN,
                                    cli._REVOKE_TIMEOUT_SECONDS, TOKEN)])
        self.assertLess(cli._REVOKE_TIMEOUT_SECONDS, 45)
        self.assertEqual(blob.count("previous sign-in"), 1)
        self.assertIn("its credential fn2d_…old1 was revoked on FN2 AI", blob)
        self.assertLess(blob.index("signed in as"), blob.index("previous sign-in"))
        self.assertEqual(storage.stored_token("https://fn2.ai")[0], TOKEN)

    def test_json_reports_the_revoke_without_leaking_either_token(self):
        self._seed()
        rc, blob, revoked = self._login("--json")
        self.assertEqual(rc, 0)
        payload = json.loads(self.stdout)
        self.assertEqual(payload["superseded_device"], "revoked")
        self.assertEqual(payload["credential"], "fn2d_…wxyz")
        self.assertEqual(len(revoked), 1)

    def test_first_sign_in_has_nothing_to_revoke(self):
        rc, blob, revoked = self._login()
        self.assertEqual(rc, 0)
        self.assertEqual(revoked, [])
        self.assertNotIn("previous sign-in", blob)
        rc, blob, revoked = self._login("--json")  # now replaces TOKEN with TOKEN
        self.assertEqual(revoked, [])              # the same token is not revoked
        self.assertIsNone(json.loads(self.stdout)["superseded_device"])

    def test_an_environment_credential_is_never_revoked(self):
        os.environ["FN2_API_TOKEN"] = OLD_TOKEN
        rc, blob, revoked = self._login()
        self.assertEqual(rc, 0)
        self.assertEqual(revoked, [])
        # With one in the environment AND one stored, only the stored one goes.
        stored_old = "fn2d_" + "E" * 36 + "sto2"
        storage.clear_credential("https://fn2.ai")
        self._seed(token=stored_old)
        rc, blob, revoked = self._login()
        self.assertEqual([r[1] for r in revoked], [stored_old])
        self.assertNotIn(stored_old, blob)

    def test_a_stored_api_key_is_not_sent_to_the_device_route(self):
        self._seed(token=APIKEY, kind="api_key")
        rc, blob, revoked = self._login()
        self.assertEqual(rc, 0)
        self.assertEqual(revoked, [])
        self.assertNotIn("previous sign-in", blob)
        self.assertNotIn(APIKEY, blob)

    def test_a_token_stored_for_another_endpoint_is_left_alone(self):
        # The file holds a test.fn2.ai credential; this sign-in is to fn2.ai.
        # Sending that token here would hand one deployment's credential to
        # another.
        self._seed(base_url="https://test.fn2.ai")
        os.environ["FN2_BASE_URL"] = "https://fn2.ai"
        rc, blob, revoked = self._login()
        self.assertEqual(rc, 0)
        self.assertEqual(revoked, [])

    def test_keychain_stored_token_is_revoked_too(self):
        vault = {"fn2.ai": OLD_TOKEN}
        with mock.patch.object(storage, "keychain_available", return_value=True), \
             mock.patch.object(storage, "keychain_read", side_effect=vault.get), \
             mock.patch.object(storage, "keychain_store",
                               side_effect=vault.__setitem__):
            storage.save_record({"kind": "device", "base_url": "https://fn2.ai",
                                 "storage": "keychain"})
            rc, blob, revoked = self._login()
        self.assertEqual(rc, 0)
        self.assertEqual([r[1] for r in revoked], [OLD_TOKEN])
        self.assertEqual(vault["fn2.ai"], TOKEN)

    def test_a_failing_revoke_never_fails_the_sign_in(self):
        failures = (
            (ApiError("could not reach https://fn2.ai", code="network"), True),
            (ApiError("upstream", status=503), True),
            (TimeoutError("timed out"), True),          # not an ApiError at all
            (AuthError("revoked", status=401), False),  # already dead: silent
        )
        for failure, noted in failures:
            with self.subTest(failure=repr(failure)):
                storage.clear_credential("https://fn2.ai")
                self._seed()
                rc, blob, revoked = self._login(logout=failure)
                self.assertEqual(rc, 0)
                self.assertEqual(len(revoked), 1)
                self.assertIn("signed in as", blob)
                self.assertEqual(storage.stored_token("https://fn2.ai")[0], TOKEN)
                self.assertNotIn("was revoked on FN2 AI", blob)
                self.assertEqual("could not revoke the previous sign-in" in blob,
                                 noted)
                if noted:
                    self.assertIn("Connected Devices", blob)
        storage.clear_credential("https://fn2.ai")
        self._seed()
        rc, blob, _ = self._login("--json", logout=ApiError("x", code="network"))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(self.stdout)["superseded_device"],
                         "revoke_failed")

    def test_a_denied_or_expired_sign_in_revokes_nothing(self):
        self._seed()
        for status in ("denied", "expired"):
            rc, blob, revoked = self._login(approved={"status": status})
            self.assertEqual(rc, 1)
            self.assertEqual(revoked, [])
            self.assertEqual(storage.stored_token("https://fn2.ai")[0], OLD_TOKEN)

    def test_the_revoke_request_is_the_device_logout_with_the_old_bearer(self):
        """End to end through the HTTP seam: one POST, old token as bearer."""
        self._seed()
        sent = []

        class _Ok(io.BytesIO):
            def getcode(self):
                return 200

        def transport(client, request):
            sent.append((request.method, request.full_url,
                         request.get_header("Authorization"), client.timeout))
            return _Ok(b'{"revoked": true}')

        with mock.patch.object(deviceauth, "start", return_value=dict(START_RESPONSE)), \
             mock.patch.object(deviceauth, "poll_until_complete",
                               return_value=dict(APPROVED)), \
             mock.patch.object(Client, "_urlopen", new=transport):
            rc, out, err = _run_cli(["auth", "login", "--no-browser"])
        self.assertEqual(rc, 0)
        self.assertEqual(sent, [("POST",
                                 "https://fn2.ai/api/v1/skill/device-auth/logout",
                                 "Bearer " + OLD_TOKEN,
                                 cli._REVOKE_TIMEOUT_SECONDS)])
        self.assertNotIn(OLD_TOKEN, out + err)


# ---------------------------------------------------------------------------
# CLI: auth login --no-wait (two-phase flow for assistants)
# ---------------------------------------------------------------------------
class AuthLoginNoWaitTests(_EnvSandbox):
    def test_no_wait_prints_code_and_exits_without_polling(self):
        with mock.patch.object(deviceauth, "start", return_value=dict(START_RESPONSE)), \
             mock.patch.object(deviceauth, "poll_until_complete") as poll:
            rc, out, err = _run_cli(["auth", "login", "--no-wait", "--no-browser"])
        self.assertEqual(rc, 0)
        poll.assert_not_called()
        blob = out + err
        self.assertIn("https://fn2.ai/start", blob)
        self.assertIn("BCDF-GHJK", blob)
        self.assertIn("--no-wait", blob)  # says how to finish
        pending = storage.load_pending()
        self.assertEqual(pending["device_code"], DEVICE_CODE)

    def test_no_wait_then_plain_login_resumes_and_finishes(self):
        with mock.patch.object(deviceauth, "start", return_value=dict(START_RESPONSE)) as start, \
             mock.patch.object(deviceauth, "poll_until_complete",
                               return_value=dict(APPROVED)):
            rc1, _, _ = _run_cli(["auth", "login", "--no-wait", "--no-browser"])
            rc2, out, err = _run_cli(["auth", "login", "--no-browser"])
        self.assertEqual((rc1, rc2), (0, 0))
        self.assertEqual(start.call_count, 1)  # the resume reuses the same code
        self.assertIn("resuming", out + err)
        record = json.loads(storage.credentials_path().read_text())
        self.assertEqual(record["api_key"], TOKEN)
        self.assertIsNone(storage.load_pending())

    def test_no_wait_resumes_an_existing_pending_code(self):
        storage.save_pending({
            "device_code": DEVICE_CODE, "user_code": "BCDF-GHJK",
            "verification_uri": "https://fn2.ai/start", "interval": 5,
            "expires_at": time.time() + 600, "base_url": "https://fn2.ai",
        })
        with mock.patch.object(deviceauth, "start") as start:
            rc, out, err = _run_cli(["auth", "login", "--no-wait", "--no-browser"])
        self.assertEqual(rc, 0)
        start.assert_not_called()
        self.assertIn("BCDF-GHJK", out + err)

    def test_no_wait_json_has_no_device_code_or_token(self):
        with mock.patch.object(deviceauth, "start", return_value=dict(START_RESPONSE)):
            rc, out, err = _run_cli(["auth", "login", "--no-wait", "--no-browser",
                                     "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(payload["user_code"], "BCDF-GHJK")
        self.assertEqual(payload["verification_uri"], "https://fn2.ai/start")
        self.assertNotIn(DEVICE_CODE, out)  # the poll secret stays on disk only


# ---------------------------------------------------------------------------
# CLI: browser auto-open (display-gated, never TTY-gated)
# ---------------------------------------------------------------------------
class BrowserOpenTests(_EnvSandbox):
    def _login(self, argv):
        with mock.patch.object(deviceauth, "start", return_value=dict(START_RESPONSE)), \
             mock.patch.object(deviceauth, "poll_until_complete",
                               return_value=dict(APPROVED)), \
             mock.patch.object(cli, "_open_browser", return_value=True) as opened:
            rc, out, err = _run_cli(argv)
        return rc, out + err, opened

    def test_opens_browser_through_a_pipe_when_display_present(self):
        # _run_cli captures stdout into a StringIO (isatty False): the browser
        # must open anyway, because an assistant-driven pipe is the normal case.
        with mock.patch.object(cli, "_display_available", return_value=True):
            rc, blob, opened = self._login(["auth", "login"])
        self.assertEqual(rc, 0)
        opened.assert_called_once_with("https://fn2.ai/start")
        self.assertIn("opened in your browser", blob)

    def test_headless_prints_url_and_never_calls_browser(self):
        with mock.patch.object(cli, "_display_available", return_value=False):
            rc, blob, opened = self._login(["auth", "login"])
        self.assertEqual(rc, 0)
        opened.assert_not_called()
        self.assertIn("https://fn2.ai/start", blob)

    def test_no_browser_flag_wins_over_display(self):
        with mock.patch.object(cli, "_display_available", return_value=True):
            rc, blob, opened = self._login(["auth", "login", "--no-browser"])
        self.assertEqual(rc, 0)
        opened.assert_not_called()

    def test_display_detection_matrix(self):
        avail = cli._display_available
        self.assertTrue(avail({}, "darwin"))
        self.assertTrue(avail({}, "win32"))
        self.assertFalse(avail({}, "linux"))
        self.assertTrue(avail({"DISPLAY": ":0"}, "linux"))
        self.assertTrue(avail({"WAYLAND_DISPLAY": "wayland-0"}, "linux"))
        # over SSH only a forwarded display counts, on every platform
        self.assertFalse(avail({"SSH_CONNECTION": "1.2.3.4"}, "darwin"))
        self.assertFalse(avail({"SSH_TTY": "/dev/ttys001"}, "linux"))
        self.assertTrue(avail({"SSH_CONNECTION": "1.2.3.4", "DISPLAY": ":10"},
                              "linux"))


# ---------------------------------------------------------------------------
# CLI: status / logout / permissions / doctor / redaction
# ---------------------------------------------------------------------------
class AuthLifecycleCliTests(_EnvSandbox):
    def _seed_credential(self):
        with mock.patch.object(storage, "keychain_available", return_value=False):
            storage.store_credential(
                TOKEN, base_url="https://fn2.ai", kind="device",
                extra={"scopes": ["agents", "models"],
                       "expires_at": "2026-10-19T00:00:00Z"})

    def test_status_revoked_hints_and_redacts(self):
        self._seed_credential()
        boom = AuthError("token " + TOKEN + " revoked", status=401)
        with mock.patch.object(cli.api, "usage", side_effect=boom):
            rc, out, err = _run_cli(["auth", "status"])
        self.assertEqual(rc, 1)
        blob = out + err
        self.assertNotIn(TOKEN, blob)
        self.assertIn("fn2 auth login", blob)
        with mock.patch.object(cli.api, "usage", side_effect=boom):
            rc, out, err = _run_cli(["auth", "status", "--json"])
        self.assertEqual(rc, 1)
        self.assertNotIn(TOKEN, out + err)
        payload = json.loads(out)
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["credential"], "fn2d_…wxyz")

    def test_status_verified_stamps_last_verified(self):
        self._seed_credential()
        with mock.patch.object(cli.api, "usage", return_value={"plan": "free"}):
            rc, out, err = _run_cli(["auth", "status"])
        self.assertEqual(rc, 0)
        self.assertIn("verified   just now", out)
        record = json.loads(storage.credentials_path().read_text())
        self.assertIn("last_verified_at", record)

    def test_logout_revoke_tolerates_401(self):
        self._seed_credential()
        with mock.patch.object(deviceauth, "logout",
                               side_effect=AuthError("revoked", status=401)):
            rc, out, err = _run_cli(["auth", "logout", "--revoke"])
        self.assertEqual(rc, 0)
        self.assertIn("already revoked", out)
        self.assertFalse(storage.credentials_path().exists())

    def test_logout_revoke_success_path(self):
        self._seed_credential()
        with mock.patch.object(deviceauth, "logout",
                               return_value={"revoked": True}) as logout:
            rc, out, err = _run_cli(["auth", "logout", "--revoke"])
        self.assertEqual(rc, 0)
        self.assertEqual(logout.call_count, 1)
        self.assertIn("revoked on FN2 AI", out)
        self.assertFalse(storage.credentials_path().exists())

    def test_logout_revoke_tolerates_transient_error_and_still_clears(self):
        # A non-401 failure (500/timeout/network) must not block local sign-out.
        self._seed_credential()
        with mock.patch.object(deviceauth, "logout",
                               side_effect=ApiError("fn2 unreachable", code="network")):
            rc, out, err = _run_cli(["auth", "logout", "--revoke"])
        self.assertEqual(rc, 0)
        self.assertIn("could not confirm remote revoke", out)
        self.assertNotIn(TOKEN, out + err)
        self.assertFalse(storage.credentials_path().exists())

    def test_logout_revoke_with_api_key_skips_device_endpoint(self):
        # An fn2_ API key must be revoked in the web app, not via the device-only
        # /logout route; the CLI must not call it and must not claim it revoked.
        with mock.patch.object(storage, "keychain_available", return_value=False):
            storage.store_credential(
                APIKEY, base_url="https://fn2.ai", kind="api_key",
                extra={"scopes": ["agents"]})
        with mock.patch.object(deviceauth, "logout") as logout:
            rc, out, err = _run_cli(["auth", "logout", "--revoke"])
        self.assertEqual(rc, 0)
        self.assertEqual(logout.call_count, 0)
        self.assertIn("API key", out)
        self.assertIn("web app", out)
        self.assertFalse(storage.credentials_path().exists())

    def test_permissions_lists_scopes_and_limits(self):
        self._seed_credential()
        rc, out, err = _run_cli(["permissions"])
        self.assertEqual(rc, 0)
        self.assertIn("agents", out)
        self.assertIn("models", out)
        self.assertIn("can NOT", out)
        self.assertIn("Connected", out)
        rc, out, err = _run_cli(["permissions", "--json"])
        self.assertEqual(rc, 0)
        self.assertNotIn(TOKEN, out)
        payload = json.loads(out)
        self.assertEqual([s["scope"] for s in payload["scopes"]], ["agents", "models"])

    def test_doctor_json_never_leaks_token(self):
        self._seed_credential()

        class _Fake(io.BytesIO):
            def getcode(self):
                return 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with mock.patch.object(Client, "_urlopen",
                               return_value=_Fake(b'{"ok": true}')):
            rc, out, err = _run_cli(["doctor", "--json"])
        self.assertEqual(rc, 0)
        self.assertNotIn(TOKEN, out + err)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        names = [c["check"] for c in payload["checks"]]
        for expected in ("python", "storage backend", "credential",
                         "base URL", "reachability"):
            self.assertIn(expected, names)

    def test_redact_masks_all_secret_shapes(self):
        text = f"oops {TOKEN} and {DEVICE_CODE} and fn2_plainkey0000000000"
        redacted = config.redact(text)
        self.assertNotIn(TOKEN, redacted)
        self.assertNotIn(DEVICE_CODE, redacted)
        self.assertNotIn("fn2_plainkey0000000000", redacted)
        self.assertIn("fn2d_…wxyz", redacted)


if __name__ == "__main__":
    unittest.main()
