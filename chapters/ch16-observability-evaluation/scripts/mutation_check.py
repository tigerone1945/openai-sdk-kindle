"""テストが、壊れたコードを見つけられるかを確かめる(ミューテーション検査。第16章)。

コードを 1 か所ずつ壊し(判定を消す・反転する・値を差し替える)、テストが失敗することを確かめる。
失敗しない(SURVIVED)なら、そこを守るテストが無い。終わると、必ず元に戻す。
使い方(リポジトリ直下から):
  uv run --with pytest --with pytest-asyncio python chapters/ch16-observability-evaluation/scripts/mutation_check.py
本文の「壊して確かめた変更 N 個」は、このスクリプトの実行結果。
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
TESTS = "chapters/ch16-observability-evaluation/tests"

# (壊すファイル(章の直下から), 元の文字列, 壊した文字列, 実行するテストの絞り込み(None なら全部))
MUTATIONS = [('src/observability.py',
  'if k.lower() not in FORBIDDEN_FIELDS}',
  '}',
  ['chapters/ch16-observability-evaluation/tests/test_observability.py', 'chapters/ch16-observability-evaluation/tests/test_privacy.py']),
 ('src/observability.py',
  'if request.url.path != "/health":',
  'if True:',
  ['chapters/ch16-observability-evaluation/tests/test_observability.py', 'chapters/ch16-observability-evaluation/tests/test_privacy.py']),
 ('src/observability.py',
  'path=getattr(route, "path", request.url.path),',
  'path=request.url.path,',
  ['chapters/ch16-observability-evaluation/tests/test_observability.py', 'chapters/ch16-observability-evaluation/tests/test_privacy.py']),
 ('src/service.py',
  'error_type=type(e).__name__, duration_ms=_ms(started),\n',
  'error_type=str(e), duration_ms=_ms(started),\n',
  ['chapters/ch16-observability-evaluation/tests/test_observability.py', 'chapters/ch16-observability-evaluation/tests/test_privacy.py']),
 ('src/observability.py',
  'value.model_settings = value.model_settings.resolve(ModelSettings(store=False))',
  'pass',
  ['chapters/ch16-observability-evaluation/tests/test_observability.py', 'chapters/ch16-observability-evaluation/tests/test_privacy.py']),
 ('src/service.py',
  'PRIVATE_AGENTS = apply_privacy_policy(core)',
  'PRIVATE_AGENTS = []',
  ['chapters/ch16-observability-evaluation/tests/test_observability.py', 'chapters/ch16-observability-evaluation/tests/test_privacy.py']),
 ('src/service.py',
  '        if isinstance(error, (PgOperationalError, PgInterfaceError, PoolTimeoutError, InterfaceError)):\n            return True\n',
  '        if False:\n            return True\n',
  ['chapters/ch16-observability-evaluation/tests/test_state_failure.py']),
 ('src/service.py',
  '        error = error.__cause__ or error.__context__\n    return False\n\n\n@contextmanager',
  '        error = None\n    return False\n\n\n@contextmanager',
  ['chapters/ch16-observability-evaluation/tests/test_state_failure.py']),
 ('src/service.py',
  '        if _storage_failure(e):\n'
  '            raise StorageUnavailableError("保存先を利用できません。") from e\n'
  '        raise\n'
  '\n'
  '    with storage_failures_as_unavailable():\n'
  '        outcome = _to_outcome(result, session_id)\n'
  '    _log_outcome(outcome, session_id, started)',
  '        raise\n'
  '\n'
  '    with storage_failures_as_unavailable():\n'
  '        outcome = _to_outcome(result, session_id)\n'
  '    _log_outcome(outcome, session_id, started)',
  ['chapters/ch16-observability-evaluation/tests/test_state_failure.py']),
 ('src/service.py',
  '        with storage_failures_as_unavailable(), _state_engine().begin() as conn:\n'
  '            conn.execute(\n'
  '                text(\n'
  '                    "INSERT INTO pending_approvals',
  '        with _state_engine().begin() as conn:\n'
  '            conn.execute(\n'
  '                text(\n'
  '                    "INSERT INTO pending_approvals',
  ['chapters/ch16-observability-evaluation/tests/test_state_failure.py'])]


def run_tests(extra):
    cmd = [sys.executable, "-m", "pytest", *(extra or [TESTS]), "-q", "-x", "-p", "no:cacheprovider"]
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True).returncode != 0


def main() -> int:
    if run_tests(None):
        print("壊す前のテストが失敗しています。先にテストを通してください")
        return 2
    bad = []
    for rel, old, new, extra in MUTATIONS:
        path = ROOT / rel
        original = path.read_text()
        if old not in original:
            print("NOT FOUND:", rel, old[:60].replace("\n", "\\n"))
            bad.append(("not found", rel))
            continue
        path.write_text(original.replace(old, new, 1))
        try:
            killed = run_tests(extra)
        finally:
            path.write_text(original)
        print("KILLED  " if killed else "SURVIVED", rel, "|", old[:70].replace("\n", "\\n"))
        if not killed:
            bad.append(("survived", rel))
    print(f"\n{len(MUTATIONS) - len(bad)} / {len(MUTATIONS)} を検出")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
