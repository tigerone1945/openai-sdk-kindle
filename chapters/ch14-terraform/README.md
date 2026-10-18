# 第14章 TerraformでAWS基盤をコード化する

> 状態:**実機で検証済み**(2026-10-13、東京リージョン)。記録は `expected_output/example_run.txt`。

## 1. この章で追加するCapability

- AWS の土台(VPC・サブネット・セキュリティグループ・ECR・ECS クラスタ・RDS・ログ)を、Terraform で作る
- 変更を `fmt → validate → plan → 人の確認 → apply` で通す
- state を S3 に置く。RDS のパスワードを Terraform が持たない
- NAT Gateway を変数で切り替える(既定は無し)

## 2. 前章からの変更点

- VPC 1 つだけの最小構成(サブネット・RDS 用の設定なし、パスワードは変数)に対して、本章は 2 AZ のサブネット、3 つのセキュリティグループ(ALB → app → db)、DB サブネットグループ、暗号化、`manage_master_user_password` を追加した
- アプリのコードは変更なし(第15章でデプロイする)

## 3. ファイル

- `src/terraform/*.tf`(`backend.tf` は S3。`backend.hcl.example` を `backend.hcl` にして使う)
- `scripts/create_state_bucket.sh`(state 用バケットを、あなたのAWSアカウントに作る。バケット名を指定し、1 回だけ、`--yes` で実行)
- `tests/`(22 件)

## 4. 実行方法

以下は、リポジトリを GitHub から Clone した直後の状態から、そのまま実行できるように書いています。コマンドは、**リポジトリの直下(`openai-sdk-kindle/`)から**始めます。

### 事前準備(第14〜16章に共通)

- **課金に関する注意:** この章の手順は、**あなた自身のAWSアカウントに、有料のリソースを作ります**。作ったままにすると、課金が続きます。`plan` で内容と費用の目安を確認し、終わったら必ず `destroy` してください。本書の金額は、著者の環境での概算で、請求額を保証しません
- **ツール:** Terraform 1.10 以上(`backend.tf` が S3 のロックファイルを使うため)、AWS CLI v2
- **AWS CLI の認証:** `aws configure`(または `aws configure sso` と `aws sso login`)で、あなたのAWSアカウントに認証しておく。次で、操作先のアカウントを確認する(表示されるアカウントIDは、他人に見せず、Gitにも書かない)

```bash
aws sts get-caller-identity
export AWS_REGION=ap-northeast-1     # 本書のTerraformの既定の地域(東京)
```

### 手順1 state 用の S3 バケットを作る(1 回だけ)

Terraform の state(AWS上に何があるかの記録)は、S3 に置きます。**バケットは、あなた自身のAWSアカウントに、あなたが新しく作ります。**著者のバケットは使えません。

- **バケット名は、あなたが決めます。**S3 のバケット名は、全AWSで一意です。小文字・数字・ハイフン・ドット、3〜63 文字(例:`yamada-tfstate-20261018`)。使用済みの名前だと、作成に失敗するので、別の名前にします
- 第14・15・16章で、**同じバケットを使えます。**state は、章ごとに別のキー(`ch14/…`、`ch15/…`、`ch16/…`)で保存されるので、混ざりません

```bash
cd chapters/ch14-terraform
export TF_STATE_BUCKET="<あなたが決めたバケット名>"
scripts/create_state_bucket.sh "$TF_STATE_BUCKET"          # 内容の確認だけ。何も作らない
scripts/create_state_bucket.sh "$TF_STATE_BUCKET" --yes    # 作成する(1 回だけ)
```

作られるバケットは、バージョニング有効、パブリックアクセスを全ブロック、SSE-S3 暗号化、TLS 以外を拒否、です。バケット名を省略すると、`openai-sdk-kindle-tfstate-<あなたのアカウントID>` になります(確認の表示で、名前を見てから `--yes` を付けます)。

### 手順2 backend.hcl を作る

`backend.hcl.example` をもとに、`backend.hcl`(あなたの環境の値。**Git に入れません**)を作ります。

```bash
cd src/terraform
sed "s|REPLACE_WITH_YOUR_STATE_BUCKET_NAME|${TF_STATE_BUCKET}|" backend.hcl.example > backend.hcl
cat backend.hcl        # bucket が、手順1のバケット名になっているか確認する
```

| 章 | state のキー |
|---|---|
| 第14章 | `ch14/terraform.tfstate` |
| 第15章 | `ch15/terraform.tfstate` |
| 第16章 | `ch16/terraform.tfstate` |

### 手順3 初期化・検証・plan・apply

```bash
terraform init -backend-config=backend.hcl
terraform fmt -recursive && terraform validate
terraform plan -out=my.tfplan                  # ← 人の確認。費用が出るのは RDS(約 $0.03/時)
terraform apply my.tfplan
```

`plan` の出力を読み、作られるリソースと、自分のアカウントであることを確認してから `apply` します。NAT を作るには `-var enable_nat_gateway=true`(+約 $0.062/時)。

### 手順4 終わったら必ず destroy

```bash
terraform plan -destroy -out=d.tfplan && terraform apply d.tfplan
```

**`destroy` で消えるのは、この章の Terraform が作ったリソースです。手順1の state 用 S3 バケットは消えません**(Terraform の管理の外で作ったため)。バケットは、少額ですが、残っている間は課金されます。第14〜16章をすべて終え、`destroy` が済んだ後に、不要なら、AWS マネジメントコンソールで、バケットを「空にする」(バージョンも含めて削除される)→「削除」の順に消してください。**`destroy` の前に消すと、state を失い、リソースを Terraform で消せなくなります。**

state を手元のファイルで始める場合は `backend.tf` を外して `terraform init` し、後から `backend.tf` を戻して `terraform init -migrate-state -backend-config=backend.hcl`。

## 5. テスト

```bash
uv run --with pytest --with pytest-asyncio pytest chapters/ch14-terraform/tests -q   # 22 passed(AWS 認証情報なしでは 9 passed)
```

## 6. 次章で変更される点

インフラはあるが、アプリは動いていない。第15章で、イメージを ECR に push し、ECS/Fargate で動かす。
