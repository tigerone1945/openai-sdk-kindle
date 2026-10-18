# ch13 src — ソースコードの案内

この章のソースコード（完全版のファイルと、本文の説明用の抜粋）の一覧です。

- 「完全ファイル」: 完成した、または主要なコード全体。
- 「抜粋」(`snippets/`): 本文で説明する部分コード。説明の順に番号を振っている。単体では動かない場合がある。
- `snippets/` と `scripts/import_csv_to_postgres.py` は比較用のファイルで、完全版とは内容が異なる場合があり、動作は未検証（本文では使わない）。**検証済みの完全版は `repository.py` / `db.py` / `catalog.py` / `agent_service.py` / `migrate.py` / `seed.py` / `api/main.py` / `compose.yaml`（本章の本文で使う版）**。

| ファイル | 種別 | 対応する節 | 行数 |
|---|---|---|---|
| `snippets/01_L198.env` | 抜粋 | `.env`へDB接続情報を追加する | 7 |
| `snippets/02_L220.yaml` | 抜粋 | `compose.yaml`へPostgreSQLを追加する | 45 |
| `db.py` | 完全ファイル | Database Connectionを共通化する | 11 |
| `scripts/import_csv_to_postgres.py` | 完全ファイル | CSVをPostgreSQLへ取り込む | 91 |
| `repository.py` | 完全ファイル | Repositoryを作る | 35 |
| `snippets/03_L475.py` | 抜粋 | 地域別売上Repository | 21 |
| `snippets/04_L503.py` | 抜粋 | 顧客種別別売上Repository | 23 |
| `snippets/05_L533.py` | 抜粋 | Function ToolはRepositoryを呼ぶだけにする | 23 |
