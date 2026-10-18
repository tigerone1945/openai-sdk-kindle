# 第1章 CSV売上データでAgentとRunnerを理解する

> 状態：**実行確認済み**（2026-10-02 再確認、Python 3.13.8 / openai-agents 0.22.3 / pandas 3.0.6、モデルはSDKデフォルトの `gpt-5.6-luna`）。モデル名はSDKの更新で変わるため、出版直前に再確認する。

## 1. Kindle対応章

本書の第1章「CSV売上データでAgentとRunnerを理解する」に対応します。この章の完全なソースコードは `src/` にあります（ファイルの案内は `src/README.md`）。実行手順は、この README に記載しています。

## 2. この章で追加するCapability

- CSV売上データでAgentとRunnerを理解する
- データの概要（Dataset Profile）から、最初に確認すべき分析観点を3つ提案する（実データの集計はまだしない）

## 3. 前章からの変更点

- 前章なし（第1章。なぜ最小Agentから始めるかは本文を参照）
- 差分なし（全コードが新規）

## 4. この章で確認するFile

- `src/main.py`
- `src/snippets/`（本文の説明用の抜粋 2 件。一覧は `src/README.md`）

## 5. 実行方法

以下はすべてリポジトリのルートで実行する。

```bash
# Setup（初回のみ）
uv sync
cp .env.example .env   # OPENAI_API_KEY を設定する

# Run
uv run python chapters/ch01-agent-runner/src/main.py
```

CSVは `data/raw/ai_agent_practice_sales.csv` を読む。

### CSVの文字コード

このCSVは **BOM付きUTF-8**（Excelで日本語を文字化けさせずに開くため）。`pandas.read_csv` はBOMを自動で除去するので、本書のコードでは意識しなくてよい。標準ライブラリの `csv` モジュールなど別の方法で読む場合は、`encoding="utf-8-sig"` を指定する。

## 6. Expected Result

- 終了コードが 0
- 分析観点が3つ出力される
- 売上金額の合計など、実際の数値は出力されない

出力の文面は実行ごとに変わる。実行例は [expected_output/example_run.txt](expected_output/example_run.txt) を参照。

## 7. 次章で変更される点

- Agentは実データを計算できない
- 次章：`../ch02-function-tools/`
