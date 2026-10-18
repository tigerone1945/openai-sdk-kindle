# ch11 src — ソースコードの案内

この章のソースコード（完全版のファイルと、本文の説明用の抜粋）の一覧です。

- 「完全ファイル」: 完成した、または主要なコード全体。
- 「抜粋」(`snippets/`): 本文で説明する部分コード。説明の順に番号を振っている。単体では動かない場合がある。
- `snippets/` は比較用の抜粋で、完全版とは内容が異なる場合があり、単体での動作は未検証。**検証済みの完全版は `agent_service.py` / `service.py` / `api/main.py` / `ui/app.py`（本章の本文で使う版）**。

| ファイル | 種別 | 対応する節 | 行数 |
|---|---|---|---|
| `snippets/01_L153.py` | 抜粋 | Request / Response Schemaを作る | 13 |
| `api/main.py` | 完全ファイル | FastAPI Applicationを作る | 64 |
| `snippets/02_L248.py` | 抜粋 | `run_sales_agent_async()`を作る | 21 |
| `snippets/03_L300.json` | 抜粋 | Health Check | 3 |
| `snippets/04_L325.json` | 抜粋 | Analysis APIを呼ぶ | 9 |
| `ui/app.py` | 完全ファイル | StreamlitからHTTPで呼ぶ | 26 |
| `snippets/05_L452.json` | 抜粋 | API Contractという考え方 | 4 |
| `snippets/06_L463.json` | 抜粋 | API Contractという考え方 | 6 |
| `snippets/07_L508.py` | 抜粋 | Error Handling | 4 |
