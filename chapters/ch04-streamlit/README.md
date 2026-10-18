# 第4章 StreamlitでAIデータ分析AgentのWeb画面を作る

> 状態：**実行確認済み**（2026-10-02、Python 3.13.8 / openai-agents 0.22.3 / pandas 3.0.6 / streamlit 1.64.0、モデルはSDKデフォルトの `gpt-5.6-luna`）。モデル名はSDKの更新で変わるため、出版直前に再確認する。

## 1. Kindle対応章

第4章「StreamlitでAIデータ分析AgentのWeb画面を作る」（Zenn第4回：`source/zenn/zenn04.md`）

## 2. この章で追加するCapability

- StreamlitでAIデータ分析AgentのWeb画面を作る
- ブラウザから質問を入力し、分析結果を3つの区画（分析概要・重要な発見・次のアクション）で表示する
- Agent の能力は増えない。追加するのは人が使うための層（Human Interface Layer）

## 3. 前章からの変更点

- 前章（第3章）で残った課題：結果は型付けされたが、入口がCLIしかない
- 差分: Agent・Tool・Schema を `agent_service.py` へ移し、`run_sales_agent()` を切り出し
- 追加: `app.py`（Streamlit の画面）、依存 `streamlit`

## 4. この章で確認するFile

- `src/agent_service.py`
- `src/app.py`

## 5. 実行方法

リポジトリのルートで実行する（Setup は第1章 README を参照。`uv sync` で `streamlit` も入る）。

```bash
uv run streamlit run chapters/ch04-streamlit/src/app.py
```

表示された URL（通常は http://localhost:8501）をブラウザで開く。

## 6. Expected Result

- 画面が表示され、質問入力欄と「分析する」ボタンがある
- 質問を入力して「分析する」を押すと、「分析概要」「重要な発見」「次のアクション」の3区画が表示される
- 金額が、第2章の正解（pandas で直接集計した値）と一致する
- 入力が空のとき、「分析したい内容を入力してください。」の警告が出て、Agent は呼ばれない

文面は実行ごとに変わる。実行例は [expected_output/example_run.txt](expected_output/example_run.txt)、画面は `../../05_figures/ch04_screen_*.png` を参照。

## 7. 次章で変更される点

- 会話状態と実行履歴がない
- 次章：`../ch05-sessions-tracing/`
