"""監査ログの出力先と、イメージ・マイグレーションの静的な検査(AWS も DB も要らない)。"""
import hashlib
import json
import re

from conftest import CH13_SRC, ROOT, SRC, M

core = M.agent_service


def test_audit_log_goes_to_stdout_in_containers_and_leaves_no_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIT_LOG_DEST", "stdout")
    monkeypatch.setattr(core, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    core.write_audit_log("approved", tool="create_review_request", approval_id="a1")
    record = json.loads(capsys.readouterr().out.strip())
    assert record["event"] == "approved" and record["approval_id"] == "a1"
    assert not (tmp_path / "audit.jsonl").exists()


def test_audit_log_still_appends_to_a_file_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("AUDIT_LOG_DEST", raising=False)
    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(core, "AUDIT_LOG_PATH", path)
    core.write_audit_log("executed", order_id="O1")
    core.write_audit_log("executed", order_id="O2")
    assert [json.loads(line)["order_id"] for line in path.read_text().splitlines()] == ["O1", "O2"]
    assert capsys.readouterr().out == ""


def test_audit_log_keeps_non_ascii_readable(monkeypatch, capsys):
    monkeypatch.setenv("AUDIT_LOG_DEST", "stdout")
    core.write_audit_log("rejected", reason="割引率の確認")
    assert "割引率の確認" in capsys.readouterr().out


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_applied_migrations_are_byte_identical_to_chapter_13():
    """RDS は、第13章の 0001・0002 を記録している。1 バイトでも違うと、migrate が「書き換えられた」と止まる。"""
    for name in ("0001_schema.sql", "0002_privileges.sql"):
        assert _sha(SRC / "migrations" / name) == _sha(CH13_SRC / "migrations" / name), name
    assert sorted(p.name for p in (SRC / "migrations").glob("*.sql")) == ["0001_schema.sql", "0002_privileges.sql", "0003_state.sql"]


def test_state_tables_are_not_readable_by_the_read_only_role():
    sql = (SRC / "migrations/0003_state.sql").read_text()
    grants = re.findall(r"GRANT .*? TO (\w+)", sql)
    assert grants and set(grants) == {"agent_rw"}


def test_dockerfile_copies_only_files_that_exist_and_needs_no_app_data():
    text = "\n".join(l for l in (SRC / "Dockerfile.api").read_text().splitlines() if not l.lstrip().startswith("#"))
    assert "/app/data" not in text and "VOLUME" not in text  # 状態をタスクのファイルに置かない
    assert "AUDIT_LOG_DEST=stdout" in text
    copies = re.findall(r"^COPY ((?:[^\n\\]|\\\n)+?) \S+$", text, re.M)
    for spec in copies:
        for src in spec.replace("\\\n", " ").split():
            assert (ROOT / src).exists(), f"COPY 元が存在しません: {src}"


def test_service_does_not_write_state_files_when_database_backend_is_postgres():
    source = (SRC / "service.py").read_text()
    assert "use_database()" in source and source.count("open_session(session_id)") == 2
    assert "SQLiteSession(session_id" not in source.replace("return SQLiteSession(session_id, str(core.SESSION_DB_PATH))", "")
