# 第10章 Multi-Agentで分析責務を分割する

> 状態：**実行確認済み**（2026-10-12、Python 3.13.8 / openai-agents 0.22.3 / pandas 3.0.6、モデルはSDKデフォルト）。モデル名とLLMの挙動・計測値は更新で変わるため、出版直前に再確認する。

## 1. Kindle対応章

本書の第10章「Multi-Agentで分析責務を分割する」に対応します。この章の完全なソースコードは `src/` にあります（ファイルの案内は `src/README.md`）。実行手順は、この README に記載しています。

## 2. この章で追加するCapability

- Manager Pattern：`Agent.as_tool()` で専門Agentを呼ぶ（会話の主導権はManagerが持つ）
- 専門Agent 3つ：Data Quality / Sales Analyst / Business Insight
- 責務の境界：状態を変更するTool（承認が必要）とGuardrailはManagerだけが持つ。専門Agentは読み取りだけ
- 専門Agentは会話履歴を知らない（Context Boundary）。Managerが必要な前提を文章で渡す

## 3. 前章からの変更点

- 前章（第9章）で残った課題：1 Agentの責務が広すぎる（11個のTool）
- 差分: `agent_service.py` の下半分（Agent定義）だけが変わる。Data Access・Join Governance・Toolは第9章と同一
- Manager 4 Tool / Data Quality 5 / Sales Analyst 5 / Business Insight 0
- 本章の完全版（`agent_service.py`）と `src/snippets/` の抜粋との違い: ①Sales Analystに `get_review_orders` を追加（第8章で追加済みのTool）、`get_sales_by_product_category` は第9章で `get_sales_by_category` に統合済み ②Instructionsに「専門Agentは会話を知らない」「できないことはそのまま伝える」を追加 ③承認が必要なToolはManagerに置く

## 4. この章で確認するFile

- `src/agent_service.py`（完全版。Data Accessは第9章の複製）
- `src/main.py`（第9章と同じCLI）
- `tests/test_agent_boundaries.py`（LLMなしの検証。責務の境界と、第9章とのData Accessの乖離検出。9件）
- `src/snippets/`（比較用の抜粋で、完全版とは内容が異なる。本文では使わない）
- 取り込みスクリプトは第9章のものを使う（`../ch09-multitable/src/scripts/normalize_sales_db.py`）

## 5. 実行方法

リポジトリのルートで実行する（Setup は第1章 README を参照）。

```bash
uv run python chapters/ch09-multitable/src/scripts/normalize_sales_db.py
uv run python chapters/ch10-multi-agent/src/main.py
uv run --with pytest pytest chapters/ch10-multi-agent/tests -q
```

## 6. Expected Result

- テスト：9 passed
- Agent：集計の質問は `analyze_sales_data` を、Joinの確認は `check_data_quality` を、意味づけは `create_business_insight` を呼ぶ
- 単一Agent（第9章）との比較は、本文のVerificationを参照（時間・モデル呼び出し回数・トークン数）

文面・Toolの呼び出し順は実行ごとに変わる。実行例は [expected_output/example_run.txt](expected_output/example_run.txt) を参照。

注意:
- 専門Agentに承認が必要なToolを持たせると、承認の中断が入れ子になる。この章では扱わず、Managerに置く
- Data Accessは章ごとに複製している（技術的負債）。`tests` が第9章との乖離を検出する。第11章以降で `shared/` に切り出すかを判断する

## 7. 次章で変更される点

- AgentがUI（またはCLI）と同一プロセス・密結合で、Serviceとして切り出せていない
- 次章：`../ch11-fastapi/`
