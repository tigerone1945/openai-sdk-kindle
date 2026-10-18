# 第9章 Multi-tableとJoin Validationを実装する

> 状態：**実行確認済み**（2026-10-12、Python 3.13.8 / openai-agents 0.22.3 / pandas 3.0.6、モデルはSDKデフォルト）。モデル名とLLMの挙動は更新で変わるため、出版直前に再確認する。

## 1. Kindle対応章

本書の第9章「Multi-tableとJoin Validationを実装する」に対応します。この章の完全なソースコードは `src/` にあります（ファイルの案内は `src/README.md`）。実行手順は、この README に記載しています。

## 2. この章で追加するCapability

- `sales` を `orders` / `customers` / `products` の3 Tableに正規化（主キー・外部キー・CHECK）
- Join Governance：`ALLOWED_JOINS` に許可したJoinだけ実行
- Join Validation：`list_tables` → `inspect_table` → `suggest_join` → `validate_join` → `preview_join`
- Many-to-Many を `validate_join` が NG とし、`preview_join` も実行しない
- 読み取りは読み取り専用接続（`mode=ro`）。書き込みは登録Toolだけ
- 切り口の許可リスト（`DIMENSIONS`）：Semantic Layer の最小形
- `get_sales_by_customer_type`

## 3. 前章からの変更点

- 前章（第8章）で残った課題：1 TableではData Modelが弱い
- 差分: `sales` を3 Tableに分割。第8章の集計Toolは、Interface（名前・説明・出力形式）を保ったまま、JOINを使うSQLに差し替え
- `review_requests` の外部キーが `orders(order_id)` を参照
- 本章の完全版（`agent_service.py`）と `src/snippets/` の抜粋との違い: ①`preview_join` の `SELECT *` を列名に接頭辞を付けて衝突回避 ②`validate_join` がMany-to-Manyを判定し、`preview_join` が検証を必ず通す ③識別子は許可リスト（`require_table`）を通してからSQLに埋め込む ④`suggest_join` と `resolve_join` の重複を統合

## 4. この章で確認するFile

- `src/scripts/normalize_sales_db.py`（正規化。属性が食い違えば失敗する）
- `src/agent_service.py`（完全版）
- `src/main.py`（第8章と同じCLI）
- `tests/test_join_governance.py`（LLMなしの検証。21件）
- `src/snippets/`（比較用の抜粋で、完全版とは内容が異なる。本文では使わない）

## 5. 実行方法

リポジトリのルートで実行する（Setup は第1章 README を参照）。

```bash
uv run python chapters/ch09-multitable/src/scripts/normalize_sales_db.py
uv run python chapters/ch09-multitable/src/main.py
uv run --with pytest pytest chapters/ch09-multitable/tests -q
```

`data/sales.db` は第8章と**同じパス**で、取り込みのたびに作り直される（`sales` Tableは消え、3 Tableになる）。第8章のコードを動かすときは、第8章の取り込みを再実行する。

## 6. Expected Result

- 取り込み：customers 10件 / products 12件 / orders 300件。売上合計は 28,298,695円（第1章と同じ）
- テスト：21 passed
- Agent：単純な質問は集計Toolを直接使い、Joinの確認を求める質問では `list_tables → suggest_join → validate_join → preview_join` の順に進む
- 許可されていないJoin、クロス集計、任意SQLは「できない」と答える

文面・Toolの順序は実行ごとに変わる。実行例は [expected_output/example_run.txt](expected_output/example_run.txt) を参照。

## 7. 次章で変更される点

- 1つのAgentが、集計・Join確認・レビュー依頼の登録まで、11個のToolを抱えている
- 次章：`../ch10-multi-agent/`
