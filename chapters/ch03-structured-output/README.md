# 第3章 Structured Outputで分析結果を安定させる

> 状態：**実行確認済み**（2026-10-02、Python 3.13.8 / openai-agents 0.22.3 / pandas 3.0.6、モデルはSDKデフォルトの `gpt-5.6-luna`）。モデル名はSDKの更新で変わるため、出版直前に再確認する。

## 1. Kindle対応章

本書の第3章「Structured Outputで分析結果を安定させる」に対応します。この章の完全なソースコードは `src/` にあります（ファイルの案内は `src/README.md`）。実行手順は、この README に記載しています。

## 2. この章で追加するCapability

- Structured Outputで分析結果を安定させる
- Agentの最終回答を、自然文ではなく型付きのオブジェクト（`SalesAnalysisResult`、5項目）で返す
- `output_type` と `final_output` / `model_dump()` の使い方

## 3. 前章からの変更点

- 前章（第2章）で残った課題：自然文出力ではApplicationが扱いにくい
- 差分: `SalesAnalysisResult`（Pydantic）の追加、Agentへの `output_type` 指定、Instructionsに各項目の指示を追記
- Tool・Runnerの使い方は第2章と同じ

## 4. この章で確認するFile

- `src/main.py`
- `src/snippets/`（本文の説明用の抜粋 4 件。一覧は `src/README.md`）

## 5. 実行方法

リポジトリのルートで実行する（Setup は第1章 README を参照）。

```bash
uv run python chapters/ch03-structured-output/src/main.py
```

## 6. Expected Result

- 終了コードが 0
- `final_output` が `SalesAnalysisResult` で、5項目（`question` / `analysis_type` / `result_summary` / `key_findings` / `next_action`）がそろう
- 金額が、第2章の正解（pandas で直接集計した値）と一致する
- 質問を変えると `analysis_type` が変わる

文面は実行ごとに変わる。実行例は [expected_output/example_run.txt](expected_output/example_run.txt) を参照。

注意: `key_findings` の中には、Agent 自身が計算した値（上位2カテゴリの合計・割合）が含まれることがある。Schema は項目の有無と型を保証するが、中身の正しさは保証しない。

## 7. 次章で変更される点

- 結果は型付けされたが、入口がCLIしかない（人が使える画面がない）
- 次章：`../ch04-streamlit/`
