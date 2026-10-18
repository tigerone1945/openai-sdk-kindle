"""テストが、壊れたコードを見つけられるかを確かめる(ミューテーション検査。第15章)。

コードを 1 か所ずつ壊し(判定を消す・反転する・値を差し替える)、テストが失敗することを確かめる。
失敗しない(SURVIVED)なら、そこを守るテストが無い。終わると、必ず元に戻す。
使い方(リポジトリ直下から):
  uv run --with pytest --with pytest-asyncio python chapters/ch15-aws-deploy/scripts/mutation_check.py
本文の「壊して確かめた変更 N 個」は、このスクリプトの実行結果。
  PostgreSQL のテストが必要(TEST_PG_URL。chapters/ch13-postgresql/scripts/start_test_postgres.sh で作れる)。
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
TESTS = "chapters/ch15-aws-deploy/tests"

# (壊すファイル(章の直下から), 元の文字列, 壊した文字列, 実行するテストの絞り込み(None なら全部))
MUTATIONS = [('src/migrations/0003_state.sql', 'GRANT USAGE ON SEQUENCE agent_messages_id_seq TO agent_rw;', '', None),
 ('src/migrations/0003_state.sql', 'TO agent_rw;\nGRANT USAGE', 'TO agent_rw, agent_ro;\nGRANT USAGE', None),
 ('src/migrations/0003_state.sql', 'message_data  TEXT NOT NULL', 'message_data  TEXT', None),
 ('src/service.py',
  'return SQLAlchemySession(session_id, engine=_state_async_engine())',
  'return SQLiteSession(session_id, str(core.SESSION_DB_PATH))',
  None),
 ('src/agent_service.py', 'if os.environ.get("AUDIT_LOG_DEST") == "stdout":', 'if False:', None),
 ('src/service.py',
  '            # DELETE ... RETURNING は 1 文で完結する。2 台が同時に同じ承認を取りに来ても、片方だけが行を得る。\n'
  '            row = conn.execute(\n'
  '                text(\n'
  '                    "DELETE FROM pending_approvals WHERE approval_id = :a "\n'
  '                    "RETURNING session_id, state"\n'
  '                ),\n'
  '                {"a": approval_id},\n'
  '            ).first()\n',
  '            row = conn.execute(text("SELECT session_id, state FROM pending_approvals WHERE approval_id = :a"), {"a": '
  'approval_id}).first()\n'
  '            import time as _t; _t.sleep(0.05)\n'
  '            if row is not None:\n'
  '                conn.execute(text("DELETE FROM pending_approvals WHERE approval_id = :a"), {"a": approval_id})\n',
  None),
 ('src/terraform/tasks.tf',
  '{ name = "DB_HOST", value = aws_db_instance.postgres.address },',
  '{ name = "DB_HOST", value = aws_db_instance.postgres.address },\n    { name = "OPENAI_API_KEY", value = "sk-leak" },',
  ['chapters/ch15-aws-deploy/tests/test_terraform_policy.py', '-k', 'test_no_plaintext']),
 ('src/terraform/tasks.tf',
  '{ name = "OPENAI_API_KEY", valueFrom = aws_secretsmanager_secret.openai_api_key.arn },',
  '{ name = "OPENAI_API_KEY", valueFrom = aws_secretsmanager_secret.openai_api_key.arn },\n'
  '      { name = "DB_OWNER_PASSWORD", valueFrom = local.db_secret_arn },',
  ['chapters/ch15-aws-deploy/tests/test_terraform_policy.py', '-k', 'test_api_gets_only']),
 ('src/terraform/tasks.tf',
  'hostPort = 8000, ',
  '',
  ['chapters/ch15-aws-deploy/tests/test_terraform_policy.py', '-k', 'test_task_definitions_spell']),
 ('src/terraform/service_discovery.tf',
  '  dns_config {',
  '  health_check_custom_config {}\n\n  dns_config {',
  ['chapters/ch15-aws-deploy/tests/test_terraform_policy.py', '-k', 'test_task_definitions_spell']),
 ('src/terraform/tasks.tf',
  'cpu_architecture        = "ARM64"',
  'cpu_architecture        = "X86_64"',
  ['chapters/ch15-aws-deploy/tests/test_terraform_policy.py', '-k', 'test_services_roll_back']),
 ('src/terraform/ecr.tf',
  'image_tag_mutability = "IMMUTABLE"',
  'image_tag_mutability = "MUTABLE"',
  ['chapters/ch15-aws-deploy/tests/test_terraform_policy.py', '-k', 'test_ecr_tags']),
 ('src/terraform/secrets.tf',
  '  recovery_window_in_days = 0\n}\n\nresource "aws_secretsmanager_secret" "db_ro_password"',
  '  recovery_window_in_days = 0\n'
  '}\n'
  '\n'
  'resource "aws_secretsmanager_secret_version" "v" {\n'
  '  secret_id     = aws_secretsmanager_secret.openai_api_key.id\n'
  '  secret_string = "x"\n'
  '}\n'
  '\n'
  'resource "aws_secretsmanager_secret" "db_ro_password"',
  ['chapters/ch15-aws-deploy/tests/test_terraform_policy.py', '-k', 'test_secrets_are'])]


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
