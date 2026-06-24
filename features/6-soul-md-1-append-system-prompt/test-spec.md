# test-spec: #6 SOUL.md 手動チェックリスト

project_type=jobs。自動テストフレームは無い。すべて手動でコマンドを実行し、期待値を確認する。

## 前提セットアップ

- 作業ブランチ `gloop/6-soul-md-1-append-system-prompt` 上で実装完了済み
- `cd ~/hermes-lite` がリポジトリルート
- `gateway/discord/` で `python3 -c "..."` が動作すること（venv 不要、CLAUDE_BIN だけ import 内で参照）

## チェックリスト

### T01: SOUL.md 存在 + 非空

- [ ] コマンド: `test -s SOUL.md`
- [ ] 期待値: exit 0

### T02: SOUL.md ↔ `_DEFAULT_SOUL` ドリフト検知

- [ ] コマンド:
  ```bash
  cd gateway/discord && python3 -c "
import pathlib
from claude_runner import _DEFAULT_SOUL
soul = pathlib.Path('../../SOUL.md').read_text(encoding='utf-8').strip()
assert soul == _DEFAULT_SOUL.strip(), 'SOUL.md drifted from _DEFAULT_SOUL'
print('OK')
"
  ```
- [ ] 期待値: `OK` 出力、exit 0

### T03: 正常系 smoke test

- [ ] コマンド:
  ```bash
  cd gateway/discord && python3 -c "
from claude_runner import _build_cmd, _DEFAULT_SOUL
cmd = _build_cmd('hi', None)
assert '--append-system-prompt' in cmd
i = cmd.index('--append-system-prompt')
assert cmd[i+1].startswith('あなたは Discord 上のしょうへい'), cmd[i+1][:60]
assert cmd[i+1] == _DEFAULT_SOUL.strip(), 'SOUL.md content must match _DEFAULT_SOUL.strip()'
print('OK')
"
  ```
- [ ] 期待値: `OK` 出力、exit 0

### T04: SOUL.md 不在時に `_DEFAULT_SOUL` にフォールバック

- [ ] コマンド:
  ```bash
  cd gateway/discord
  SOUL_TMP=$(mktemp -d)
  trap 'rm -rf "$SOUL_TMP"' EXIT
  python3 -c "
import logging, pathlib
logging.basicConfig(level=logging.WARNING)
import claude_runner as r
r._SOUL_FILE = pathlib.Path('$SOUL_TMP/nope.md')
cmd = r._build_cmd('hi', None)
assert '--append-system-prompt' in cmd
i = cmd.index('--append-system-prompt')
assert 'Discord 上のしょうへい' in cmd[i+1], cmd[i+1][:60]
print('OK')
" 2> /tmp/soul-test.err
  cat /tmp/soul-test.err
  grep -q 'SOUL.md not loadable' /tmp/soul-test.err && echo 'WARN OK'
  ```
- [ ] 期待値: `OK` 出力、stderr に `SOUL.md not loadable`、`WARN OK` 出力

### T05: SOUL.md 空のとき `_DEFAULT_SOUL` にフォールバック

- [ ] コマンド:
  ```bash
  cd gateway/discord
  SOUL_TMP=$(mktemp -d)
  trap 'rm -rf "$SOUL_TMP"' EXIT
  touch "$SOUL_TMP/empty.md"
  python3 -c "
import logging, pathlib
logging.basicConfig(level=logging.WARNING)
import claude_runner as r
r._SOUL_FILE = pathlib.Path('$SOUL_TMP/empty.md')
cmd = r._build_cmd('hi', None)
assert '--append-system-prompt' in cmd
i = cmd.index('--append-system-prompt')
assert 'Discord 上のしょうへい' in cmd[i+1]
print('OK')
" 2> /tmp/soul-test2.err
  grep -q 'SOUL.md is empty' /tmp/soul-test2.err && echo 'WARN OK'
  ```
- [ ] 期待値: `OK` 出力、stderr に `SOUL.md is empty`、`WARN OK` 出力

### T05b: SOUL.md が UTF-8 として壊れているとき fallback

- [ ] コマンド:
  ```bash
  cd gateway/discord
  SOUL_TMP=$(mktemp -d)
  trap 'rm -rf "$SOUL_TMP"' EXIT
  printf '\xff\xfe\x00\x00bad utf8\xff' > "$SOUL_TMP/broken.md"
  python3 -c "
import logging, pathlib
logging.basicConfig(level=logging.WARNING)
import claude_runner as r
r._SOUL_FILE = pathlib.Path('$SOUL_TMP/broken.md')
cmd = r._build_cmd('hi', None)
assert '--append-system-prompt' in cmd
i = cmd.index('--append-system-prompt')
assert 'Discord 上のしょうへい' in cmd[i+1]
print('OK')
" 2> /tmp/soul-test3.err
  grep -q 'SOUL.md not loadable' /tmp/soul-test3.err && echo 'WARN OK'
  ```
- [ ] 期待値: `OK` 出力、UnicodeError 捕捉、stderr に warning

### T06: 後方互換 alias 残存

- [ ] コマンド:
  ```bash
  cd gateway/discord && python3 -c "
from claude_runner import APPEND_SYSTEM_PROMPT, _DEFAULT_SOUL
assert APPEND_SYSTEM_PROMPT == _DEFAULT_SOUL, 'alias drift'
print('OK')
"
  ```
- [ ] 期待値: `OK` 出力

### T07: CLAUDE.md 注記

- [ ] コマンド: `grep -q '例外: 「SOUL.md」' CLAUDE.md && echo 'OK'`
- [ ] 期待値: `OK` 出力

### T08: resume_session_id 付きで `--resume` と `--append-system-prompt` が同居

- [ ] コマンド:
  ```bash
  cd gateway/discord && python3 -c "
from claude_runner import _build_cmd
cmd = _build_cmd('hi', 'abc-session')
assert '--resume' in cmd and 'abc-session' in cmd
assert '--append-system-prompt' in cmd
i = cmd.index('--append-system-prompt')
assert 'Discord 上のしょうへい' in cmd[i+1]
print('OK')
"
  ```
- [ ] 期待値: `OK` 出力
