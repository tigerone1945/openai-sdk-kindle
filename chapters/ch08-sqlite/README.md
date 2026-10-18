# 第8章 CSVからSQLiteへ移行する

> 状態：**実行確認済み**（2026-10-12、Python 3.13.8 / openai-agents 0.22.3 / pandas 3.0.6 / SQLite 3.x、モデルはSDKデフォルト）。モデル名はSDKの更新で変わるため、出版直前に再確認する。

## 1. Kindle対応章

本書の第8章「CSVからSQLiteへ移行する」に対応します。この章の完全なソースコードは `src/` にあります（ファイルの案内は `src/README.md`）。実行手順は、この README に記載しています。

## 2. この章で追加するCapability

- 業務データ（売上・レビュー依頼）を CSV から SQLite（`data/sales.db`）へ移す
- スキーマを明示した取り込み（主キー・CHECK・外部キー）
- Tool の Interface（名前・説明）は維持し、中身だけ SQL に差し替える
- `get_review_orders`（要レビュー注文の検索。Parameterized Query）
- レビュー依頼を `review_requests` テーブルに保存（主キーによる重複防止）

## 3. 前章からの変更点

- 前章（第7章）で残った課題：業務データが CSV のまま
- 差分: `load_sales_data()`（pandas）を `get_connection()` + SQL に置換。SQL を知る関数（`sales_summary` など）と、Agent に見せる Tool（`get_sales_summary` など）を分離
- `create_review_request` の登録先を `data/review_requests.csv` から `review_requests` テーブルへ。重複確認は DB の主キー（`ON CONFLICT DO NOTHING`）に任せる
- 監査ログ（`data/audit_log.jsonl`）は第7章のまま

## 4. この章で確認するFile

- `src/scripts/import_csv_to_sqlite.py`（スキーマ定義つきの取り込み）
- `src/agent_service.py`（SQLite 版の完全版）
- `src/main.py`（第7章と同じ CLI）
- `tests/test_sqlite_migration.py`（LLM なしの検証。9件）
- `src/snippets/`（本文の説明用の抜粋。完全版とは内容が異なり、CSV パスや `@tool` の書き方が完全版と一致しない。本文では使わない）

## 5. 実行方法

リポジトリのルートで実行する（Setup は第1章 README を参照）。

```bash
uv run python chapters/ch08-sqlite/src/scripts/import_csv_to_sqlite.py
uv run python chapters/ch08-sqlite/src/main.py
uv run --with pytest pytest chapters/ch08-sqlite/tests -q
```

`data/sales.db` は実行時に生成され、`.gitignore`（`*.db`）で除外される。取り込みスクリプトは**実行のたびに DB を作り直す**（`review_requests` も消える）。

## 6. Expected Result

- 取り込み：「300件を data/sales.db へ取り込みました。」売上合計は 28,298,695円（第1章と同じ）
- テスト：9 passed
- Agent：第7章と同じ質問に、同じ数値で答える。レビュー依頼は `review_requests` テーブルに入る
- 同じ注文の二重登録は、承認されても Tool が拒否する

文面は実行ごとに変わる。実行例は [expected_output/example_run.txt](expected_output/example_run.txt) を参照。

注意:
- SQLite の外部キーは、接続ごとに `PRAGMA foreign_keys = ON` を実行しないと**無効**（既定）。`get_connection()` で必ず有効にしている。
- 同一注文の二重登録では、人に承認を求めたあとで Tool が拒否する（承認の前に重複を判定する仕組みは、この章では作らない）。

## 7. 次章で変更される点

- `sales` が1 Table（注文・顧客・商品が1行に混在）で、Data Model が弱い
- 次章：`../ch09-multitable/`
