from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict

import discord

import claude_runner
from config import (
    ALLOWED_USER_IDS,
    DISCORD_TOKEN,
    INPUT_CHANNEL_IDS,
    MAX_DISCORD_MESSAGE,
    SESSIONS_DB,
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


@client.event
async def on_ready() -> None:
    user = client.user
    log.info("logged in as %s (id=%s)", user, user.id if user else "?")
    log.info("allowed user ids: %s", ALLOWED_USER_IDS)


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
    await _handle(message)


def main() -> None:
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set (check .env / EnvironmentFile)")
    if not ALLOWED_USER_IDS:
        raise SystemExit("ALLOWED_USER_IDS is empty - refusing to run with no authorization")
    client.run(DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
