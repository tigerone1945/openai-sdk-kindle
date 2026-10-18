-- 第15章: アプリの「状態」(承認待ち・会話履歴)を、タスクのファイルから DB へ移す。
-- タスクは、いつでも入れ替わり、同時に複数台動く。状態をタスクの中に置くと、台が違う・入れ替わった途端に消える。

-- 承認待ち: RunState(Agent の一時停止した状態)を、承認の ID と結びつけて持つ。1 回だけ取り出せる。
CREATE TABLE pending_approvals (
    approval_id  TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    state        TEXT NOT NULL,
    created_at   DOUBLE PRECISION NOT NULL   -- epoch 秒。期限切れの掃除に使う
);

-- 会話履歴: Agents SDK の SQLAlchemySession が期待する形(テーブル名・列名は SDK の既定と同じ)。
CREATE TABLE agent_sessions (
    session_id  VARCHAR PRIMARY KEY,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE agent_messages (
    id            SERIAL PRIMARY KEY,
    session_id    VARCHAR NOT NULL REFERENCES agent_sessions (session_id) ON DELETE CASCADE,
    message_data  TEXT NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_agent_messages_session_time ON agent_messages (session_id, created_at);

-- 書き込み用の役割だけが使う。読み取り用(agent_ro)には、見せない:
-- 承認待ちには、実行を待っている操作の中身(RunState)が入っている。
GRANT SELECT, INSERT, UPDATE, DELETE ON pending_approvals, agent_sessions, agent_messages TO agent_rw;
GRANT USAGE ON SEQUENCE agent_messages_id_seq TO agent_rw;
