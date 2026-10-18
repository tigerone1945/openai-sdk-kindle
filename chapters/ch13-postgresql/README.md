# 第13章 SQLiteからPostgreSQLへ移行する

> 状態：**実行確認済み**（2026-10-12、PostgreSQL 17.11 / SQLAlchemy 2.1.4 / psycopg 3.3.6 / Docker 29.8.2 / Python 3.13、モデルはSDKデフォルト）。モデル名・LLMの挙動・計測値は更新で変わるため、出版直前に再確認する。

## 1. Kindle対応章

本書の第13章「SQLiteからPostgreSQLへ移行する」に対応します。この章の完全なソースコードは `src/` にあります（ファイルの案内は `src/README.md`）。実行手順は、この README に記載しています。

## 2. この章で追加するCapability

- 業務データの置き場を PostgreSQL に移す。**Tool の名前・説明・出力の形式は、第11〜12章と同じ**
- Repository（`repository.py`）：SQL を知る唯一の層。SQLAlchemy Core で、SQLite と PostgreSQL の**両方で動く**1つの実装
- 接続（`db.py`）：部品（ユーザー・パスワード・ホスト）から組み立てる。プール設定（`pool_pre_ping` など）を明示
- DB の役割（権限）の分離：`agent_ro`（読み取りのみ）/ `agent_rw`（レビュー依頼の登録のみ）/ owner（DDL。migrate ジョブだけ）
- マイグレーション（`migrate.py` + `migrations/*.sql`）：順番に・一度だけ・競合せずに適用。第12章の `init_db.py` の置き換え
- SQLite → PostgreSQL のデータ移行（`scripts/migrate_sqlite_to_postgres.py`）：全行を照合してから確定
- DB の障害を、API が 503（`database_unavailable`）で返す。`/ready`（DB まで確かめる）を追加
- Compose に `db`（PostgreSQL）と `migrate`（ジョブ）を追加。DB のポートは公開しない

## 3. 前章からの変更点

- 前章（第12章）で残った課題：SQLite は本番のデータストアとして弱い
- 変更: `agent_service.py` から SQL を取り除いた（Tool → Repository → DB）。`api/main.py` に `/ready` と DB 障害の対応づけを追加。`service.py`・`ui/` は第11章のまま
- 新規: `catalog.py`（許可する Join・切り口の定義。DB に依存しない）、`repository.py`、`db.py`、`migrate.py`、`seed.py`、`migrations/`
- 手元の開発・テストでは、SQLite も使える（`DB_BACKEND=sqlite` が既定）。コンテナでは `DB_BACKEND=postgres`
- まだファイルのままの状態: 会話履歴（`conversations.db`）・承認待ち（`approvals.db`）・監査ログ（`audit_log.jsonl`）。`api` は、まだ1台に縛られる

## 4. この章で確認するFile

- `src/repository.py`（Repository の契約と実装）
- `src/db.py`（接続・プール）、`src/catalog.py`（業務上の定義）
- `src/agent_service.py`（SQL を持たない Tool 層）、`src/api/main.py`（`/ready`・DB 障害の 503）
- `src/migrate.py` + `src/migrations/`（スキーマ・権限）、`src/seed.py`（デモデータ）
- `src/scripts/migrate_sqlite_to_postgres.py`（既存の SQLite からの移行）
- `src/Dockerfile.api` / `src/compose.yaml`
- `scripts/start_test_postgres.sh`（テスト用の PostgreSQL を起動）
- `tests/`（126件。PostgreSQL なしでも 87 件が動く）
- `src/snippets/` と `src/scripts/import_csv_to_postgres.py`（比較用のファイルで、完全版とは内容が異なる。本文では使わない）

## 5. 実行方法

リポジトリのルートで実行する（Setup は第1章 README を参照）。Docker が起動している必要がある。

`.env` に、`.env.example` の第13章の項目（`DB_OWNER_PASSWORD` `DB_RO_PASSWORD` `DB_RW_PASSWORD`）を設定する（3つとも別の値。例: `openssl rand -base64 18`）。

```bash
docker compose -f chapters/ch13-postgresql/src/compose.yaml --env-file .env up --build
```

起動順序は `db`（healthy）→ `migrate`（スキーマ・役割・デモデータ。終了）→ `api`（`/ready` が応答）→ `ui`。画面は http://127.0.0.1:8501。

- 止める（状態は残る）: 上の `up` を `down` に。状態も消す: `down -v`（`pg-data` と `app-data` が消える）
- 本番ではデモデータを入れない: `.env` に `SEED_DEMO_DATA=false`
- 第12章（SQLite）のデータを移す: ① `SEED_DEMO_DATA=false` でスキーマだけ作る（`docker compose ... run --rm migrate`）② 移行スクリプトを実行（下の注意を参照）

```bash
# 例: 第12章のボリュームから取り出した sales.db を、空のPostgreSQLへ移す(登録日時を東京時間として読む)
docker run --rm --network ai-sales-agent_default --read-only --tmpfs /tmp \
  -e DB_HOST=db -e DB_NAME=ai_agent -e DB_OWNER_USER=app_owner -e DB_OWNER_PASSWORD="<owner のパスワード>" \
  -v "$PWD/chapters/ch13-postgresql/src:/opt/src:ro" -v "/path/to/sales.db:/tmp/old/sales.db:ro" \
  ai-sales-agent-api:ch13 python /opt/src/scripts/migrate_sqlite_to_postgres.py /tmp/old/sales.db --timezone Asia/Tokyo
```

テスト：

```bash
source chapters/ch13-postgresql/scripts/start_test_postgres.sh       # テスト用のPostgreSQLを起動し、TEST_PG_URL を設定
uv run --with pytest --with pytest-asyncio pytest chapters/ch13-postgresql/tests -q    # 126 passed
docker rm -f ch13-test-postgres                                        # 後片付け
```

`TEST_PG_URL` がないときは、PostgreSQL のテスト（39件）は、理由つきでスキップされる（SQLite のテストだけが動く）。**CI では、必ず PostgreSQL ありで実行すること。**

## 6. Expected Result

- テスト：PostgreSQL ありで 126 passed（全章まとめて 234 passed）。なしで 87 passed / 39 skipped
- 起動：約 14 秒（`db` healthy → `migrate` 終了 → `api` healthy → `ui`）
- 同じテストが、SQLite と PostgreSQL の両方で通り、Tool の出力が完全に一致する
- `api` の資格情報では、`DELETE` / `DROP` / `CREATE TABLE` が拒否される。`agent_ro` は `review_requests` も見えない
- DB を止める → `/ready` と `/analysis` が 503 `database_unavailable`（`/health` は 200）。再開すると、api を再起動せずに復旧する
- 実行例・計測値は [expected_output/example_run.txt](expected_output/example_run.txt) を参照

注意:
- **テスト用の PostgreSQL は、専用のコンテナで。** 役割（`agent_ro` / `agent_rw`）は、PostgreSQL のクラスタ全体で共通で、テストは役割のパスワードを書き換える。開発用の DB に向けて実行しない
- 認証・認可（アプリの利用者の）はまだない（第11章のまま）。ポートは `127.0.0.1` のみ
- DB への接続は、Compose のネットワーク内の平文（TLS なし）。クラウドでは TLS を使う（第15章）
- マイグレーションは**前進のみ**（ロールバック用の「down」はない）。適用済みのファイルを書き換えると、失敗する
- `docker inspect` / `docker compose config` は、パスワードを表示する。画面共有・ログに貼らない
- バックアップはまだない（`pg-data` ボリュームを消すと、業務データも消える）

## 7. 次章で変更される点

- ここまでの Application は、すべて手元の Docker の上。クラウド（AWS）で動かせていない
- 次章：`../ch14-terraform/`

## テストの検査(ミューテーション)

コードを 1 か所ずつ壊して、テストが失敗することを確かめる。

```bash
TEST_PG_URL=... uv run --with pytest --with pytest-asyncio python chapters/ch13-postgresql/scripts/mutation_check.py
```
