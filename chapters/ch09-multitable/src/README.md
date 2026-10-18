# ch09 src — ソースコードの案内

この章のソースコード（完全版のファイルと、本文の説明用の抜粋）の一覧です。

- 「完全ファイル」: 完成した、または主要なコード全体。
- 「抜粋」(`snippets/`): 本文で説明する部分コード。説明の順に番号を振っている。単体では動かない場合がある。
- `snippets/` は比較用の抜粋で、完全版とは内容が異なる場合があり、単体での動作は未検証。**検証済みの完全版は `agent_service.py` / `main.py` / `scripts/normalize_sales_db.py`（本章の本文で使う版）**。

| ファイル | 種別 | 対応する節 | 行数 |
|---|---|---|---|
| `snippets/01_L101.sql` | 抜粋 | 今回のゴール | 3 |
| `scripts/normalize_sales_db.py` | 完全ファイル | まず3 Tableへ分割する | 131 |
| `snippets/02_L360.py` | 抜粋 | Joinを「許可リスト」で管理する | 16 |
| `snippets/03_L394.py` | 抜粋 | Step 1：Table一覧を確認する | 28 |
| `snippets/04_L431.py` | 抜粋 | Step 2：Schemaを確認する | 29 |
| `snippets/05_L469.py` | 抜粋 | Step 3：Join候補を提案する | 40 |
| `snippets/06_L524.py` | 抜粋 | Step 4：Join Keyを検証する | 18 |
| `snippets/07_L547.py` | 抜粋 | Step 4：Join Keyを検証する | 39 |
| `snippets/08_L638.py` | 抜粋 | Step 5：Join Previewを出す | 46 |
| `snippets/09_L693.py` | 抜粋 | Step 6：安全な集計Toolを用意する | 27 |
| `snippets/10_L725.py` | 抜粋 | Step 6：安全な集計Toolを用意する | 27 |
| `snippets/11_L761.py` | 抜粋 | `resolve_join()`を作る | 28 |
| `snippets/12_L796.py` | 抜粋 | Agentへ与えるTool | 29 |
