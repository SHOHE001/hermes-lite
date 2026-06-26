# debug-spec for #8 — Codex final review round 1 反映

> **注**: 以下「Round 1 修正」セクションの後に「Round 2 追加修正」セクションがあり、
> 修正 2（旧 sid retry）の最終仕様は **Round 2 の修正 4 で更新**されている。
> 実装は Round 2 反映後が真の最終姿。Round 1 修正 2 の after コードは history として残置。

Codex 最終レビュー round 1 の指摘 4 件のうち、コード変更を要する 3 件を implementer に再委譲する内容。

## 修正 1: bot.py で `hermes_home=HERMES_HOME` を明示渡し

**理由**: Codex architect H1 採用。systemd で起動 cwd が変わると `compaction.py` の fallback `Path(__file__).resolve().parents[2]` が意図と合わないケースを排除するため、bot.py から `config.HERMES_HOME` を必ず渡す。

**変更**: `gateway/discord/bot.py` の `_run_with_resume` 内。

before:
```python
compact = await asyncio.to_thread(
    compaction.run_compaction, sid, session_updated_at=updated_at,
)
```

after:
```python
compact = await asyncio.to_thread(
    compaction.run_compaction,
    sid,
    session_updated_at=updated_at,
    hermes_home=HERMES_HOME,
)
```

`HERMES_HOME` は既に `from config import ... HERMES_HOME` で import 済み。

## 修正 2: 要約成功 + 本実行失敗時に旧 sid で再試行

**理由**: Codex contrarian H1 採用。通知文「⚠️ 要約は作成しましたが新セッション起動に失敗しました（旧継続）」と実際の挙動を整合させる。現状は `result.text` がエラー文字列のまま返るので、ユーザーは「旧継続」と言われたのに失敗応答を見ることになる。

**変更**: `gateway/discord/bot.py` の `_run_with_resume` 内、要約成功後 `claude_runner.run` が失敗したブランチで、**旧 sid に対して 1 回だけリトライ** する。リトライ時は raw prompt（prefix なし）を渡す。

before（plan のフロー）:
```python
result = await claude_runner.run(effective_prompt, compact.resume_session_id)

if result.invalid_resume and scope_key:
    ...

if result.ok and result.session_id and scope_key:
    store.set(scope_key, result.session_id)

# 通知文 candidate を bot 側で組み立てる
notice_text = _build_compaction_notice(compact, result)

# 追跡性ログ
if compact.status == "summary_ok":
    if result.ok and result.session_id:
        log.info(...)
    else:
        log.warning(...)
        compaction.mark_failed(compact.meta.old_sid)

return result, notice_text
```

after:
```python
result = await claude_runner.run(effective_prompt, compact.resume_session_id)

if result.invalid_resume and scope_key:
    store.delete(scope_key)
    result = await claude_runner.run(effective_prompt, None)

# 要約成功 + 本実行失敗 → 旧 sid で 1 回だけリトライ（contrarian H1 採用）
if compact.status == "summary_ok" and not (result.ok and result.session_id):
    log.warning(
        "compaction summary succeeded but follow-up run failed: scope=%s old_sid=%s "
        "exit=%s — retrying on old session",
        scope_key, compact.meta.old_sid, result.exit_code,
    )
    compaction.mark_failed(compact.meta.old_sid)
    if compact.meta.old_sid:
        retry_result = await claude_runner.run(prompt, compact.meta.old_sid)
        # 旧 sid でも失敗した場合は retry_result を返す（store は更新しない）
        if retry_result.ok and retry_result.session_id and scope_key:
            store.set(scope_key, retry_result.session_id)
        result = retry_result
elif result.ok and result.session_id and scope_key:
    store.set(scope_key, result.session_id)

notice_text = _build_compaction_notice(compact, result)
# 注: notice_text は再試行前の result でも再試行後の result でも、
#     "summary_ok かつ result.ok=False" の状態を見て「⚠️ 旧継続」を選ぶ
#     _build_compaction_notice の判定が retry 後の result を見るため矛盾なし。

# 追跡性ログ（再試行成功時は INFO、旧 sid 起動も失敗時は WARNING のみ）
if compact.status == "summary_ok" and result.ok and result.session_id:
    log.info(
        "compaction success scope=%s old_sid=%s new_sid=%s ...",
        scope_key, compact.meta.old_sid, result.session_id, ...
    )

return result, notice_text
```

**ポイント**:
- 旧 sid で再試行することで「ユーザー応答」は失敗のまま終わらず、最低限「旧セッションでの通常応答」が返る。
- store は旧 sid のままなので、次回も `old_sid` でアクセス可能。
- mark_failed は cooldown 入りなので、即座に再要約は起きない。
- 通知文 "⚠️ 要約は作成しましたが新セッション起動に失敗しました（旧継続）" の意味と運用挙動が整合する。

## 修正 3: compaction.run_compaction の最外周 try/except

**理由**: Codex migration M3 採用。`run_compaction` 内で想定外例外（permission error、Path 例外等）が発生すると bot.py の汎用 except に落ちて Discord 応答が「⚠️ 内部エラー」になり、Discord 会話自体が止まる。本来は noop で素通りすべき。

**変更**: `gateway/discord/compaction.py::run_compaction` の最外周に try/except を入れ、想定外例外時は `_noop_result(session_id, "exception")` を返す。

```python
def run_compaction(
    session_id: Optional[str],
    *,
    session_updated_at: Optional[int] = None,
    now: Optional[int] = None,
    projects_dir: Optional[Path] = None,
    hermes_home: Optional[Path] = None,
) -> CompactionResult:
    """エフェクト持ち orchestration..."""
    try:
        # 既存の実装内容をすべてここに包む
        settings = load_settings()
        ...
        return _build_result(...)
    except Exception as e:  # noqa: BLE001
        log.warning(
            "compaction.run_compaction crashed unexpectedly (sid=%s): %s — falling back to noop",
            session_id, e, exc_info=True,
        )
        return _noop_result(session_id, "exception")
```

`CompactionMeta.trigger_reason` の値域に `"exception"` を追加する（型ヒントが `Literal[...]` なら追加、`str` なら定義コメントだけ）。
`_noop_result` の中で例外が起きないようにする（最低限の構築だけ）。

## 確認

修正後、以下を smoke 確認してから報告:

1. `python -m py_compile gateway/discord/bot.py gateway/discord/compaction.py` で構文 OK。
2. 既存 smoke (T01..T14) のうち、bot.py / compaction.py 修正で影響する T-ID を再実行し、`pass` を維持していること。
3. 新規 smoke として、`run_compaction` 内で `_extract_history` を例外を raise する mock に差し替えて、`status="noop", trigger_reason="exception"` を返すことを確認。これは `test-summary.json` の `smoke_results` に `T15_exception_fallback: pass` として追加。

実装内容で `claude_runner.py` を触ったら NG。`git diff main..HEAD -- gateway/discord/claude_runner.py` が空であることを最後に確認して報告。

---

# Round 2 追加修正（Codex final review round 2 反映）

Round 1 修正の `_run_with_resume` で「旧 sid retry 成功時に成功通知（🧹）になってしまう」バグを 3 persona すべてが指摘した。本質 1 件 + 例外 fallback の細分化を反映する。

## 修正 4: 通知判定を「初回 result」で行う（最重要バグ）

**理由**: Codex round 2 architect H1 / contrarian H1 / migration H1 採用。
要約成功 + 新セッション起動失敗時に旧 sid で retry したあとも、通知は「⚠️ 要約は作成しましたが新セッション起動に失敗しました（旧継続）」固定にする。retry が成功しても「新 sid に移行できた」ことにはならない（store は旧 sid のまま、新セッション lineage は未確立）。

**変更**: `gateway/discord/bot.py::_run_with_resume`

before（round 1 の修正 2 適用済み状態）:
```python
result = await claude_runner.run(effective_prompt, compact.resume_session_id)

if result.invalid_resume and scope_key:
    store.delete(scope_key)
    result = await claude_runner.run(effective_prompt, None)

if compact.status == "summary_ok" and not (result.ok and result.session_id):
    log.warning(...)
    compaction.mark_failed(compact.meta.old_sid)
    if compact.meta.old_sid:
        retry_result = await claude_runner.run(prompt, compact.meta.old_sid)
        if retry_result.ok and retry_result.session_id and scope_key:
            store.set(scope_key, retry_result.session_id)
        result = retry_result  # ← BUG: 上書きすると notice 判定が崩れる
elif result.ok and result.session_id and scope_key:
    store.set(scope_key, result.session_id)

notice_text = _build_compaction_notice(compact, result)  # ← bug: retry 後の result を見る
```

after:
```python
result = await claude_runner.run(effective_prompt, compact.resume_session_id)

if result.invalid_resume and scope_key:
    store.delete(scope_key)
    result = await claude_runner.run(effective_prompt, None)

# 初回 result（新セッション起動の成否）を別変数で保持。
# notice/ログはこれで判定する（contrarian/architect/migration H1 採用）。
initial_result = result
new_session_ok = (
    compact.status == "summary_ok"
    and initial_result.ok
    and initial_result.session_id is not None
)

if compact.status == "summary_ok" and not new_session_ok:
    log.warning(
        "compaction summary succeeded but follow-up run failed: scope=%s old_sid=%s "
        "exit=%s — retrying on old session",
        scope_key, compact.meta.old_sid, initial_result.exit_code,
    )
    compaction.mark_failed(compact.meta.old_sid)
    if compact.meta.old_sid:
        retry_result = await claude_runner.run(prompt, compact.meta.old_sid)
        # 旧 sid で retry 成功なら、ユーザーには旧 sid の応答を返す。
        # ただし通知は「旧継続」のまま、store も旧 sid のままにする。
        if retry_result.ok and retry_result.session_id and scope_key:
            store.set(scope_key, retry_result.session_id)
            # ↑ retry_result.session_id は claude CLI 側で「旧 sid から派生した同一 lineage」のはず。
            # store.set は updated_at を最新に保つ目的（idle 判定の精度維持）。
        result = retry_result  # 応答として返す
elif initial_result.ok and initial_result.session_id and scope_key:
    store.set(scope_key, initial_result.session_id)

# 通知は initial_result で判定する。retry 後 result は応答テキストにだけ使う。
notice_text = _build_compaction_notice(compact, initial_result)

# 追跡性ログも initial_result で判定（new_sid は initial_result.session_id のみ）
if compact.status == "summary_ok":
    if new_session_ok:
        log.info(
            "compaction success scope=%s old_sid=%s new_sid=%s old_jsonl=%s "
            "older_turns=%d recent_turns=%d trigger=%s dropped=%d",
            scope_key, compact.meta.old_sid, initial_result.session_id, compact.meta.old_jsonl,
            compact.meta.older_count, compact.meta.recent_count, compact.meta.trigger_reason,
            compact.meta.dropped_count,
        )
    # warning ログは上の if ブロックで既に出している
```

**ポイント**:
- `_build_compaction_notice` は変更しない。**呼び出し時に渡す `result` を `initial_result` にする**だけ。
- `initial_result.ok and initial_result.session_id` が True のときだけ「🧹 成功」、False かつ `summary_ok` なら「⚠️ 旧継続」になり、retry の成否は通知に影響しない。
- store は initial_result 失敗時は触らず、retry 成功時のみ store.set（updated_at 維持目的）。
- 追跡性ログ `compaction success ...` も initial_result.session_id が確定したときだけ。

## 修正 5: `run_compaction` の例外 fallback を trigger 判定後は `summary_failed` 化

**理由**: Codex architect H2 採用。trigger 判定後の `_extract_history` / `_summarize` 周辺で想定外例外が起きた場合、現状は `_noop_result(..., "exception")` を返すため、通知も cooldown も出ない。これは「肥大化 jsonl で毎発話例外」を黙って繰り返す状況になる。trigger 判定後の例外は `summary_failed` 扱いにして mark_failed + Discord 通知を出す。

**変更**: `gateway/discord/compaction.py::run_compaction`

```python
def run_compaction(...) -> CompactionResult:
    try:
        settings = load_settings()
        ...
        if not trigger:
            return _noop_result(...)
        # ↓ trigger 後はここから例外が起きたら summary_failed に分岐
        trigger_passed = True
        ...
        return _build_result(...)
    except Exception as e:  # noqa: BLE001
        log.warning(
            "compaction.run_compaction crashed unexpectedly (sid=%s): %s — falling back",
            session_id, e, exc_info=True,
        )
        if locals().get("trigger_passed"):
            # trigger 後の例外: 失敗扱いで cooldown + Discord 警告通知
            try:
                mark_failed(session_id)
            except Exception:
                pass
            return _failed_result(session_id, "exception")
        else:
            # trigger 前の例外: 設定読み込み等の問題なので noop でログだけ
            return _noop_result(session_id, "exception")
```

`_failed_result` は status="summary_failed" を返す既存 / 新規ヘルパ。なければ `CompactionResult(status="summary_failed", resume_session_id=session_id, prompt_prefix=None, meta=CompactionMeta(old_sid=session_id, old_jsonl=None, trigger_reason="exception", older_count=0, recent_count=0, dropped_count=0))` 相当を返す。

これにより:
- 通知付きで失敗が見える
- cooldown が効いて毎発話の例外ループを抑止できる

## 修正 6: test-spec.md / test-summary.json の補強

**理由**: Codex round 2 architect M3 / contrarian M2 / migration H2 採用（軽量採用）。

`features/8-discord-p/test-spec.md` の T07c に「`_run_with_resume` を実モジュール経由で smoke する」サブステップを足す。具体的には:

```python
# T07c (拡張版): discord モジュールを最小スタブ化して bot.py を import する
import sys, types
# discord モジュールスタブ
fake_discord = types.ModuleType("discord")
fake_discord.HTTPException = type("HTTPException", (Exception,), {})
fake_discord.Forbidden = type("Forbidden", (fake_discord.HTTPException,), {})
fake_discord.Intents = type("Intents", (), {"default": staticmethod(lambda: types.SimpleNamespace(message_content=False, dm_messages=False, guild_messages=False))})
fake_discord.Client = type("Client", (), {"__init__": lambda self, **kw: None, "event": staticmethod(lambda f: f), "user": None, "run": lambda self, *a, **kw: None, "loop": None})
fake_discord.DMChannel = type("DMChannel", (), {})
fake_discord.Thread = type("Thread", (), {})
fake_discord.Message = type("Message", (), {})
sys.modules.setdefault("discord", fake_discord)

# 必要な env 設定（ALLOWED_USER_IDS, DISCORD_TOKEN は空でも import 自体は通る）
import os
os.environ.setdefault("DISCORD_TOKEN", "dummy")
os.environ.setdefault("ALLOWED_USER_IDS", "0")

import bot  # 実モジュール

# claude_runner.run を monkey patch して initial_result 失敗 + retry_result 成功シナリオを再現
import claude_runner
calls = []
async def fake_run(prompt, sid):
    calls.append((prompt[:30], sid))
    if len(calls) == 1:
        # 初回：要約 prefix 付き / resume_sid=None で失敗
        return claude_runner.RunResult(ok=False, text="boom", session_id=None, exit_code=1, invalid_resume=False, timed_out=False)
    # 2 回目：旧 sid で retry 成功
    return claude_runner.RunResult(ok=True, text="ok-from-old", session_id="old-sid-x", exit_code=0, invalid_resume=False, timed_out=False)

claude_runner.run = fake_run

# compaction.run_compaction を summary_ok mock
import compaction
def fake_run_compaction(sid, **kw):
    return compaction.CompactionResult(
        status="summary_ok",
        resume_session_id=None,
        prompt_prefix="ダミー prefix",
        meta=compaction.CompactionMeta(old_sid="old-sid-x", old_jsonl="/tmp/x.jsonl",
                                       trigger_reason="size", older_count=5, recent_count=10, dropped_count=0),
    )
compaction.run_compaction = fake_run_compaction

import asyncio
# bot.store も monkey patch（任意）
result, notice = asyncio.run(bot._run_with_resume("こんにちは", "dm:1"))
assert not (result is None)
assert "新セッション起動に失敗" in (notice or ""), f"notice should warn old-continue, got: {notice!r}"
assert result.text == "ok-from-old", f"retry result.text expected, got: {result.text!r}"
print("OK")
```

T15 もこの拡張版で再実行する形にして、bot.py の `_run_with_resume` 統合経路が実モジュール上で動くことを確認。

`features/8-discord-p/test-summary.json` の `smoke_notes.discord_bot_import` を「discord モジュールを最小スタブ化して bot.py 実 import smoke 実施」に更新。`skipped_realdiscord` / `skipped_realclaude` の文言は維持（実機チェックは引き続き operator follow-up）。

## 確認

修正後:
1. `python -m py_compile gateway/discord/bot.py gateway/discord/compaction.py` 構文 OK。
2. T07c 拡張版 smoke で `notice` に「新セッション起動に失敗」を含み、`result.text == "ok-from-old"` であることを確認。
3. 既存 T15_exception_fallback を「trigger 前例外 → noop / trigger 後例外 → summary_failed」両方の smoke に拡張。
   - T15a_exception_before_trigger: `settings = load_settings()` の前で例外 → `status="noop", trigger_reason="exception"`
   - T15b_exception_after_trigger: `_extract_history` で例外 → `status="summary_failed", trigger_reason="exception"`、mark_failed が呼ばれる
4. `git diff main..HEAD -- gateway/discord/claude_runner.py` 空維持。

## 報告

1. 変更ファイル + 差分行数
2. py_compile OK
3. T07c 拡張版 / T15a / T15b の結果
4. claude_runner.py 差分空
