# 第16章 運用できる状態にする(Secrets・Logs・Metrics・Evaluation)

> 状態:**実機で検証済み**(2026-10-13、東京リージョン)。記録は `expected_output/example_run.txt`。

## 1. この章で追加するCapability

- 構造化ログ(質問・回答は残さない)と、ログから作るメトリクス、7 つのアラーム、ダッシュボード
- 質問・回答を、OpenAI 側にも残さない方針(`store=False`。Tracing の設定とは別)
- 評価(Evaluation): 正解データとの照合・範囲外の拒否・承認への到達を、同じケースを繰り返して測る
- Production Readiness チェックリストを、稼働中の AWS に対して判定するスクリプト
- 障害の演習: DB のパスワードを間違えたとき、何が検知でき、何が検知できないか

## 2. 前章からの変更点

- `src/observability.py` / `src/server.py` / `src/service.py` / `src/Dockerfile.api`: ログとプライバシー方針
- `src/evaluation/`: 評価
- `src/terraform/monitoring.tf`: 監視
- `scripts/check_readiness.py` / `scripts/incident_drill.py`: チェックリストと障害の演習

## 3. 実行方法

評価を手元で流す(OpenAI を呼ぶ):
```bash
export DB_OWNER_PASSWORD=$(openssl rand -hex 12) DB_RO_PASSWORD=$(openssl rand -hex 12) DB_RW_PASSWORD=$(openssl rand -hex 12)
docker compose -f chapters/ch16-observability-evaluation/src/compose.yaml --env-file .env up -d --build --wait
cd chapters/ch16-observability-evaluation/src
python -m evaluation.runner --url http://127.0.0.1:8000 --runs 3 --report /tmp/report.json
python -m evaluation.runner --url http://127.0.0.1:8000 --runs 20 --cases overall-001   # 不安定さは、回数を増やして測る
```

AWS(第15章と同じ流れ。作って、測って、消す):

**事前に必要なもの:**第14章の「事前準備」(課金の注意・Terraform 1.10 以上・AWS CLI の認証)、**state 用の S3 バケット**(第14章の手順1。あなた自身のアカウントに作る。名前は、あなたが決めたもの)。バケットは、第14・15・16章で共通に使えます。state のキーは、章ごとに別です(この章は `ch16/terraform.tfstate`)。

**前の章の環境が残っていないこと:**第14章・第15章で作った環境が残っていると、同じ名前(`ai-agent-practice`)のリソースと衝突する可能性があります。前の章は、先に `destroy` してください。`destroy` しても、state 用バケットは残ります(次の章でも使います)。

**OpenAI のキー:**`./put_secrets.sh` は、リポジトリ直下の `.env` の `OPENAI_API_KEY` を読みます。`.env` は自分で作り、**Git に入れないでください**。

以下は、リポジトリの直下から実行します。`terraform.tfvars` は、第15章と同様に、自分の IP だけを許可する設定です(あなたの環境の値。Git に入れない)。

```bash
export TF_STATE_BUCKET="<第14章で作った、あなたの state 用バケット名>"
cd chapters/ch16-observability-evaluation/src/terraform
sed "s|REPLACE_WITH_YOUR_STATE_BUCKET_NAME|${TF_STATE_BUCKET}|" backend.hcl.example > backend.hcl   # Git に入れない
echo "alb_ingress_cidrs = [\"$(curl -s https://checkip.amazonaws.com)/32\"]" > terraform.tfvars
terraform init -backend-config=backend.hcl
terraform fmt -recursive && terraform validate
terraform plan -out=a.tfplan   # ← 人の確認(課金される)
terraform apply a.tfplan
cd ../../scripts && ./put_secrets.sh && ./deploy_images.sh chapters/ch16-observability-evaluation/src/Dockerfile.api v4 api \
  && ./deploy_images.sh chapters/ch16-observability-evaluation/src/Dockerfile.api v1 ui && ./run_migrate.sh
cd ../src/terraform && terraform apply -var api_image_tag=v4 -var api_desired_count=2 -var ui_desired_count=1   # 現在のSourceは v4(DB障害を503に翻訳)。variables.tf の既定値 v3 は、記録(v3の実験)とテストの固定値として残してある
python3 ../../scripts/check_readiness.py                     # チェックリスト
python3 ../../scripts/incident_drill.py $(terraform output -raw alb_dns_name)   # 障害の演習(自分の環境だけで)
# 終わったら、必ず terraform plan -destroy -out=d.tfplan && terraform apply d.tfplan
```

`destroy` で消えるのは、この章で作ったリソースです。**state 用の S3 バケットは消えません**(第14〜16章をすべて終えた後の消し方は、第14章の手順4)。

## 4. テスト

```bash
uv run --with pytest --with pytest-asyncio pytest chapters/ch16-observability-evaluation/tests -q          # 件数は環境により異なる。2026-10-13の記録は 73 passed, 4 skipped。現在の収集件数は78(非live 74、live 4)。terraform・AWS認証情報がないと、Terraformのテスト7件がスキップされる
RUN_LIVE_TESTS=1 uv run --with pytest --with pytest-asyncio pytest chapters/ch16-observability-evaluation/tests/test_trace_privacy_live.py   # OpenAI を呼ぶ(数円)
```

## 5. 次章で変更される点

本書は、この第16章で完結します(続きの章はありません)。第16章は、AWS 上で動かし、観測し、評価する、最後の章です。

Agent 固有の機能(記憶・Tool 接続・認証・観測・評価)は、アプリケーション側で自前管理しています。これを、マネージドな基盤に任せる選択肢(AWS の Amazon Bedrock AgentCore など)は、本書の範囲外の発展先です。本リポジトリには含まれません。

## テストの検査(ミューテーション)

コードを 1 か所ずつ壊して、テストが失敗することを確かめる。

```bash
uv run --with pytest --with pytest-asyncio python chapters/ch16-observability-evaluation/scripts/mutation_check.py
```
