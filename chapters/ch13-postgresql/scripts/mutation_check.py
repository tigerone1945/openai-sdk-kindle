"""テストが、壊れたコードを見つけられるかを確かめる(ミューテーション検査。第13章)。

コードを 1 か所ずつ壊し(判定を消す・反転する・値を差し替える)、テストが失敗することを確かめる。
失敗しない(SURVIVED)なら、そこを守るテストが無い。終わると、必ず元に戻す。
使い方(リポジトリ直下から):
  uv run --with pytest --with pytest-asyncio python chapters/ch13-postgresql/scripts/mutation_check.py
本文の「壊して確かめた変更 N 個」は、このスクリプトの実行結果。
  PostgreSQL のテストが必要(TEST_PG_URL。chapters/ch13-postgresql/scripts/start_test_postgres.sh で作れる)。
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
TESTS = "chapters/ch13-postgresql/tests"

# (壊すファイル(章の直下から), 元の文字列, 壊した文字列, 実行するテストの絞り込み(None なら全部))
MUTATIONS = [('src/repository.py', 'ON CONFLICT (order_id) DO NOTHING', '', None),
 ('src/repository.py', 'return int(value) if value == value.to_integral_value() else float(value)', 'return value', None),
 ('src/repository.py', 'ORDER BY o.total_amount DESC, o.order_id', 'ORDER BY o.order_id', None),
 ('src/repository.py', 'ORDER BY {order_by}', '', None),
 ('src/repository.py', "COALESCE(SUM(CASE WHEN status = 'キャンセル' THEN 1 ELSE 0 END), 0)", '0', None)]


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
