-- 権限。役割(agent_ro / agent_rw)は migrate.py が作る(パスワードを、SQLファイルに書かないため)。
-- Agentのアプリが使うのは、この2つだけ。DDL(Tableの作成・変更)をできる役割は、アプリに渡さない。
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO agent_ro, agent_rw;

-- 読み取り用:業務データを読めるだけ。レビュー依頼のTableは見えない。
GRANT SELECT ON customers, products, orders TO agent_ro;
-- 書き込み用:レビュー依頼の登録だけ。売上・顧客・商品は、読めるが、書き換えられない。
GRANT SELECT ON customers, products, orders TO agent_rw;
GRANT SELECT, INSERT ON review_requests TO agent_rw;

-- 役割そのものの制約(アプリの接続の書き方に頼らず、DBが強制する)。
ALTER ROLE agent_ro SET default_transaction_read_only = on;
ALTER ROLE agent_ro SET statement_timeout = '10s';
ALTER ROLE agent_rw SET statement_timeout = '10s';
