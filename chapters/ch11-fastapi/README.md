# 第11章 FastAPIでAIエージェントをAPI化する

> 状態：**実行確認済み**（2026-10-12、Python 3.13.8 / openai-agents 0.22.3 / fastapi 0.143.0 / uvicorn 0.54.0 / httpx 0.28.1、モデルはSDKデフォルト）。モデル名とLLMの挙動・計測値は更新で変わるため、出版直前に再確認する。

## 1. Kindle対応章

本書の第11章「FastAPIでAIエージェントをAPI化する」に対応します。この章の完全なソースコードは `src/` にあります（ファイルの案内は `src/README.md`）。実行手順は、この README に記載しています。

## 2. この章で追加するCapability

- Agent を HTTP API として切り離す（`POST /analysis`、`GET /health`）
- 契約（Request / Response / Error）を先に定義する（Contract-first）。OpenAPI（`/docs`）に反映される
- Error Model：`{"error": {"code", "message", "request_id"}}`。内部の例外は返さない
- 承認（HITL）を HTTP で受け渡す：`approval_required` → `POST /approvals/{id}`
- `analysis_type` を `Literal`（候補限定）に変更（第3章からの引き継ぎ）
- 集計Toolの出力に「合計」の行を追加（LLMに足し算をさせない。第10章のコピーからの唯一のData Accessの変更）
- 時間制限（既定120秒）、`request_id`、非同期（`async def` + `Runner.run`）

## 3. 前章からの変更点

- 前章（第10章）で残った課題：Agent の実行が同一プロセスの Python 関数のまま
- `agent_service.py` は第10章の複製。変更は `AnalysisType`（Literal）とその指示のみ
- 追加: `service.py`（Agent Service。HTTPを知らない）、`api/main.py`（API）、`ui/app.py`（Streamlit。HTTPだけで通信）
- 承認待ち（`RunState`）はサーバー側の `data/approvals.db` に保管。クライアントには `approval_id` だけを返す
- `shared/` への切り出しは行わない：方針書（GitHubフォルダー作成方針 §6）に従い、章ごとの完成スナップショットを保つ。重複の解消は最終版 `app/` で行う

## 4. この章で確認するFile

- `src/api/main.py`（契約・エラー対応・エンドポイント）
- `src/service.py`（Agent Service・承認待ちの保管）
- `src/agent_service.py`（第10章の複製 + Literal）
- `src/ui/app.py`（Streamlit。Agent を import しない）
- `tests/test_api_contract.py`（API。LLMなし。25件）
- `tests/test_ui.py`（画面。APIを差し替え。LLMなし。8件）
- `tests/test_data_layer.py`（集計の出力の「合計」行がToolの側にあることの確認。LLMなし。3件）
- `src/snippets/`（比較用の抜粋で、完全版とは内容が異なる。本文では使わない）。`src/api/main.py` と `src/ui/app.py` が本章の完成版

## 5. 実行方法

リポジトリのルートで実行する（Setup は第1章 README を参照）。

```bash
uv run python chapters/ch09-multitable/src/scripts/normalize_sales_db.py   # 第9章の取り込みを共用
uv run uvicorn api.main:app --app-dir chapters/ch11-fastapi/src --port 8000
# 別のターミナルで
uv run streamlit run chapters/ch11-fastapi/src/ui/app.py
```

API を直接試す：

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/analysis -H "Content-Type: application/json" \
  -d '{"question": "カテゴリ別の売上を分析してください", "session_id": "demo-session"}'
```

`http://127.0.0.1:8000/docs`（Swagger UI）から試すこともできる。

テスト：

```bash
uv run --with pytest --with pytest-asyncio pytest chapters/ch11-fastapi/tests -q
```

## 6. Expected Result

- テスト：36 passed（API 25 + 画面 8 + 合計 3）
- `POST /analysis`：`status` が `completed`（`result` あり）か `approval_required`（`approval` あり）
- 承認：`POST /approvals/{approval_id}` に `{"decision": "approve" | "reject"}`。同じ `approval_id` は一度しか使えない（2回目は 404）
- 範囲外の質問は 422 `out_of_scope`。不正な入力は 422 `validation_error`
- 実行例は [expected_output/example_run.txt](expected_output/example_run.txt) を参照

注意:
- **認証・認可はない。** `approval_id` を知っていれば誰でも承認できる。認証・認可（誰が承認できるかの管理）の実装は、本書の対象範囲外です
- 承認の再開に失敗すると、その `approval_id` は使えなくなる（二重実行を避けるため）。もう一度質問し直す
- `data/approvals.db` は実行時に生成され、`.gitignore`（`*.db`）で除外される
- 古いパスで作られた `.venv` では、`uvicorn` / `streamlit` の起動スクリプトが動かないことがある。`uv run python -m uvicorn ...` で起動するか、`.venv` を作り直す

## 7. 次章で変更される点

- 実行環境がローカルに依存している（Python・依存・DBファイルのパス）
- 次章：`../ch12-docker/`
