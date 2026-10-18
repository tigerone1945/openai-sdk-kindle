# OpenAI Agents SDK Kindle — Reader Source

Kindle書籍『OpenAI Agents SDKで育てるAIエージェント』の、読者向けサンプルソースコードです。

- [1. このリポジトリについて](#1-このリポジトリについて)
- [2. 必要な環境](#2-必要な環境)
- [3. リポジトリの取得](#3-リポジトリの取得)
- [4. Python環境の構築](#4-python環境の構築)
- [5. 環境変数の設定](#5-環境変数の設定)
- [6. 章ごとのSource Snapshot](#6-章ごとのsource-snapshot)
- [7. 実行とテスト](#7-実行とテスト)
- [8. DockerとAWSを使う章](#8-dockerとawsを使う章)
- [9. セキュリティ上の注意](#9-セキュリティ上の注意)
- [10. ソースコードのバージョン](#10-ソースコードのバージョン)
- [11. ライセンス・利用条件](#11-ライセンス利用条件)

## 1. このリポジトリについて

- 書籍の**第1〜16章**に対応する、完全なSource Codeを提供します。本書は第16章で完結しており、続きの章はありません。
- 書籍の本文では、設計判断と重要な差分を説明します。**GitHubでは、動かせる完全なコードを提供します。**本文のコードは要点だけを抜き出したものなので、全文はここで確認してください。
- 売上データ分析AIエージェントを、1章ずつ育てていきます。各章のフォルダーは、**その章を終えた時点の姿(Source Snapshot)**です。
- 書籍の制作用の原稿や編集資料、本書の範囲外の教材は、収録していません。

## 2. 必要な環境

| 必要なもの | 用途 |
|---|---|
| Git | リポジトリの取得 |
| Python 3.12以上(`pyproject.toml` の `requires-python = ">=3.12"`) | 全章。著者の確認は、各章READMEの「状態」に書いたバージョンです |
| [uv](https://docs.astral.sh/uv/) | Pythonの依存関係の管理と実行 |
| OpenAI APIキー | LLM(Agent)を実行する章(利用料がかかります) |
| Docker / Docker Compose | 第12・13章(コンテナで動かす)。第15・16章でイメージを作るときにも使います |
| Terraform 1.10以上 | 第14〜16章 |
| AWS CLI(v2)と、AWSアカウント | 第14〜16章(**実際にAWSで試す場合は、料金がかかります**) |

読むだけ、または第1〜11章を試すだけなら、Docker・Terraform・AWSは不要です。

## 3. リポジトリの取得

```bash
git clone https://github.com/tigerone1945/openai-sdk-kindle.git
cd openai-sdk-kindle
```

以降のコマンドは、**特に断りがなければ、このリポジトリのルート(`openai-sdk-kindle/`)から実行**します。

## 4. Python環境の構築

```bash
uv sync
```

`pyproject.toml` と `uv.lock` にもとづいて、**全章分の依存関係**をまとめて入れます(章ごとに環境を分けません)。以降は、`uv run ...` で実行します。

## 5. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を開き、値を設定します。

| 変数 | 必要な章 | 内容 |
|---|---|---|
| `OPENAI_API_KEY` | LLMを実行する章 | あなたのOpenAI APIキー |
| `DB_OWNER_PASSWORD`、`DB_RO_PASSWORD`、`DB_RW_PASSWORD` | 第13章(PostgreSQL。詳細は第13章README) | それぞれ**別の値**にする。例:`openssl rand -base64 18` |

- `.env` は、Gitの管理から除外されています(`.gitignore`)。**`.env` をGitHubへPushしないでください。**
- 値は、自分の環境で決めます。この README やリポジトリに、実際の値は含まれません。

## 6. 章ごとのSource Snapshot

各章のフォルダーに、`README.md`(実行手順)、`src/`(Source Code)、`tests/`(テスト)、`scripts/`、`expected_output/`(過去の実行記録)があります。章が進むと、前の章のファイルを引き継ぎます(例:第16章のコンテナは、第15章・第13章のファイルも使って作られます)。

| 章 | フォルダー | 主な内容 |
|---|---|---|
| 第1章 | [`ch01-agent-runner`](chapters/ch01-agent-runner/README.md) | CSV売上データで、AgentとRunnerを理解する |
| 第2章 | [`ch02-function-tools`](chapters/ch02-function-tools/README.md) | Function Toolsとpandasで、CSVを分析する |
| 第3章 | [`ch03-structured-output`](chapters/ch03-structured-output/README.md) | Structured Outputで、分析結果を安定させる |
| 第4章 | [`ch04-streamlit`](chapters/ch04-streamlit/README.md) | Streamlitで、Web画面を作る |
| 第5章 | [`ch05-sessions-tracing`](chapters/ch05-sessions-tracing/README.md) | SessionsとTracingで、会話と実行履歴を管理する |
| 第6章 | [`ch06-guardrails`](chapters/ch06-guardrails/README.md) | Guardrailsで、安全境界を作る |
| 第7章 | [`ch07-hitl`](chapters/ch07-hitl/README.md) | Human-in-the-Loopで、人の判断を組み込む |
| 第8章 | [`ch08-sqlite`](chapters/ch08-sqlite/README.md) | CSVからSQLiteへ移行する |
| 第9章 | [`ch09-multitable`](chapters/ch09-multitable/README.md) | Multi-tableとJoin Validation |
| 第10章 | [`ch10-multi-agent`](chapters/ch10-multi-agent/README.md) | Multi-Agentで、分析の責務を分割する |
| 第11章 | [`ch11-fastapi`](chapters/ch11-fastapi/README.md) | FastAPIで、AgentをAPI化する |
| 第12章 | [`ch12-docker`](chapters/ch12-docker/README.md) | Docker / Docker Composeで、実行環境を固定する |
| 第13章 | [`ch13-postgresql`](chapters/ch13-postgresql/README.md) | SQLiteからPostgreSQLへ移行する |
| 第14章 | [`ch14-terraform`](chapters/ch14-terraform/README.md) | TerraformでAWSの土台をコード化する |
| 第15章 | [`ch15-aws-deploy`](chapters/ch15-aws-deploy/README.md) | ECR・ECS/Fargate・ALB・RDSへデプロイする |
| 第16章 | [`ch16-observability-evaluation`](chapters/ch16-observability-evaluation/README.md) | Secrets・Logs・Metrics・Evaluationで、運用できる状態にする |

共通の売上データは、`data/raw/ai_agent_practice_sales.csv` です(学習用のデモデータです)。

## 7. 実行とテスト

- **実行手順は、各章の `README.md` を参照してください。**
- **ルートから実行するコマンド**(`uv run python chapters/...`)と、**章のフォルダーに移って実行するコマンド**(第14〜16章のTerraformなど)があります。各章のREADMEに、作業ディレクトリが書いてあります。

テストの例(章ごとに実行します。章をまとめて実行すると、同名のテスト用モジュールが衝突することがあります):

```bash
uv run --with pytest --with pytest-asyncio pytest chapters/ch11-fastapi/tests -q
```

- 第1〜7章には、`tests/` のテストはありません。
- **実行条件が足りないテストは、スキップされます。**例:PostgreSQLがない(`TEST_PG_URL` を設定していない)、`terraform` やAWS認証情報がない、OpenAIを呼ぶテスト(`RUN_LIVE_TESTS=1` が必要)。スキップは失敗ではありません。件数は、環境で変わります。
- **`expected_output/` は、過去の検証記録**です(2026年10月に、著者の環境で取りました)。**現在の実行を保証するものではありません。**LLMの出力は、実行のたびに変わります。検証当時のフォルダー名・リポジトリ名などが、記録に残っていることがあります。

## 8. DockerとAWSを使う章

| 章 | 必要なもの |
|---|---|
| 第12章 | Docker / Docker Compose |
| 第13章 | Docker / Docker Compose(PostgreSQLを、コンテナで動かす) |
| 第14章 | Terraform 1.10以上、AWS CLI、AWSアカウント |
| 第15章 | 第14章に加えて、Docker(イメージのビルド)、OpenAI APIキー |
| 第16章 | 第15章と同じ |

**第14〜16章は、あなた自身のAWSアカウントに、有料のリソースを作ります。作ったままにすると、課金が続きます。**

- **Terraform Stateを置くS3バケットは、読者自身が作ります。**バケット名は、あなたが決めます(全AWSで一意)。作り方は、[第14章のREADME](chapters/ch14-terraform/README.md)にあります。第14・15・16章で、同じバケットを使えます。stateのキーは、章ごとに別です。
- 各章の `src/terraform/backend.hcl.example` から、**自分の `backend.hcl` を作ります**(`backend.hcl` はGitに入れません)。
- `terraform plan` の出力を読み、**作られるリソースと費用の目安を確認**してから、`apply` します。
- 検証が終わったら、**必ず `destroy`** します。前の章の環境が残っていると、次の章と名前が衝突する可能性があります。
- **State用のS3バケットは、`terraform destroy` では削除されません。**不要になったら、すべての章の `destroy` が済んでから、自分で削除します(手順は第14章のREADME)。
- バケット名の指定:`scripts/create_state_bucket.sh` は、第1引数、または環境変数 `STATE_BUCKET` でバケット名を受け取ります。各章のREADMEでは、シェル変数 `TF_STATE_BUCKET` に名前を入れ、スクリプトの引数と `backend.hcl` の作成の両方に使っています。

## 9. セキュリティ上の注意

- **APIキー:** コードやREADMEに書かず、`.env` に置きます。画面共有・ログ・スクリーンショットに出さないでください。`docker inspect` や `docker compose config` は、渡した値を表示することがあります。
- **AWS認証情報:** Gitに入れません。操作先のAWSアカウントは、`aws sts get-caller-identity` で確認してから操作します。
- **公開してはいけないファイル:** `.env`、`backend.hcl`、`terraform.tfvars`、`terraform.tfstate`、`*.tfplan`、`.terraform/`、秘密鍵、`*.db`(会話履歴・業務データ)。`.gitignore` で除外していますが、`git status` で、Pushするものを確認してください。
- **教材環境と商用本番環境は違います。**第16章までで到達するのは、学習用の基準線(Generic AWS Production Baseline)です。**商用の本番環境に必要な、すべての安全要件を満たすものではありません。**認証・認可、ネットワークの分離、監査、可用性、運用体制などは、利用する組織とサービスの要件に合わせて、別に設計・確認してください。

## 10. ソースコードのバージョン

現時点では、出版用のGit Tagは作成していません。**`main` ブランチの内容が、公開済みの内容です。**出版用のTagは、書籍の公開に合わせて、後で用意します。

最新の設定やSDKの仕様は、書籍の検証時点と異なることがあります。

### ソースコードの依存関係について

`pyproject.toml` および `uv.lock` には、制作時のプロジェクト名 `agentcore-kindle` と、本書では使用しない発展的な依存パッケージが含まれています。

本リポジトリの学習対象は第1〜16章です。各章で必要な環境と実行方法については、対応するREADMEを参照してください。

また、`expected_output/` は過去の検証記録です。記録中のバケット名や旧名称は、現在の推奨設定ではありません。

## 11. ライセンス・利用条件

本リポジトリのサンプルコードは、[OpenAI Agents SDK Kindle サンプルコード利用条件](LICENSE.md) に従って利用できます。学習・検証目的の実行や改変は許可されていますが、教材一式の再配布・再販売には制限があります。詳細は利用条件を確認してください。**本利用条件はOSI承認のオープンソースライセンスではありません。**
