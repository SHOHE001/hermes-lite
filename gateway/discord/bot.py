from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import defaultdict
from typing import Optional

import discord

import claude_runner
import compaction
from config import (
    ALLOWED_USER_IDS,
    DISCORD_TOKEN,
    INPUT_CHANNEL_IDS,
    MAX_DISCORD_MESSAGE,
    SESSIONS_DB,
    HERMES_HOME,
    APPROVALS_DB,
    APPROVAL_COMMANDS_ENABLED,
)
from session_store import SessionStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("hermes-lite.discord.bot")

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.guild_messages = True

client = discord.Client(intents=intents)
store = SessionStore(SESSIONS_DB)
locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

# ---------------------------------------------------------------------------
# 承認ゲート (Issue #3) — flag check の後に optional import / regex 初期化
# ---------------------------------------------------------------------------

_approval_handler = None  # type: Optional[object]
_APPROVAL_PATTERN: Optional[re.Pattern] = None
_sweep_task: Optional[asyncio.Task] = None

if APPROVAL_COMMANDS_ENABLED:
    # approval_handler 内部の get_authorized_user_ids() が fallback できるよう
    # ALLOWED_USER_IDS を環境変数に export する (plan v6 Round 6 採用)
    if ALLOWED_USER_IDS and not os.environ.get("HERMES_APPROVAL_ALLOWED_USER_IDS_FALLBACK"):
        os.environ["HERMES_APPROVAL_ALLOWED_USER_IDS_FALLBACK"] = ",".join(
            str(x) for x in ALLOWED_USER_IDS
        )
    _APPROVAL_PATTERN = re.compile(
        r"^\s*approval\s+(approve|reject)\s+#?[a-f0-9]{8}\s*$",
        re.IGNORECASE,
    )
    try:
        import approval_handler  # type: ignore
        _approval_handler = approval_handler
        log.info(
            "approval feature enabled (HERMES_HOME=%s APPROVALS_DB=%s)",
            HERMES_HOME, APPROVALS_DB,
        )
    except Exception:
        log.warning(
            "approval_handler import failed; approval feature disabled "
            "(reserved-word capture remains)",
            exc_info=True,
        )
        _approval_handler = None


def _scope_key(message: discord.Message) -> str | None:
    if isinstance(message.channel, discord.DMChannel):
        return f"dm:{message.author.id}"
    if isinstance(message.channel, discord.Thread):
        return f"thread:{message.channel.id}"
    if message.channel.id in INPUT_CHANNEL_IDS:
        # 指定チャンネル全メッセージモード。channel 単位で session を継続。
        return f"channel:{message.channel.id}"
    return None


def _should_react(message: discord.Message) -> bool:
    if message.author.bot:
        return False
    if message.author.id not in ALLOWED_USER_IDS:
        return False
    if isinstance(message.channel, discord.DMChannel):
        return True
    if isinstance(message.channel, discord.Thread):
        return True
    if message.channel.id in INPUT_CHANNEL_IDS:
        return True
    return client.user is not None and client.user in message.mentions


def _strip_mention(content: str) -> str:
    if client.user is None:
        return content
    return re.sub(rf"<@!?{client.user.id}>", "", content).strip()


def _split_for_discord(text: str, limit: int = MAX_DISCORD_MESSAGE) -> list[str]:
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    if rest:
        chunks.append(rest)
    return chunks


def _build_compaction_notice(
    compact: compaction.CompactionResult,
    result: claude_runner.RunResult,
) -> str | None:
    """status と result.ok を見て通知文を組み立てる。noop なら None."""
    old_sid8 = (compact.meta.old_sid or "????????")[:8]
    dropped_suffix = (
        f" / ⚠️ サイズ超過のため古い履歴 {compact.meta.dropped_count} 件を要約から除外"
        if compact.meta.dropped_count > 0
        else ""
    )
    if compact.status == "summary_ok":
        if result.ok and result.session_id:
            return (
                f"🧹 セッションをコンパクションしました（旧 sid: {old_sid8}）"
                f"{dropped_suffix}"
            )
        return (
            f"⚠️ 要約は作成しましたが新セッション起動に失敗しました"
            f"（旧継続: {old_sid8}）"
        )
    if compact.status == "summary_failed":
        return f"⚠️ コンパクション失敗（旧セッション継続: {old_sid8}）"
    return None  # status == "noop"


async def _run_with_resume(
    prompt: str, scope_key: str | None
) -> tuple[claude_runner.RunResult, str | None]:
    sid = store.get(scope_key) if scope_key else None
    updated_at = store.get_updated_at(scope_key) if scope_key else None

    # compaction 判定 + 要約 subprocess は同期 io なので to_thread に逃がす
    # hermes_home は config.HERMES_HOME を明示渡し（systemd で起動 cwd が変わる場合の
    # compaction.py 側 fallback `Path(__file__).resolve().parents[2]` 依存を排除する。
    # Codex architect H1 採用 / debug-spec 修正 1）。
    compact = await asyncio.to_thread(
        compaction.run_compaction,
        sid,
        session_updated_at=updated_at,
        hermes_home=HERMES_HOME,
    )

    effective_prompt = compaction.build_effective_prompt(compact.prompt_prefix, prompt)

    result = await claude_runner.run(effective_prompt, compact.resume_session_id)

    if result.invalid_resume and scope_key:
        log.warning("resume invalid for %s, retrying fresh", scope_key)
        store.delete(scope_key)
        # invalid_resume 時の再試行でも effective_prompt（prefix 含む）を渡す。
        # 要約成功時の resume=None は通常 invalid_resume を起こさないが、
        # ノーオペで old_sid invalid のパターンでも effective_prompt は prefix なし
        # （prompt と等価）なので安全。要約消失を防ぐためここでは effective_prompt を渡す。
        result = await claude_runner.run(effective_prompt, None)

    # 初回 result（新セッション起動の成否）を別変数で保持する。
    # 通知判定と追跡性ログはこの initial_result を使う。retry の成否は通知に影響させない
    # ＝「⚠️ 旧継続」は initial_result が失敗である限り出続ける（store も旧 sid のまま）。
    # Codex round 2 architect H1 / contrarian H1 / migration H1 採用 / debug-spec 修正 4。
    initial_result = result
    new_session_ok = (
        compact.status == "summary_ok"
        and initial_result.ok
        and initial_result.session_id is not None
    )

    # 要約成功 + 本実行失敗 → 旧 sid で 1 回だけリトライ
    # （Codex contrarian H1 採用 / debug-spec 修正 2）。
    # 通知文「⚠️ 要約は作成しましたが新セッション起動に失敗しました（旧継続）」と
    # 実挙動を整合させるため、旧 sid に対して raw prompt（prefix なし）で 1 回だけ再試行する。
    # 旧 sid でも失敗した場合は retry 結果をそのまま返す（store は更新しない）。
    if compact.status == "summary_ok" and not new_session_ok:
        log.warning(
            "compaction summary succeeded but follow-up run failed: scope=%s "
            "old_sid=%s exit=%s — retrying on old session",
            scope_key,
            compact.meta.old_sid,
            initial_result.exit_code,
        )
        compaction.mark_failed(compact.meta.old_sid)
        if compact.meta.old_sid:
            retry_result = await claude_runner.run(prompt, compact.meta.old_sid)
            # 旧 sid で retry 成功なら、ユーザーには旧 sid の応答を返す。
            # ただし通知は「旧継続」のまま、store も旧 sid のままにする
            # （store.set は updated_at を最新に保つ目的のみ。新 lineage への切替ではない）。
            if retry_result.ok and retry_result.session_id and scope_key:
                store.set(scope_key, retry_result.session_id)
            result = retry_result  # 応答として返すのは retry の result
    elif initial_result.ok and initial_result.session_id and scope_key:
        store.set(scope_key, initial_result.session_id)

    # 通知判定は initial_result で固定する。retry 後の result は応答テキストにだけ使う。
    # _build_compaction_notice の中身は無変更（status と result.ok の組合せで判定）。
    notice_text = _build_compaction_notice(compact, initial_result)

    # 追跡性ログも initial_result で判定する。
    # WARNING は上の retry ブランチで既出のため、ここでは成功時の INFO のみ。
    # new_sid は initial_result.session_id を採用（retry の session_id は新 lineage 確立では
    # ないため、ログには含めない）。
    if compact.status == "summary_ok" and new_session_ok:
        log.info(
            "compaction success scope=%s old_sid=%s new_sid=%s old_jsonl=%s "
            "older_turns=%d recent_turns=%d trigger=%s dropped=%d",
            scope_key,
            compact.meta.old_sid,
            initial_result.session_id,
            compact.meta.old_jsonl,
            compact.meta.older_count,
            compact.meta.recent_count,
            compact.meta.trigger_reason,
            compact.meta.dropped_count,
        )

    return result, notice_text


async def _handle(message: discord.Message) -> None:
    prompt = _strip_mention(message.content)
    if not prompt:
        return

    scope_key = _scope_key(message)
    lock_key = scope_key or f"single:{message.channel.id}:{message.id}"

    async with locks[lock_key]:
        log.info(
            "handle from=%s scope=%s prompt(%d): %s",
            message.author.id, scope_key, len(prompt),
            prompt[:200].replace("\n", " "),
        )
        try:
            async with message.channel.typing():
                result, notice_text = await _run_with_resume(prompt, scope_key)
        except Exception:
            log.exception("unhandled error")
            await message.channel.send("⚠️ 内部エラー (journalctl 参照)")
            return

        if notice_text:
            try:
                await message.channel.send(notice_text)
            except discord.HTTPException:
                log.warning(
                    "could not send compaction notice (scope=%s)",
                    scope_key,
                    exc_info=True,
                )

        for chunk in _split_for_discord(result.text):
            await message.channel.send(chunk)


async def _approval_sweep_loop() -> None:
    """1 時間に 1 度、3 種類の sweep を呼ぶ."""
    assert _approval_handler is not None
    while True:
        try:
            swept_exp = await asyncio.to_thread(_approval_handler.sweep_expired)
            swept_appr = await asyncio.to_thread(_approval_handler.sweep_stale_approved)
            swept_exec = await asyncio.to_thread(_approval_handler.sweep_stale_executing)
            if swept_exp or swept_appr or swept_exec:
                log.info(
                    "approval sweep: %d expired, %d stale-approved, %d stale-executing",
                    swept_exp, swept_appr, swept_exec,
                )
        except Exception:
            log.exception("approval sweep failed")
        await asyncio.sleep(3600)


@client.event
async def on_ready() -> None:
    global _sweep_task
    user = client.user
    log.info("logged in as %s (id=%s)", user, user.id if user else "?")
    log.info("allowed user ids: %s", ALLOWED_USER_IDS)
    if APPROVAL_COMMANDS_ENABLED and _approval_handler is not None:
        if _sweep_task is None or _sweep_task.done():
            _sweep_task = client.loop.create_task(_approval_sweep_loop())
            log.info("approval sweep loop started")


@client.event
async def on_thread_create(thread: discord.Thread) -> None:
    try:
        await thread.join()
        log.info("joined thread: %s (%s)", thread.id, thread.name)
    except discord.Forbidden:
        log.warning("cannot join thread: %s", thread.id)


@client.event
async def on_message(message: discord.Message) -> None:
    if not _should_react(message):
        if not message.author.bot and message.author.id not in ALLOWED_USER_IDS:
            log.warning(
                "unauthorized user=%s channel=%s",
                message.author.id, type(message.channel).__name__,
            )
        return

    # 承認ゲート (flag on のときだけ regex マッチを試す)
    if APPROVAL_COMMANDS_ENABLED and _APPROVAL_PATTERN is not None:
        stripped = _strip_mention(message.content)
        if _APPROVAL_PATTERN.match(stripped):
            if _approval_handler is None:
                await message.channel.send(
                    "⚠️ [WARN] approval feature disabled (import failed; see journalctl)"
                )
                return
            try:
                reply = await asyncio.to_thread(
                    _approval_handler.handle, stripped, message.author.id
                )
            except Exception:
                log.exception("approval handler crashed")
                await message.channel.send(
                    "⚠️ [WARN] approval 処理で内部エラー (journalctl 参照)"
                )
                return
            await message.channel.send(reply)
            return

    await _handle(message)


def main() -> None:
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set (check .env / EnvironmentFile)")
    if not ALLOWED_USER_IDS:
        raise SystemExit("ALLOWED_USER_IDS is empty - refusing to run with no authorization")
    client.run(DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
