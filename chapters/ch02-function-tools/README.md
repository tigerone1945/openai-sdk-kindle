# 第2章 Function ToolsとpandasでCSVを分析する

> 状態：**実行確認済み**（2026-10-02、Python 3.13.8 / openai-agents 0.22.3 / pandas 3.0.6、モデルはSDKデフォルトの `gpt-5.6-luna`）。モデル名はSDKの更新で変わるため、出版直前に再確認する。

## 1. Kindle対応章

第2章「Function ToolsとpandasでCSVを分析する」（Zenn第2回：`source/zenn/zenn02.md`）

## 2. この章で追加するCapability

- Function ToolsとpandasでCSVを分析する
- Agentが Function Tool を呼び、pandas で売上を集計できる（`get_sales_summary` / `get_sales_by_category` / `get_sales_by_region`）
- 「売上 = `sales_amount`」という業務ルールを Tool 側に固定する

## 3. 前章からの変更点

- 前章（第1章）で残った課題：Agentは実データを計算できない
- 差分: Function Tool 3つの追加、Agent への `tools=[...]` 指定、Instructions に「Toolの結果を使う」を追記
- Runner の使い方は第1章と同じ（Agent の能力だけが増える）

## 4. この章で確認するFile

- `src/main.py`
- `src/snippets/`（記事の抜粋 5 件。一覧は `src/README.md`）

## 5. 実行方法

リポジトリのルートで実行する（Setup は第1章 README を参照）。

```bash
uv run python chapters/ch02-function-tools/src/main.py
```

質問は `main.py` 末尾の `Runner.run_sync(...)` の第2引数で変える。

## 6. Expected Result

- 終了コードが 0
- 出力の金額が、pandas で直接集計した値と一致する（下表）
- 質問を変えると別の Tool が使われる

| 集計 | 正解 |
|---|---|
| 売上合計 | 28,298,695円（300件、キャンセル14件） |
| IT機器 / オフィス家具 / 周辺機器 / ストレージ | 11,651,680 / 11,329,340 / 2,879,995 / 2,437,680円 |
| 東北 / 関西 / 九州 / 関東 / 中部 | 8,439,765 / 8,373,825 / 4,980,410 / 3,268,525 / 3,236,170円 |

文面は実行ごとに変わる。実行例は [expected_output/example_run.txt](expected_output/example_run.txt) を参照。

## 7. 次章で変更される点

- 自然文出力ではApplicationが扱いにくい
- 次章：`../ch03-structured-output/`
