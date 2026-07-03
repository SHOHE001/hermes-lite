#!/usr/bin/env python3
"""SwitchBot API v1.1 クライアント + CLI（Issue #12）。

標準ライブラリのみで実装している。systemd --user の oneshot ジョブから
直接叩ける CLI として使うのが主目的（Discord bot の claude -p からも Bash 経由で叩ける）。

## 認証
`SWITCHBOT_TOKEN` / `SWITCHBOT_SECRET` を環境変数で渡す（`.env` 経由）。
どちらか欠けていれば即エラー終了する（fail-fast）。値はログにも通知にも出さない。

## サブコマンド
    switchbot.py devices                 登録機器 + IR リモコン一覧（id / name / type）
    switchbot.py status  <deviceId>      機器のステータス（温湿度計の temperature/humidity など）
    switchbot.py command <deviceId> <command> [parameter] [commandType]
                                         機器へコマンド送信（例: LED を turnOn）
    switchbot.py scenes                  登録済みシーン一覧（id / name）
    switchbot.py scene   <sceneId>       シーン実行

いずれも成功時 exit 0、失敗時 exit 1 + stderr にエラー理由。--json を付けると
生 JSON を stdout に出す（機械処理向け）。

参考: https://github.com/OpenWonderLabs/SwitchBotAPI （v1.1 認証仕様）
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

API_BASE = os.environ.get("SWITCHBOT_API_BASE", "https://api.switch-bot.com/v1.1")
# API 応答の statusCode == 100 が成功。それ以外はエラー扱い。
_STATUS_OK = 100
_HTTP_TIMEOUT_SEC = 15


class SwitchBotError(RuntimeError):
    """SwitchBot API 呼び出しに関わるすべての失敗（認証欠落・HTTP・API エラー）."""


def _credentials() -> tuple[str, str]:
    """token / secret を環境変数から取り出す。欠けていれば SwitchBotError。"""
    token = os.environ.get("SWITCHBOT_TOKEN", "").strip()
    secret = os.environ.get("SWITCHBOT_SECRET", "").strip()
    missing = [
        name
        for name, val in (("SWITCHBOT_TOKEN", token), ("SWITCHBOT_SECRET", secret))
        if not val
    ]
    if missing:
        raise SwitchBotError(
            f"認証情報が未設定です: {', '.join(missing)}（.env に設定してください）"
        )
    return token, secret


def _auth_headers(token: str, secret: str, now_ms: int | None = None) -> dict[str, str]:
    """v1.1 の署名ヘッダを組む。

    sign = base64( HMAC-SHA256(secret, token + t + nonce) )
    now_ms は主にテスト用の注入口。省略時は現在時刻（ミリ秒）。
    """
    t = str(now_ms if now_ms is not None else int(time.time() * 1000))
    nonce = str(uuid.uuid4())
    string_to_sign = f"{token}{t}{nonce}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
    sign = base64.b64encode(digest).decode("utf-8")
    return {
        "Authorization": token,
        "sign": sign,
        "t": t,
        "nonce": nonce,
        "Content-Type": "application/json; charset=utf8",
    }


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """SwitchBot API を叩き、payload（dict）を返す。失敗は SwitchBotError。"""
    token, secret = _credentials()
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urlrequest.Request(url, data=data, method=method)
    for key, val in _auth_headers(token, secret).items():
        req.add_header(key, val)
    try:
        with urlrequest.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8")
    except HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:  # noqa: BLE001 — 詳細取得失敗は握りつぶす
            pass
        raise SwitchBotError(f"HTTP {e.code} {e.reason} {detail}".strip()) from e
    except URLError as e:
        raise SwitchBotError(f"接続失敗: {e.reason}") from e

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SwitchBotError(f"応答が JSON でない: {raw[:200]}") from e

    status = payload.get("statusCode")
    if status != _STATUS_OK:
        msg = payload.get("message", "(no message)")
        raise SwitchBotError(f"API エラー statusCode={status}: {msg}")
    return payload


# --- 高レベル API ----------------------------------------------------------


def list_devices() -> dict[str, Any]:
    """GET /devices — body に deviceList / infraredRemoteList を含む."""
    return _request("GET", "/devices").get("body", {})


def get_status(device_id: str) -> dict[str, Any]:
    """GET /devices/{id}/status — 温湿度計なら temperature/humidity を含む."""
    return _request("GET", f"/devices/{device_id}/status").get("body", {})


def send_command(
    device_id: str,
    command: str,
    parameter: str = "default",
    command_type: str = "command",
) -> dict[str, Any]:
    """POST /devices/{id}/commands — 機器へコマンド送信."""
    body = {"command": command, "parameter": parameter, "commandType": command_type}
    return _request("POST", f"/devices/{device_id}/commands", body).get("body", {})


def list_scenes() -> list[dict[str, Any]]:
    """GET /scenes — 登録済みシーン一覧."""
    body = _request("GET", "/scenes").get("body", [])
    return body if isinstance(body, list) else []


def run_scene(scene_id: str) -> dict[str, Any]:
    """POST /scenes/{id}/execute — シーン実行."""
    return _request("POST", f"/scenes/{scene_id}/execute").get("body", {})


# --- CLI -------------------------------------------------------------------


def _print_devices(body: dict[str, Any]) -> None:
    device_list = body.get("deviceList", []) or []
    ir_list = body.get("infraredRemoteList", []) or []
    print("# 物理デバイス (deviceList)")
    if not device_list:
        print("  (なし)")
    for d in device_list:
        print(f"  {d.get('deviceId', '?'):<16} {d.get('deviceType', '?'):<18} {d.get('deviceName', '')}")
    print("# IR リモコン (infraredRemoteList)")
    if not ir_list:
        print("  (なし)")
    for d in ir_list:
        print(f"  {d.get('deviceId', '?'):<16} {d.get('remoteType', '?'):<18} {d.get('deviceName', '')}")


def _print_scenes(scenes: list[dict[str, Any]]) -> None:
    if not scenes:
        print("(登録シーンなし)")
        return
    for s in scenes:
        print(f"  {s.get('sceneId', '?'):<20} {s.get('sceneName', '')}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="switchbot.py",
        description="SwitchBot API v1.1 CLI（Issue #12）",
    )
    p.add_argument("--json", action="store_true", help="生 JSON を stdout に出す")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("devices", help="機器 + IR リモコン一覧")

    sp = sub.add_parser("status", help="機器ステータス")
    sp.add_argument("device_id")

    sp = sub.add_parser("command", help="機器へコマンド送信")
    sp.add_argument("device_id")
    sp.add_argument("command")
    sp.add_argument("parameter", nargs="?", default="default")
    sp.add_argument("command_type", nargs="?", default="command")

    sub.add_parser("scenes", help="シーン一覧")

    sp = sub.add_parser("scene", help="シーン実行")
    sp.add_argument("scene_id")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "devices":
            body = list_devices()
            if args.json:
                print(json.dumps(body, ensure_ascii=False, indent=2))
            else:
                _print_devices(body)
        elif args.cmd == "status":
            body = get_status(args.device_id)
            print(json.dumps(body, ensure_ascii=False, indent=2) if args.json else body)
        elif args.cmd == "command":
            body = send_command(args.device_id, args.command, args.parameter, args.command_type)
            print(json.dumps(body, ensure_ascii=False) if args.json else f"OK: {args.command} → {args.device_id}")
        elif args.cmd == "scenes":
            scenes = list_scenes()
            if args.json:
                print(json.dumps(scenes, ensure_ascii=False, indent=2))
            else:
                _print_scenes(scenes)
        elif args.cmd == "scene":
            run_scene(args.scene_id)
            print(f"OK: scene {args.scene_id} executed")
        else:  # argparse が required=True なのでここには来ない
            return 2
    except SwitchBotError as e:
        print(f"⚠️ SwitchBot API 失敗: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
