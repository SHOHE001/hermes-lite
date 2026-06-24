# plan: #6 SOUL.md: 人格・トーンを 1 ファイルに集約し --append-system-prompt で渡す

slug: soul-md-1-append-system-prompt
milestone: Phase 1
labels: type:docs, batch:fixes
revision: 4 (Codex design loop 3 反映: 見出し prompt 混入除去 + 互換 alias + UnicodeError 捕捉 + ドリフト検知テスト)

## In-Scope / Out-of-Scope

| In-Scope | Out-of-Scope |
|---|---|
| リポジトリルートに `SOUL.md` を新設（旧 `APPEND_SYSTEM_PROMPT` の **そのままの移植先**） | bin/run-claude.sh への組み込み（Phase 2 別 Issue。jobs ごとの互換確認が必要） |
| `gateway/discord/claude_runner.py` を SOUL.md ファイル読み込み方式に差し替え | jobs (`jobs/ping/` 等) への `--append-system-prompt` 適用（Phase 2） |
| Python 側に `_DEFAULT_SOUL`（旧 APPEND_SYSTEM_PROMPT そのまま）を fallback として残す。SOUL.md が不在 / 空 / 読込失敗のいずれでも `_DEFAULT_SOUL` を使い、warning を出す → **旧挙動と完全互換** | 複数人格切替、per-job 上書き機構 |
| CLAUDE.md `### 1. 本家を入れない理由` に 1 行注記追加 | CLAUDE.md の責務再編、SOUL.md の人格そのものの刷新（中身は移植のみ） |
| 後方互換 alias: `APPEND_SYSTEM_PROMPT = _DEFAULT_SOUL` を残す（既存 import 互換維持） | SOUL.md と CLAUDE.md の責務再編（Phase 2 別 Issue） |

## Non-Goals

- 既存 Discord runner のトーン文言を**書き換える**こと（移植のみ。差分は別 Issue）
- SOUL.md と CLAUDE.md の責務分担の意味的な整理（Phase 2 で扱う）
- 全 jobs への共通適用（Phase 2）
- bin/run-claude.sh の引数構築変更
- 複数人格切替 / per-job 上書き
- SOUL.md にメタデータ（front matter / 注記コメント）を入れること（**prompt 本文に汚染を入れない**ため）

## 設計方針

### スコープ縮小と移行互換の理由（Codex design loop 1-2 を踏まえて）

- Codex 3 persona すべてが「全 jobs への適用は Phase 1 として過剰スコープ」と high で指摘 → Phase 1 は Discord runner のみに縮小。
- 同じく「APPEND_SYSTEM_PROMPT 定数を完全削除すると deploy 漏れ・退避時に旧挙動と差が出る（破壊的変更）」を high で指摘 → `_DEFAULT_SOUL` 定数（旧文字列そのまま）を Python 側に残す方針に変更。SOUL.md が無くても claude には旧 prompt が渡る。
- 「より単純な案（SOUL.md 追加のみで実装変更は後続）」と「Discord runner も今回変える案」の比較: ファイルだけ追加しても誰も読まないなら意味がない。Issue #6 の目的は「人格・トーンを 1 ファイルに集約**して使う**」なので、最低 1 経路（Discord runner）の読み込みは Phase 1 で必須。

### 二重注入リスクへの整合

現状の Discord runner (`gateway/discord/claude_runner.py:91-98`) は `subprocess.run` で claude CLI を**直接**起動しており、bin/run-claude.sh を経由していない。本 Issue では bin/run-claude.sh を触らないため、`--append-system-prompt` の二重注入は構造上発生しない。

### HERMES_HOME の定義

既存定義 (`gateway/discord/claude_runner.py:17`):

```python
HERMES_HOME = Path(__file__).resolve().parents[2]
```

`__file__` = `~/hermes-lite/gateway/discord/claude_runner.py` → `.parents[2]` = `~/hermes-lite/`（リポジトリルート）。systemd unit (`gateway/discord/systemd/*.service`) の WorkingDirectory が何であっても、`Path(__file__).resolve()` は絶対パス解決なので影響を受けない。SOUL.md はルート直下に置く前提で確実に解決できる。

### Fallback 設計（旧挙動互換）

`_load_soul()` は以下のいずれかでも warning を吐いて `_DEFAULT_SOUL` を返す:

- ファイル不在（`OSError: FileNotFoundError`）
- 読み込みエラー（その他の `OSError`）
- 中身が空または whitespace のみ（`strip()` 後が空）

これにより:

- SOUL.md が正常 → SOUL.md の内容を `--append-system-prompt` に渡す
- SOUL.md が壊れた / 無い → `_DEFAULT_SOUL`（= 旧 APPEND_SYSTEM_PROMPT そのまま）を `--append-system-prompt` に渡す
- どちらの場合も `--append-system-prompt` 自体は**常に**追加される（旧挙動と挙動契約が一致）

### SOUL.md の構造（Codex loop 3 を踏まえ、見出しも削除）

人間向けメタデータ（注記、見出し、front matter）は SOUL.md には**一切入れない**。理由: SOUL.md は丸ごと `--append-system-prompt` に渡されるので、見出しすら入れると claude の system prompt に「`# SOUL — hermes-lite の人格`」というノイズが混入する。これは「旧 APPEND_SYSTEM_PROMPT 完全互換」を破る。

そのため SOUL.md は:

- **本文 = 旧 APPEND_SYSTEM_PROMPT を Python 文字列連結したものとバイト完全一致**
- 見出し・空行・注記・コメントは一切なし
- Markdown 文書ではなく「プロンプト本文を格納するテキストファイル」と扱う

「本家パイプライン排除」「Issue #6 / Phase 1」などのメタは **CLAUDE.md 側のみ**に書く。

→ Python 文字列連結の隣接結合 (`"foo" "bar"` → `"foobar"`) を保つため、旧 APPEND_SYSTEM_PROMPT の各文字列はすべて**連結された状態の 1 つの文字列**として SOUL.md に書く。改行は元の Python ソース上の `"\n\n"` `"\n"` がそのまま改行になる。

### CLAUDE.md の本家排除条項との整合

CLAUDE.md `### 1. 本家を入れない理由` の末尾に 1 行注記を追加（後述の実装対象を参照）。

### Rollback 方針

- `_DEFAULT_SOUL` を残すので、SOUL.md を退避するだけで**旧挙動と同等**になる（fallback が旧文字列）
- それでも問題なら `git revert <merge-commit>` で plan の全変更を戻す

## 実装対象

### 旧 APPEND_SYSTEM_PROMPT（全文、移植元）

`gateway/discord/claude_runner.py:45-59`:

```python
APPEND_SYSTEM_PROMPT = (
    "あなたは Discord 上のしょうへい専用アシスタントです。"
    "返事は短く、確認質問はできる限りせず、わかる範囲で直接答えてください。"
    "天気・ニュース・最新情報など知らないことを聞かれたら WebSearch を積極的に使ってください。"
    "出力は読みやすい日本語の地の文を優先し、見出しや長いコードブロックは必要なときだけ。"
    "前の発言を覚えていて自然に続けてください。"
    "\n\n"
    "あなたは今 ~/hermes-lite/ ディレクトリにいます。ジョブ作成・修正の依頼を受けたら、"
    "まず ~/hermes-lite/CLAUDE.md を読んで、そこに書かれた手順に従ってください。"
    "\n"
    "判別の目安：「毎朝」「定期的に」「自動で」「いつも」「ジョブ化して」など継続実行を匂わせる依頼は"
    "~/hermes-lite/jobs/<name>/ にファイルを作って systemd timer に登録するジョブ化タスク。"
    "それ以外の単発質問はその場で答えるだけ。迷ったら一度だけ "
    "「ジョブにしておく？それとも今だけ答えるだけにする？」と聞いてください。"
)
```

### 新規ファイル: `SOUL.md`（リポジトリルート）

中身は旧 APPEND_SYSTEM_PROMPT の Python 文字列連結結果と**バイト完全一致**:

```
あなたは Discord 上のしょうへい専用アシスタントです。返事は短く、確認質問はできる限りせず、わかる範囲で直接答えてください。天気・ニュース・最新情報など知らないことを聞かれたら WebSearch を積極的に使ってください。出力は読みやすい日本語の地の文を優先し、見出しや長いコードブロックは必要なときだけ。前の発言を覚えていて自然に続けてください。

あなたは今 ~/hermes-lite/ ディレクトリにいます。ジョブ作成・修正の依頼を受けたら、まず ~/hermes-lite/CLAUDE.md を読んで、そこに書かれた手順に従ってください。
判別の目安：「毎朝」「定期的に」「自動で」「いつも」「ジョブ化して」など継続実行を匂わせる依頼は~/hermes-lite/jobs/<name>/ にファイルを作って systemd timer に登録するジョブ化タスク。それ以外の単発質問はその場で答えるだけ。迷ったら一度だけ 「ジョブにしておく？それとも今だけ答えるだけにする？」と聞いてください。
```

- 見出し / 注記 / front matter は無し
- ファイル末尾の改行は 1 つだけ（Unix 慣習）。`_load_soul()` が `.strip()` で除去するので意味差は無い
- ドリフト検知用のテスト T09 で `_load_soul()` の戻り値が `_DEFAULT_SOUL.strip()` と一致することを保証

### `gateway/discord/claude_runner.py` の編集

**Before**（45-59 行目）:

```python
APPEND_SYSTEM_PROMPT = (
    "あなたは Discord 上のしょうへい専用アシスタントです。"
    "返事は短く、確認質問はできる限りせず、わかる範囲で直接答えてください。"
    "天気・ニュース・最新情報など知らないことを聞かれたら WebSearch を積極的に使ってください。"
    "出力は読みやすい日本語の地の文を優先し、見出しや長いコードブロックは必要なときだけ。"
    "前の発言を覚えていて自然に続けてください。"
    "\n\n"
    "あなたは今 ~/hermes-lite/ ディレクトリにいます。ジョブ作成・修正の依頼を受けたら、"
    "まず ~/hermes-lite/CLAUDE.md を読んで、そこに書かれた手順に従ってください。"
    "\n"
    "判別の目安：「毎朝」「定期的に」「自動で」「いつも」「ジョブ化して」など継続実行を匂わせる依頼は"
    "~/hermes-lite/jobs/<name>/ にファイルを作って systemd timer に登録するジョブ化タスク。"
    "それ以外の単発質問はその場で答えるだけ。迷ったら一度だけ "
    "「ジョブにしておく？それとも今だけ答えるだけにする？」と聞いてください。"
)
```

**After**（同位置に置換）:

```python
# SOUL.md が読めない場合の旧挙動互換用 fallback。
# 中身は旧 APPEND_SYSTEM_PROMPT そのまま（Issue #6 移行時のセーフティネット）。
_DEFAULT_SOUL = (
    "あなたは Discord 上のしょうへい専用アシスタントです。"
    "返事は短く、確認質問はできる限りせず、わかる範囲で直接答えてください。"
    "天気・ニュース・最新情報など知らないことを聞かれたら WebSearch を積極的に使ってください。"
    "出力は読みやすい日本語の地の文を優先し、見出しや長いコードブロックは必要なときだけ。"
    "前の発言を覚えていて自然に続けてください。"
    "\n\n"
    "あなたは今 ~/hermes-lite/ ディレクトリにいます。ジョブ作成・修正の依頼を受けたら、"
    "まず ~/hermes-lite/CLAUDE.md を読んで、そこに書かれた手順に従ってください。"
    "\n"
    "判別の目安：「毎朝」「定期的に」「自動で」「いつも」「ジョブ化して」など継続実行を匂わせる依頼は"
    "~/hermes-lite/jobs/<name>/ にファイルを作って systemd timer に登録するジョブ化タスク。"
    "それ以外の単発質問はその場で答えるだけ。迷ったら一度だけ "
    "「ジョブにしておく？それとも今だけ答えるだけにする？」と聞いてください。"
)

_SOUL_FILE = HERMES_HOME / "SOUL.md"


def _load_soul() -> str:
    try:
        text = _SOUL_FILE.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as e:
        log.warning("SOUL.md not loadable (%s): %s — using built-in default", _SOUL_FILE, e)
        return _DEFAULT_SOUL
    if not text:
        log.warning("SOUL.md is empty (%s) — using built-in default", _SOUL_FILE)
        return _DEFAULT_SOUL
    return text


# 後方互換 alias: 既存 import 互換維持（Issue #6 移行期）
APPEND_SYSTEM_PROMPT = _DEFAULT_SOUL
```

**Before**（72-79 行目, `_build_cmd`）:

```python
def _build_cmd(prompt: str, resume_session_id: str | None) -> list[str]:
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json"]
    if resume_session_id:
        cmd.extend(["--resume", resume_session_id])
    cmd.extend(["--append-system-prompt", APPEND_SYSTEM_PROMPT])
    cmd.extend(["--allowed-tools", *ALLOWED_TOOLS])
    cmd.extend(["--disallowed-tools", *DISALLOWED_TOOLS])
    return cmd
```

**After**:

```python
def _build_cmd(prompt: str, resume_session_id: str | None) -> list[str]:
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json"]
    if resume_session_id:
        cmd.extend(["--resume", resume_session_id])
    cmd.extend(["--append-system-prompt", _load_soul()])
    cmd.extend(["--allowed-tools", *ALLOWED_TOOLS])
    cmd.extend(["--disallowed-tools", *DISALLOWED_TOOLS])
    return cmd
```

→ 引数順は完全に維持（resume → append-system-prompt → allowed-tools → disallowed-tools）。`_load_soul()` は必ず非空文字列を返すので、`--append-system-prompt` は**常に**追加される（旧挙動契約と一致）。

### `CLAUDE.md` の編集（`### 1. 本家を入れない理由` の末尾）

**Before**:

```markdown
- Hermes 本家の Python ランタイム・uv・SOUL.md・skill 自動生成器などはインストールしない
```

**After**:

```markdown
- Hermes 本家の Python ランタイム・uv・SOUL.md・skill 自動生成器などはインストールしない
  - 例外: 「SOUL.md」というファイル名のみは採用する（本家の自動生成パイプラインは入れず、静的に人間が編集するテキストとして運用。Issue #6 / Phase 1）。現状は Discord runner だけが読み込み、ファイル不在時は Python 側 `_DEFAULT_SOUL` にフォールバックする。
```

### 触らない

- `bin/run-claude.sh`（Phase 2 別 Issue で扱う）
- `lib/disallowed-tools.txt` / `lib/notify.sh`（CLAUDE.md 不可侵領域）
- `jobs/ping/`（Phase 2）
- `.env` / sessions.sqlite / systemd unit

## テスト計画（手動チェックリスト）

project_type=jobs。自動テストフレームは無いので手動検証。**破壊的なファイル操作は使わず、Python レベルで `_SOUL_FILE` を一時パスに差し替える**。

| ID | 内容 | 期待値 |
|---|---|---|
| T01 | `test -s SOUL.md` をリポジトリルートで実行 | exit 0（存在 + 非空） |
| T02 | SOUL.md の本文と `_DEFAULT_SOUL.strip()` が完全一致（**ドリフト検知**）: <br>`cd gateway/discord && python -c "import pathlib; from claude_runner import _DEFAULT_SOUL; soul = pathlib.Path('../../SOUL.md').read_text(encoding='utf-8').strip(); assert soul == _DEFAULT_SOUL.strip(), 'SOUL.md drifted from _DEFAULT_SOUL'"` | exit 0 |
| T03 | Discord runner の smoke test（正常系）: <br>`cd gateway/discord && python -c "from claude_runner import _build_cmd, _DEFAULT_SOUL; cmd = _build_cmd('hi', None); assert '--append-system-prompt' in cmd; i = cmd.index('--append-system-prompt'); assert cmd[i+1].startswith('あなたは Discord 上のしょうへい'), cmd[i+1][:60]; assert cmd[i+1] == _DEFAULT_SOUL.strip(), 'SOUL.md content must match _DEFAULT_SOUL.strip()'"` | exit 0（cmd の中身は `_DEFAULT_SOUL.strip()` と一致） |
| T04_boundary | SOUL.md 不在時に `_DEFAULT_SOUL` にフォールバック: <br>`cd gateway/discord && SOUL_TMP=$(mktemp -d); trap 'rm -rf "$SOUL_TMP"' EXIT; python -c "import logging, pathlib; logging.basicConfig(level=logging.WARNING); import claude_runner as r; r._SOUL_FILE = pathlib.Path('$SOUL_TMP/nope.md'); cmd = r._build_cmd('hi', None); assert '--append-system-prompt' in cmd; i = cmd.index('--append-system-prompt'); assert 'Discord 上のしょうへい' in cmd[i+1], cmd[i+1][:60]" 2> /tmp/soul-test.err; grep -q 'SOUL.md not loadable' /tmp/soul-test.err` | `--append-system-prompt` が含まれ、中身は `_DEFAULT_SOUL`、stderr に warning |
| T05_boundary | SOUL.md が空のときも `_DEFAULT_SOUL` にフォールバック: <br>`cd gateway/discord && SOUL_TMP=$(mktemp -d); trap 'rm -rf "$SOUL_TMP"' EXIT; touch "$SOUL_TMP/empty.md"; python -c "import logging, pathlib; logging.basicConfig(level=logging.WARNING); import claude_runner as r; r._SOUL_FILE = pathlib.Path('$SOUL_TMP/empty.md'); cmd = r._build_cmd('hi', None); assert '--append-system-prompt' in cmd; i = cmd.index('--append-system-prompt'); assert 'Discord 上のしょうへい' in cmd[i+1]" 2> /tmp/soul-test2.err; grep -q 'SOUL.md is empty' /tmp/soul-test2.err` | 同上（empty 警告） |
| T05b_boundary | SOUL.md が UTF-8 として壊れているときも fallback: <br>`cd gateway/discord && SOUL_TMP=$(mktemp -d); trap 'rm -rf "$SOUL_TMP"' EXIT; printf '\xff\xfe\x00\x00bad utf8\xff' > "$SOUL_TMP/broken.md"; python -c "import logging, pathlib; logging.basicConfig(level=logging.WARNING); import claude_runner as r; r._SOUL_FILE = pathlib.Path('$SOUL_TMP/broken.md'); cmd = r._build_cmd('hi', None); assert '--append-system-prompt' in cmd; i = cmd.index('--append-system-prompt'); assert 'Discord 上のしょうへい' in cmd[i+1]" 2> /tmp/soul-test3.err; grep -q 'SOUL.md not loadable' /tmp/soul-test3.err` | UnicodeError も捕捉、`_DEFAULT_SOUL` にフォールバック |
| T06 | 互換 alias が残存（既存 import 互換）: <br>`cd gateway/discord && python -c "from claude_runner import APPEND_SYSTEM_PROMPT, _DEFAULT_SOUL; assert APPEND_SYSTEM_PROMPT == _DEFAULT_SOUL"` | exit 0（後方互換維持） |
| T07 | CLAUDE.md に注記: <br>`grep -q '例外: 「SOUL.md」' CLAUDE.md` | exit 0 |
| T08 | resume_session_id 付きでも SOUL prompt が同時に渡る: <br>`cd gateway/discord && python -c "from claude_runner import _build_cmd; cmd = _build_cmd('hi', 'abc-session'); assert '--resume' in cmd and 'abc-session' in cmd; assert '--append-system-prompt' in cmd; i = cmd.index('--append-system-prompt'); assert 'Discord 上のしょうへい' in cmd[i+1]"` | exit 0 |

破壊的なテスト（SOUL.md 本体の退避・truncate）は**実施しない**。すべて `_SOUL_FILE` を Python レベルで一時パスに差し替える方式。

## ロールバック

問題が出た場合：

1. **SOUL.md を退避するだけで旧挙動と完全互換**（`_DEFAULT_SOUL` fallback が旧 APPEND_SYSTEM_PROMPT そのもの）
2. それでも問題なら `git revert <merge-commit>`

## Issue body 抜粋

## 目的

現在 Discord runner の `APPEND_SYSTEM_PROMPT` だけに散在している「Hermes-lite としての人格・口調・優先度ルール」を 1 ファイルに集約する。本家 Hermes の SOUL.md に相当する位置づけ。

## 手段（Phase 1 縮小版）

- リポジトリルートに `SOUL.md` を置く
- **Phase 1: gateway/discord/claude_runner.py のみ SOUL.md を読む**
- **Phase 2（別 Issue）: bin/run-claude.sh と全 jobs に展開**
- CLAUDE.md（仕様・運用ルール）と SOUL.md（Discord runner プロンプト外部化）は明示的に切り分ける
- SOUL.md 不在時は Python 側の `_DEFAULT_SOUL`（旧 APPEND_SYSTEM_PROMPT そのまま）にフォールバック → 旧挙動完全互換

## 詰めるべき論点（Phase 1 で解決）

- SOUL.md と CLAUDE.md の責務分担（**Phase 1 では「SOUL.md = Discord runner プロンプト外部化」とだけ規定。意味的な再編は Phase 2**）
- 全 job が SOUL.md を読み込むか、用途別に上書きできるか → Phase 1 では Discord runner のみ
- 既存の `APPEND_SYSTEM_PROMPT` を SOUL.md に移行する手順 → `_DEFAULT_SOUL` として残す + SOUL.md に同内容を配置

## 非スコープ

- 人格そのものの設計（中身は移植のみ）
- 複数人格の切り替え機構
- bin/run-claude.sh / jobs への適用（Phase 2）
- SOUL.md / CLAUDE.md の責務再編（Phase 2）

## 関連

- 既存: `gateway/discord/claude_runner.py` の `APPEND_SYSTEM_PROMPT`, `bin/run-claude.sh`, ルート `CLAUDE.md`
