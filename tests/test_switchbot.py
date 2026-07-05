"""Issue #12 SwitchBot API クライアント/CLI の自動テスト（標準 unittest）。

ネットワークは一切叩かない。`switchbot.urlrequest.urlopen` をモックし、
署名生成・応答パース・エラー処理・CLI 終了コードを検証する。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

# lib/ を import path に追加
_REPO_ROOT = Path(__file__).resolve().parents[1]
_LIB_DIR = _REPO_ROOT / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import switchbot  # noqa: E402

_ENV = {"SWITCHBOT_TOKEN": "tok-123", "SWITCHBOT_SECRET": "sec-abc"}

# テスト中は実 .env を絶対に読ませない（env を空にするテストが本物の認証情報を
# 拾って実 API を叩くのを防ぐ）。存在しないパスへ差し替える。
_dotenv_patcher = None


def setUpModule():
    global _dotenv_patcher
    _dotenv_patcher = mock.patch.object(
        switchbot, "_DOTENV_PATH", Path("/nonexistent/hermes-lite/.env")
    )
    _dotenv_patcher.start()


def tearDownModule():
    if _dotenv_patcher is not None:
        _dotenv_patcher.stop()


class _FakeResp:
    """urlopen が返す context manager の最小モック."""

    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._raw


def _ok(body):
    return {"statusCode": 100, "message": "success", "body": body}


class AuthHeadersTest(unittest.TestCase):
    def test_sign_verifies_against_nonce(self):
        headers = switchbot._auth_headers("tok-123", "sec-abc", now_ms=1_700_000_000_000)
        self.assertEqual(headers["Authorization"], "tok-123")
        self.assertEqual(headers["t"], "1700000000000")
        self.assertIn("nonce", headers)
        # sign = base64(HMAC-SHA256(secret, token + t + nonce)) を追検証
        to_sign = f"tok-123{headers['t']}{headers['nonce']}".encode()
        expected = base64.b64encode(
            hmac.new(b"sec-abc", to_sign, hashlib.sha256).digest()
        ).decode()
        self.assertEqual(headers["sign"], expected)

    def test_nonce_changes_between_calls(self):
        h1 = switchbot._auth_headers("t", "s", now_ms=1)
        h2 = switchbot._auth_headers("t", "s", now_ms=1)
        self.assertNotEqual(h1["nonce"], h2["nonce"])


class CredentialsTest(unittest.TestCase):
    def test_missing_both_raises(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(switchbot.SwitchBotError) as ctx:
                switchbot._credentials()
        self.assertIn("SWITCHBOT_TOKEN", str(ctx.exception))
        self.assertIn("SWITCHBOT_SECRET", str(ctx.exception))

    def test_missing_secret_only(self):
        with mock.patch.dict("os.environ", {"SWITCHBOT_TOKEN": "x"}, clear=True):
            with self.assertRaises(switchbot.SwitchBotError) as ctx:
                switchbot._credentials()
        self.assertIn("SWITCHBOT_SECRET", str(ctx.exception))
        self.assertNotIn("SWITCHBOT_TOKEN", str(ctx.exception))


class RequestTest(unittest.TestCase):
    def test_list_devices_parses_body(self):
        payload = _ok({"deviceList": [{"deviceId": "AA", "deviceType": "Bot", "deviceName": "光"}],
                       "infraredRemoteList": []})
        with mock.patch.dict("os.environ", _ENV, clear=True), \
             mock.patch.object(switchbot.urlrequest, "urlopen", return_value=_FakeResp(payload)):
            body = switchbot.list_devices()
        self.assertEqual(body["deviceList"][0]["deviceId"], "AA")

    def test_status_code_not_100_raises(self):
        payload = {"statusCode": 190, "message": "device internal error", "body": {}}
        with mock.patch.dict("os.environ", _ENV, clear=True), \
             mock.patch.object(switchbot.urlrequest, "urlopen", return_value=_FakeResp(payload)):
            with self.assertRaises(switchbot.SwitchBotError) as ctx:
                switchbot.get_status("AA")
        self.assertIn("190", str(ctx.exception))

    def test_send_command_builds_post_body(self):
        captured = {}

        def _fake_urlopen(req, timeout=None):
            captured["method"] = req.get_method()
            captured["url"] = req.full_url
            captured["data"] = req.data
            return _FakeResp(_ok({}))

        with mock.patch.dict("os.environ", _ENV, clear=True), \
             mock.patch.object(switchbot.urlrequest, "urlopen", side_effect=_fake_urlopen):
            switchbot.send_command("DEV1", "turnOn")

        self.assertEqual(captured["method"], "POST")
        self.assertTrue(captured["url"].endswith("/devices/DEV1/commands"))
        sent = json.loads(captured["data"].decode())
        self.assertEqual(sent, {"command": "turnOn", "parameter": "default", "commandType": "command"})

    def test_http_error_wrapped(self):
        from urllib.error import HTTPError

        def _raise(req, timeout=None):
            raise HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b"bad token"))

        with mock.patch.dict("os.environ", _ENV, clear=True), \
             mock.patch.object(switchbot.urlrequest, "urlopen", side_effect=_raise):
            with self.assertRaises(switchbot.SwitchBotError) as ctx:
                switchbot.list_devices()
        self.assertIn("401", str(ctx.exception))


class CliTest(unittest.TestCase):
    def test_main_fail_fast_without_creds(self):
        err = io.StringIO()
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch("sys.stderr", err):
            rc = switchbot.main(["devices"])
        self.assertEqual(rc, 1)
        self.assertIn("SwitchBot API 失敗", err.getvalue())

    def test_main_devices_success(self):
        payload = _ok({"deviceList": [], "infraredRemoteList": []})
        out = io.StringIO()
        with mock.patch.dict("os.environ", _ENV, clear=True), \
             mock.patch.object(switchbot.urlrequest, "urlopen", return_value=_FakeResp(payload)), \
             mock.patch("sys.stdout", out):
            rc = switchbot.main(["devices"])
        self.assertEqual(rc, 0)
        self.assertIn("物理デバイス", out.getvalue())

    def test_main_scene_success(self):
        out = io.StringIO()
        with mock.patch.dict("os.environ", _ENV, clear=True), \
             mock.patch.object(switchbot.urlrequest, "urlopen", return_value=_FakeResp(_ok({}))), \
             mock.patch("sys.stdout", out):
            rc = switchbot.main(["scene", "scene-xyz"])
        self.assertEqual(rc, 0)
        self.assertIn("executed", out.getvalue())


if __name__ == "__main__":
    unittest.main()
