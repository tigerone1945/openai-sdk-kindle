# ch08 src — ソースコードの案内

この章のソースコード（完全版のファイルと、本文の説明用の抜粋）の一覧です。

- 「完全ファイル」: 完成した、または主要なコード全体。
- 「抜粋」(`snippets/`): 本文で説明する部分コード。説明の順に番号を振っている。単体では動かない場合がある。
- `snippets/` は比較用の抜粋で、完全版とは内容が異なる場合があり、単体での動作は未検証。**検証済みの完全版は `agent_service.py` / `main.py` / `scripts/import_csv_to_sqlite.py`（本章の本文で使う版）**。

| ファイル | 種別 | 対応する節 | 行数 |
|---|---|---|---|
| `snippets/01_L155.sql` | 抜粋 | なぜCSVからSQLiteへ移るのか | 5 |
| `scripts/import_csv_to_sqlite.py` | 完全ファイル | まずCSVをSQLiteへ取り込む | 58 |
| `snippets/02_L339.py` | 抜粋 | Agent ToolをSQLite版へ変更する | 13 |
| `snippets/03_L359.py` | 抜粋 | Tool 1：売上全体 | 36 |
| `snippets/04_L402.py` | 抜粋 | Tool 2：カテゴリ別売上 | 23 |
| `snippets/05_L432.py` | 抜粋 | Tool 3：地域別売上 | 23 |
| `snippets/06_L464.py` | 抜粋 | Tool 4：要レビュー注文を確認する | 44 |
