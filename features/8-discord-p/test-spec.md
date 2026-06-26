# test-spec for #8 Discord -p セッション自動コンパクション

> `project_type=jobs` のため自動テストフレームは導入せず、手動チェックリストで受け入れる。
> 各 T-ID は plan.md「テスト計画」の T-ID と一対一対応。

## 前提セットアップ

```bash
cd /home/shohei/hermes-lite
# 別 worktree や別ターミナルで作業する場合のみ:
git checkout gloop/8-discord-p

# Python は gateway/discord で動かす
cd gateway/discord
```

実機系の検証は Discord runner を直接起動しないでも、`python -c '...'` で `compaction.py` の純粋関数を呼び出すスタイルで実施できる（unittest フレームは使わない）。

実機 Discord で確認するもの: T06e, T11, T13b.

### 共通 fixture（手動で作る）

```bash
TMPHOME=$(mktemp -d)
mkdir -p "$TMPHOME/projects/-home-shohei-hermes-lite"
export HERMES_PROJECTS_DIR="$TMPHOME/projects"
```

各テスト終了後: `rm -rf "$TMPHOME"`。

---

## T01_noop_no_session

**前提**: session_id=None
**コマンド**:
```bash
cd gateway/discord
python -c "
import compaction
r = compaction.run_compaction(None)
print(r.status, r.resume_session_id, r.prompt_prefix is None, r.meta.trigger_reason)
"
```
**期待値**:
- [ ] 出力: `noop None True none`

---

## T02_noop_below_threshold

**前提**: 479999 bytes の jsonl + idle < 48h (`updated_at = now()`)
**コマンド**:
```bash
SID=test-sid-01
JSONL="$HERMES_PROJECTS_DIR/-home-shohei-hermes-lite/${SID}.jsonl"
head -c 479999 /dev/urandom | base64 | head -c 479999 > "$JSONL"
python -c "
import compaction, time, pathlib
r = compaction.run_compaction(
    '$SID',
    session_updated_at=int(time.time()),
    now=int(time.time()),
    projects_dir=pathlib.Path('$HERMES_PROJECTS_DIR'),
)
print(r.status, r.meta.trigger_reason)
"
```
**期待値**:
- [ ] 出力: `noop none`

---

## T02b_size_boundary_eq / T02c_size_boundary_plus

**前提**: jsonl サイズが 480000 / 480001 bytes
**コマンド**: 上記 T02 を `head -c 480000` / `head -c 480001` で再実行（idle は短く保つ）
**期待値**:
- [ ] 480000 → `(True, "size")` で `status` は要約結果に依存（`summary_ok` / `summary_failed`）
- [ ] 480001 → 同上

---

## T03_noop_no_jsonl

**前提**: `session_id="ghost-sid"` だが jsonl が存在しない
**コマンド**:
```bash
python -c "
import compaction, pathlib
r = compaction.run_compaction(
    'ghost-sid',
    projects_dir=pathlib.Path('$HERMES_PROJECTS_DIR'),
)
print(r.status, r.meta.trigger_reason)
"
```
**期待値**:
- [ ] 出力: `noop no_jsonl`

---

## T04_trigger_size

**前提**: 480001 bytes jsonl、user/assistant 行を最低 11 ペア含む
**コマンド**:
```bash
SID=test-sid-04
JSONL="$HERMES_PROJECTS_DIR/-home-shohei-hermes-lite/${SID}.jsonl"
python - <<'PY'
import json, os, pathlib
sid = 'test-sid-04'
home = os.environ['HERMES_PROJECTS_DIR']
p = pathlib.Path(home) / '-home-shohei-hermes-lite' / f'{sid}.jsonl'
p.parent.mkdir(parents=True, exist_ok=True)
# 11 ペアの会話を生成、合計 480001 bytes 超
turns = []
for i in range(11):
    turns.append({"type":"user","message":{"role":"user","content":f"質問 {i}: ダミー長文 " * 200}})
    turns.append({"type":"assistant","message":{"role":"assistant","content":f"回答 {i}: ダミー長文 " * 200}})
with p.open('w') as f:
    for t in turns:
        f.write(json.dumps(t, ensure_ascii=False) + "\n")
print('size=', p.stat().st_size)
PY
```
**期待値**:
- [ ] jsonl size が 480001 以上
- [ ] `compaction.evaluate_compaction(...)` が `(True, "size")` を返す（実機 `python -c` 確認）
- [ ] `run_compaction` 実行で `_summarize` subprocess が 1 回呼ばれる（要約 claude のコスト発生に注意。実機検証は **CLAUDE_BIN を mock した dry-run** で確認することを推奨）

> dry-run 用に `MOCK_SUMMARIZE=1` 環境変数で `_summarize` を `lambda ...: "ダミー要約"` に差し替える hook を `compaction.py` に入れておくと手動チェックが安全（現状の plan で必須化はしないが、implementer に余裕があれば検討）。

---

## T05_trigger_idle / T05b_noop_idle_too_small

**前提**: jsonl サイズ
- T05: 60000 bytes（>= 50000 かつ < 480000）
- T05b: 30000 bytes（< 50000）

両方とも `session_updated_at = now - 48*3600 - 60`（48h+1分前）
**コマンド**: T02 と同様の python ワンライナーで `session_updated_at` を変えて実行
**期待値**:
- [ ] T05: `(True, "idle")`
- [ ] T05b: `(False, "none")`（idle 単独発火しない）

---

## T06_success_path / T06b_carry_recent_fenced / T06d_bot_prompt_rewrite

**前提**: T04 と同じ jsonl + `_summarize` モック（プロンプト経由で本物の sonnet 呼びは避ける）
**コマンド**:
```bash
python - <<'PY'
import compaction
# 簡易 monkey patch
orig = compaction._summarize
compaction._summarize = lambda older, prompt_path, settings: "## 概要\n前会話の要約ダミー"
try:
    r = compaction.run_compaction('test-sid-04', projects_dir=__import__('pathlib').Path(__import__('os').environ['HERMES_PROJECTS_DIR']))
    print('status=', r.status)
    print('resume=', r.resume_session_id)
    print('prefix_head=', repr(r.prompt_prefix[:80]) if r.prompt_prefix else None)
    print('has_recent_section=', '## 直近会話' in (r.prompt_prefix or ''))
    # T06d: build_effective_prompt
    eff = compaction.build_effective_prompt(r.prompt_prefix, 'こんにちは')
    print('eff_tail=', eff[-100:])
finally:
    compaction._summarize = orig
PY
```
**期待値**:
- [ ] `status= summary_ok`
- [ ] `resume= None`
- [ ] `prefix_head` が `'（システムメモ:` で始まる
- [ ] `has_recent_section= True`
- [ ] `eff_tail` の末尾に `---ここから新しいユーザー発話（コンパクション後の最初の依頼）---\nこんにちは` を含む
- [ ] `_FENCE` (`~~~~~`) が prefix 内に登場する

---

## T06c_fence_escape

**前提**: jsonl の content に `~~~~~` を含む
**コマンド**:
```bash
python - <<'PY'
import json, os, pathlib
sid = 'test-sid-06c'
home = os.environ['HERMES_PROJECTS_DIR']
p = pathlib.Path(home) / '-home-shohei-hermes-lite' / f'{sid}.jsonl'
p.parent.mkdir(parents=True, exist_ok=True)
turns = [{"type":"user","message":{"role":"user","content": "~~~~~ break " * 100}}] * 12
with p.open('w') as f:
    for t in turns:
        f.write(json.dumps(t, ensure_ascii=False) + "\n")
PY

python - <<'PY'
import compaction
orig = compaction._summarize
compaction._summarize = lambda *a, **k: "要約 ~~~~~ 中身"
try:
    r = compaction.run_compaction('test-sid-06c', projects_dir=__import__('pathlib').Path(__import__('os').environ['HERMES_PROJECTS_DIR']))
    assert '～～～～～' in (r.prompt_prefix or ''), 'fence escape did not happen'
    assert r.prompt_prefix.count('~~~~~') == 2, 'fence appears more than expected (should be only top/bottom)'
    print('OK')
finally:
    compaction._summarize = orig
PY
```
**期待値**:
- [ ] 出力に `OK`
- [ ] prefix 内に `~~~~~` が 2 回（fence の上下）だけ登場
- [ ] 本文の `~~~~~` が `～～～～～` に置換されている

---

## T06e_persistence_resume

**前提**: 実機 Discord runner で動作確認
**コマンド**: Discord で長文を約 60 回やり取りした既存 sid を用意（or `HERMES_COMPACTION_TOKEN_THRESHOLD=1000` を一時設定して低閾値で発火させる）
**期待値**:
- [ ] 1 回目: コンパクション通知が出て応答が返る
- [ ] 2 回目（同 scope_key）: 前会話の話題（具体的な固有名詞や約束した内容）を Claude が覚えている = `--resume <new_sid>` 経由でも prefix 内容が文脈として通じる

---

## T07_failure_path

**前提**: `_summarize` を失敗（None 返し）に差し替え
**コマンド**:
```bash
python - <<'PY'
import compaction
orig = compaction._summarize
compaction._summarize = lambda *a, **k: None  # failure
try:
    r = compaction.run_compaction('test-sid-04', projects_dir=__import__('pathlib').Path(__import__('os').environ['HERMES_PROJECTS_DIR']))
    print(r.status, r.resume_session_id is not None, r.prompt_prefix is None)
finally:
    compaction._summarize = orig
PY
```
**期待値**:
- [ ] 出力: `summary_failed True True`

---

## T07b_oversized_input

**前提**: jsonl の `older` 整形テキスト合計が `MAX_INPUT_BYTES`（1_600_000）超。テスト中は `_summarize` を成功 mock に差し替え。
**コマンド**: 巨大 jsonl を作って `run_compaction` を呼ぶ。monkey patch は必ず `try/finally` で元に戻すこと。
**期待値**:
- [ ] `r.meta.dropped_count > 0`
- [ ] `r.status == "summary_ok"`（間引いた状態で要約成功）
- [ ] bot 通知文字列に「サイズ超過のため古い履歴 N 件を要約から除外」が含まれる

## T15a_exception_before_trigger（Codex final review round 2 で分割）

**前提**: trigger 判定**前**の段階（`load_settings()` / `hermes_home` 解決等）で例外が起きる ＝ 設定読み込みのトラブル相当
**コマンド**:
```bash
python - <<'PY'
import compaction, pathlib, os
orig = compaction.load_settings
def boom():
    raise RuntimeError("settings boom")
compaction.load_settings = boom
try:
    r = compaction.run_compaction(
        'test-sid-15a',
        projects_dir=pathlib.Path(os.environ['HERMES_PROJECTS_DIR']),
    )
    print(r.status, r.meta.trigger_reason)
    # noop ＝ mark_failed は呼ばれない（cooldown 入りしない）
    print('cooldown_recorded=', 'test-sid-15a' in compaction._failed_recently)
finally:
    compaction.load_settings = orig
PY
```
**期待値**:
- [ ] 出力: `noop exception` + `cooldown_recorded= False`
- [ ] WARNING ログに `compaction.run_compaction crashed unexpectedly` + `trigger_passed=False` が含まれる
- [ ] bot.py 汎用 except に落ちない（notice=None で素通り）

---

## T15b_exception_after_trigger（Codex final review round 2 で分割）

**前提**: trigger 判定**後**の段階（`_extract_history` 周辺）で例外が起きる ＝ 肥大化 jsonl などで毎発話例外を放置すると危険なケース
**コマンド**:
```bash
python - <<'PY'
import compaction, pathlib, os
# trigger を必ず通すため size 閾値を超える jsonl をでっち上げる
sid = 'test-sid-15b'
home = os.environ['HERMES_PROJECTS_DIR']
p = pathlib.Path(home) / '-home-shohei-hermes-lite' / f'{sid}.jsonl'
p.parent.mkdir(parents=True, exist_ok=True)
p.write_bytes(b'x' * 600000)

# trigger 判定の後ろで例外を起こす
orig = compaction._extract_history
def boom(*a, **k):
    raise RuntimeError("extract boom")
compaction._extract_history = boom
# mark_failed 呼び出しを捕捉する
recorded = []
orig_mark = compaction.mark_failed
def spy_mark(s):
    recorded.append(s)
    orig_mark(s)
compaction.mark_failed = spy_mark
try:
    # cooldown 残骸が他テストから移ってこないように一旦クリア
    compaction._failed_recently.pop(sid, None)
    r = compaction.run_compaction(
        sid,
        projects_dir=pathlib.Path(home),
    )
    print(r.status, r.meta.trigger_reason)
    print('mark_failed_called=', sid in recorded)
    print('cooldown_recorded=', sid in compaction._failed_recently)
finally:
    compaction._extract_history = orig
    compaction.mark_failed = orig_mark
PY
```
**期待値**:
- [ ] 出力: `summary_failed exception` + `mark_failed_called= True` + `cooldown_recorded= True`
- [ ] WARNING ログに `compaction.run_compaction crashed unexpectedly` + `trigger_passed=True` が含まれる
- [ ] bot.py の `_build_compaction_notice` が「⚠️ コンパクション失敗（旧セッション継続）」を返す

---

## T07c_followup_run_failed（round 2 拡張: discord モジュールスタブで bot.py を実 import）

**前提**: 要約は成功するが `claude_runner.run` が `result.ok=False` で返るケース。さらに round 2 で「retry 後も通知判定は initial_result で固定」になっていることを実モジュール経路で smoke する。

`features/.../test/T07c_smoke.py` 相当として下記スクリプトを `gateway/discord/` で実行する：

```python
# T07c (round 2 拡張): discord モジュールを最小スタブ化して bot.py を実 import
import sys, types, os, asyncio, pathlib

# discord モジュールスタブ（discord.py が deploy venv にしか入っていない環境用）
fake_discord = types.ModuleType("discord")
fake_discord.HTTPException = type("HTTPException", (Exception,), {})
fake_discord.Forbidden = type("Forbidden", (fake_discord.HTTPException,), {})
fake_discord.Intents = type("Intents", (), {
    "default": staticmethod(
        lambda: types.SimpleNamespace(
            message_content=False, dm_messages=False, guild_messages=False
        )
    ),
})
class _FakeClient:
    def __init__(self, **kw):
        self.user = None
        self.loop = None
    def event(self, f):
        return f
    def run(self, *a, **kw):
        return None
fake_discord.Client = _FakeClient
fake_discord.DMChannel = type("DMChannel", (), {})
fake_discord.Thread = type("Thread", (), {})
fake_discord.Message = type("Message", (), {})
sys.modules.setdefault("discord", fake_discord)

# bot.py が config 経由で参照する env
os.environ.setdefault("DISCORD_TOKEN", "dummy")
os.environ.setdefault("ALLOWED_USER_IDS", "0")

sys.path.insert(0, str(pathlib.Path("gateway/discord").resolve()))
import bot
import claude_runner
import compaction

# claude_runner.run を monkey patch して initial_result 失敗 + retry_result 成功シナリオを再現
calls = []
async def fake_run(prompt, sid):
    calls.append((prompt[:30], sid))
    if len(calls) == 1:
        # 初回（要約 prefix 付き / resume_sid=None）: 失敗
        return claude_runner.RunResult(
            ok=False, text="boom", session_id=None, exit_code=1,
            invalid_resume=False, timed_out=False,
        )
    # 2 回目（旧 sid で retry）: 成功
    return claude_runner.RunResult(
        ok=True, text="ok-from-old", session_id="old-sid-x", exit_code=0,
        invalid_resume=False, timed_out=False,
    )
claude_runner.run = fake_run

# compaction.run_compaction を summary_ok mock
def fake_run_compaction(sid, **kw):
    return compaction.CompactionResult(
        status="summary_ok",
        resume_session_id=None,
        prompt_prefix="ダミー prefix",
        meta=compaction.CompactionMeta(
            old_sid="old-sid-x", old_jsonl="/tmp/x.jsonl",
            trigger_reason="size", older_count=5, recent_count=10, dropped_count=0,
        ),
    )
compaction.run_compaction = fake_run_compaction

# bot.store もダミー化（in-memory）
class _MemStore:
    def __init__(self):
        self._d = {}
    def get(self, k):
        return self._d.get(k)
    def get_updated_at(self, k):
        return None
    def set(self, k, v):
        self._d[k] = v
    def delete(self, k):
        self._d.pop(k, None)
mem = _MemStore()
bot.store = mem

# initial_result 失敗 + retry_result 成功シナリオで _run_with_resume を実行
result, notice = asyncio.run(bot._run_with_resume("こんにちは", "dm:1"))

assert result is not None
assert notice and "新セッション起動に失敗" in notice, (
    f"notice should warn old-continue, got: {notice!r}"
)
assert result.text == "ok-from-old", f"retry result.text expected, got: {result.text!r}"
# store は initial_result では更新されないが retry_result.session_id で updated_at 維持の
# ため set されている（store.set("dm:1", "old-sid-x")）
assert mem.get("dm:1") == "old-sid-x", (
    f"store should hold old sid after retry, got: {mem.get('dm:1')!r}"
)
# cooldown が打たれている
assert "old-sid-x" in compaction._failed_recently, "old_sid should be in cooldown"
print("OK")
```

**期待値**:
- [ ] `notice` に `⚠️ 要約は作成しましたが新セッション起動に失敗しました（旧継続: ...）` を含む
- [ ] `result.text == "ok-from-old"`（retry の応答テキストを返す）
- [ ] `compaction._failed_recently` dict に `old_sid` が記録されている（cooldown 入り）
- [ ] store は旧 sid を保持（retry の session_id をそのまま set。新 lineage への切替ではない）
- [ ] 出力末尾に `OK`

---

## T08_empty_history

**前提**: jsonl は trigger 閾値超だが、user/assistant ペアが 10 件未満（keep_user_turns=10 で older が空になる）
**コマンド**:
```bash
python - <<'PY'
import json, os, pathlib
sid = 'test-sid-08'
home = os.environ['HERMES_PROJECTS_DIR']
p = pathlib.Path(home) / '-home-shohei-hermes-lite' / f'{sid}.jsonl'
p.parent.mkdir(parents=True, exist_ok=True)
# 9 turns + 巨大 padding でサイズだけ確保
turns = []
for i in range(9):
    turns.append({"type":"user","message":{"role":"user","content":f"q{i}"}})
    turns.append({"type":"assistant","message":{"role":"assistant","content":f"a{i}"}})
turns.append({"type":"mode","mode":"normal","sessionId":sid, "padding": "x" * 500_000})
with p.open('w') as f:
    for t in turns:
        f.write(json.dumps(t, ensure_ascii=False) + "\n")
PY
python -c "
import compaction, pathlib, os
r = compaction.run_compaction('test-sid-08', projects_dir=pathlib.Path(os.environ['HERMES_PROJECTS_DIR']))
print(r.status, r.meta.trigger_reason)
"
```
**期待値**:
- [ ] 出力: `noop empty_history`

---

## T08b_cooldown

**前提**: 直前に `mark_failed(SID)` 呼んだ後、即 `run_compaction(SID)`
**コマンド**:
```bash
python -c "
import compaction, pathlib, os
compaction.mark_failed('test-sid-04')
r = compaction.run_compaction('test-sid-04', projects_dir=pathlib.Path(os.environ['HERMES_PROJECTS_DIR']))
print(r.status, r.meta.trigger_reason)
"
```
**期待値**:
- [ ] 出力: `noop cooldown`

---

## T08c_jsonl_content_blocks

**前提**: jsonl 行に `content=[{type:'text', text:'..'}, {type:'tool_use', ...}]` 形式を混ぜる
**期待値**:
- [ ] `_extract_history` の結果に text block の text のみ含まれる、tool_use は除外
- [ ] 空抽出になる行（tool_result のみ等）は採用されない

---

## T08d_corrupt_updated_at_str

**前提**: `sqlite3` で直接 `UPDATE sessions SET updated_at = 'abc' WHERE ...` した sqlite を用意（理論上 NOT NULL/INTEGER だが SQLite は緩い型）
**コマンド**: `SessionStore.get_updated_at(scope_key)` を呼んで `None` が返ることを確認
**期待値**:
- [ ] `None` 返却、例外なし
- [ ] その値で `evaluate_compaction` を呼ぶと idle 判定無効化、サイズ判定だけ実施

---

## T09_summarizer_cwd_isolated

**前提**: `_summarize` 実機呼びを 1 回行う（実際の CLAUDE_BIN を使うか、`HERMES_PROJECTS_DIR=$TMPHOME` でモック化）
**期待値**:
- [ ] 要約呼び出し後、`$TMPHOME/projects/-tmp-...` 系のディレクトリに jsonl ができる
- [ ] `$TMPHOME/projects/-home-shohei-hermes-lite/` には新規 jsonl が増えていない（要約 claude の cwd 分離が効いている）

---

## T10_runner_unchanged

**前提**: 既存 features/6 smoke と完全に同じ
**コマンド**:
```bash
cd gateway/discord
python -c "
from claude_runner import _build_cmd, _DEFAULT_SOUL
cmd = _build_cmd('hi', None)
assert '--append-system-prompt' in cmd
i = cmd.index('--append-system-prompt')
assert cmd[i+1] == _DEFAULT_SOUL.strip()
"
echo "OK"
```
**期待値**:
- [ ] exit 0 + `OK`
- [ ] `_build_cmd` シグネチャが `(prompt, resume_session_id)` のまま（third positional / kw 追加なし）

---

## T11_bot_notice_send

**前提**: 実機 Discord runner
**期待値**:
- [ ] 通知 → 本応答の順で表示される
- [ ] 通知 send 失敗（例: 一時的に bot 権限を剥奪して送信失敗させる）でも本応答は届く
- [ ] journalctl に `could not send compaction notice` warning が出る

---

## T12_kill_switch

**前提**: `HERMES_COMPACTION_ENABLED=0`
**コマンド**:
```bash
HERMES_COMPACTION_ENABLED=0 python -c "
import compaction, pathlib, os
r = compaction.run_compaction('test-sid-04', projects_dir=pathlib.Path(os.environ['HERMES_PROJECTS_DIR']))
print(r.status, r.meta.trigger_reason)
"
```
**期待値**:
- [ ] 出力: `noop kill_switch`

---

## T13_idempotent

**前提**: T06 成功直後（新 sid に切り替わった状態）+ 新 sid の jsonl はまだ存在 or 極小
**期待値**:
- [ ] 2 回目の `run_compaction(new_sid)` が `noop / none`（多重要約しない）

---

## T13b_lock_serialized

**前提**: 実機 Discord runner
**期待値**:
- [ ] 同一 scope_key（DM 等）で 2 連投メッセージ → 2 回目は 1 回目の処理完了を待ってから動く
- [ ] journalctl で 2 つの `handle from=...` が時間的に重ならない
- [ ] 既存 `locks: defaultdict(asyncio.Lock)` で確認できる挙動（本 issue で追加実装は不要）

---

## T14_mark_failed_none

**コマンド**:
```bash
python -c "
import compaction
compaction.mark_failed(None)
print('OK')
"
```
**期待値**:
- [ ] exit 0 + `OK`（例外なし）
- [ ] `compaction._failed_recently` は変更されていない
