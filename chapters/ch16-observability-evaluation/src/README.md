# ch16 src

- `observability.py`: 構造化ログ(`log_event`)、リクエストの記録(`install`)、質問・回答を OpenAI 側に保存させない方針(`apply_privacy_policy`)
- `service.py`: 第15章の `service.py` に、実行結果の構造化ログを足したもの
- `server.py`: 本番の入口(`uvicorn server:app`)。第13章の API に、リクエストの記録を足す。API のコードは変えない
- `Dockerfile.api` / `compose.yaml`: イメージと、評価を手元で流すための最小の構成(db + migrate + api)
- `evaluation/`: 評価(`cases.json`、正解データ、判定、実行)
- `terraform/`: 第15章の構成 + `monitoring.tf`(アラーム・ログからのメトリクス・ダッシュボード・SNS)
- ほかのファイル(`agent_service.py`、`db.py`、`api/` など)は、Dockerfile が第13・15章のものを取り込む
