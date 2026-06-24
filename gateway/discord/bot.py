from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import defaultdict
from typing import Optional

import discord

import claude_runner
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


async def _run_with_resume(prompt: str, scope_key: str | None) -> claude_runner.RunResult:
    sid = store.get(scope_key) if scope_key else None
    result = await claude_runner.run(prompt, sid)
    if result.invalid_resume and scope_key:
        log.warning("resume invalid for %s, retrying fresh", scope_key)
        store.delete(scope_key)
        result = await claude_runner.run(prompt, None)
    if result.ok and result.session_id and scope_key:
        store.set(scope_key, result.session_id)
    return result


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
                result = await _run_with_resume(prompt, scope_key)
        except Exception:
            log.exception("unhandled error")
            await message.channel.send("⚠️ 内部エラー (journalctl 参照)")
            return

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
