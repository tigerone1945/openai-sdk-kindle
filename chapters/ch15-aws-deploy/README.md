# 第15章 AWS へデプロイする(ECR・ECS/Fargate・ALB・RDS)

> 状態:**実機で検証済み**(2026-10-13、東京リージョン)。記録は `expected_output/example_run.txt`。

## 1. この章で追加するCapability

- 第14章の土台に、ALB・ECS サービス(api・ui)・IAM・Secrets Manager・サービス検出を足し、アプリを AWS で動かす
- シークレットを、Terraform にも state にもイメージにも入れずに、タスクへ渡す
- 状態(会話履歴・承認待ち)を RDS に置き、タスクが何台でも・入れ替わっても動くようにする(v2)
- DB のマイグレーションを、VPC の中の 1 回限りのタスクとして実行する

## 2. 前章からの変更点

- `src/terraform/`: 第14章の構成 + `alb.tf` `iam.tf` `secrets.tf` `service_discovery.tf` `tasks.tf`(ECS)。標準は「非公開サブネット + NAT」。`enable_nat_gateway=false` で、NAT なし(公開サブネット + 公開 IP、入口は ALB の SG だけ)
- `src/service.py`: 状態の保存先を `DB_BACKEND` で選ぶ(postgres: RDS / sqlite: 手元のファイル)
- `src/agent_service.py`: 第13章のコピー。違いは `write_audit_log` だけ(`AUDIT_LOG_DEST=stdout` で標準出力へ)
- `src/migrations/0003_state.sql`: 承認待ち・会話履歴の表(`agent_rw` だけが使える)
- `src/Dockerfile.api`: 上の差し替え。`/app/data` を持たない
- `src/experiments/Dockerfile.api.v1b`: v1 の実験用(`VOLUME` を 1 行足しただけ)
- 依存: `sqlalchemy[asyncio]`(`greenlet`)を追加

## 3. 実行の流れ(1 回の検証 = 作って、測って、消す)

**事前に必要なもの:**第14章の「事前準備」(課金の注意・Terraform 1.10 以上・AWS CLI の認証)、**state 用の S3 バケット**(第14章の手順1。あなた自身のアカウントに作る。名前は、あなたが決めたもの)。バケットは、第14・15・16章で共通に使えます。state のキーは、章ごとに別です(この章は `ch15/terraform.tfstate`)。

**前の章の環境が残っていないこと:**第14章・第15章で作った環境が残っていると、同じ名前(`ai-agent-practice`)のリソースと衝突する可能性があります。前の章は、先に `destroy` してください。`destroy` しても、state 用バケットは残ります(次の章でも使います)。

**OpenAI のキー:**`./put_secrets.sh` は、リポジトリ直下の `.env` の `OPENAI_API_KEY` を読みます。`.env` は自分で作り、**Git に入れないでください**。

以下は、リポジトリの直下から実行します。

```bash
export TF_STATE_BUCKET="<第14章で作った、あなたの state 用バケット名>"
cd chapters/ch15-aws-deploy/src/terraform
sed "s|REPLACE_WITH_YOUR_STATE_BUCKET_NAME|${TF_STATE_BUCKET}|" backend.hcl.example > backend.hcl   # Git に入れない
echo "alb_ingress_cidrs = [\"$(curl -s https://checkip.amazonaws.com)/32\"]" > terraform.tfvars   # 自分の IP だけ(あなたの環境の値。Git に入れない)
terraform init -backend-config=backend.hcl
terraform fmt -recursive && terraform validate
terraform plan -out=a.tfplan          # ← 人の確認(NAT・ALB・RDS が課金。約 $0.17/時)
terraform apply a.tfplan              # 土台。台数は 0
cd ../../scripts
./put_secrets.sh                      # OpenAI キーは .env から。DB の ro/rw は乱数
./deploy_images.sh chapters/ch15-aws-deploy/src/Dockerfile.api v2   # arm64 で build → ECR
./run_migrate.sh                      # RDS へのマイグレーション(VPC の中のタスクで 1 回)
cd ../src/terraform
terraform plan -var api_desired_count=2 -var ui_desired_count=1 -var api_image_tag=v2 -out=b.tfplan
terraform apply b.tfplan
curl http://$(terraform output -raw alb_dns_name)/health
python3 ../../scripts/measure_statelessness.py $(terraform output -raw alb_dns_name) 10
# 終わったら、必ず
terraform plan -destroy -var api_image_tag=v2 -out=d.tfplan && terraform apply d.tfplan
```

`destroy` で消えるのは、この章で作ったリソースです。**state 用の S3 バケットは消えません**(消し方は、第14章の手順4)。

新しいバージョンを出すときの順序: ①イメージを push(新しいタグ) → ②マイグレーション用のタスク定義だけ更新(`-target=aws_ecs_task_definition.migrate`)→ ③ `run_migrate.sh` → ④ サービスを更新。新しいコードが新しい表を前提にするため、③ が ④ より先。

## 4. テスト

```bash
source chapters/ch13-postgresql/scripts/start_test_postgres.sh
uv run --with pytest --with pytest-asyncio pytest chapters/ch15-aws-deploy/tests -q   # 35 passed
```

AWS 認証情報なしでは、plan を使う検査 10 件が飛ばされる。`TEST_PG_URL` なしでは、DB の検査 9 件が飛ばされる。

## 5. 次章で変更される点

動いているが、運用できない。シークレットの権限の絞り込み、ログ・メトリクス・アラーム、評価(第16章)。

## テストの検査(ミューテーション)

コードを 1 か所ずつ壊して、テストが失敗することを確かめる。

```bash
TEST_PG_URL=... uv run --with pytest --with pytest-asyncio python chapters/ch15-aws-deploy/scripts/mutation_check.py
```
