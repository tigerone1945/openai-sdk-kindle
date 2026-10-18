# 第12章 Docker / Docker Composeで実行環境を固定する

> 状態：**実行確認済み**（2026-10-12、Docker 29.8.2 / Docker Compose v5.5.1 / Docker Desktop(aarch64) / Python 3.13.16（コンテナ内）、モデルはSDKデフォルト）。モデル名・LLMの挙動・計測値は更新で変わるため、出版直前に再確認する。

## 1. Kindle対応章

本書の第12章「Docker / Docker Composeで実行環境を固定する」に対応します。この章の完全なソースコードは `src/` にあります（ファイルの案内は `src/README.md`）。実行手順は、この README に記載しています。

## 2. この章で追加するCapability

- API と UI を別のコンテナにする（`Dockerfile.api` / `Dockerfile.ui`）。アプリのコードは第11章と**同一**で、コンテナ化のために変更していない
- 状態（DB・会話履歴・監査ログ・承認待ち）は名前付きボリューム `app-data` にだけ置く。イメージには業務データを入れない
- 初期化ジョブ `init`（`init_db.py`）：初回だけ `sales.db` を作り、2回目以降は何もしない
- 起動順序：`init`（成功）→ `api`（healthy）→ `ui`
- 秘密（`OPENAI_API_KEY`）は実行時に API コンテナにだけ渡す。イメージには入れない
- 堅牢化：一般ユーザー、読み取り専用のルートFS、権限の全削除、ポートは `127.0.0.1` のみ
- イメージごとの依存グループ（`pyproject.toml` の `[dependency-groups]`）

## 3. 前章からの変更点

- 前章（第11章）で残った課題：実行環境がローカル依存
- アプリのコード（`agent_service.py` `service.py` `api/` `ui/`）は変更なし。Dockerfile が `chapters/ch11-fastapi/src/` から取り込む
- 追加: `Dockerfile.api` `Dockerfile.ui`、許可リスト式の `*.dockerignore`、`compose.yaml`、`init_db.py`
- 本章の完全版（`Dockerfile.*` / `compose.yaml`）と `src/snippets/` の抜粋との違い: ①複数行の `CMD [` はビルドが構文エラーになるため1行に ②`COPY data ./data` をやめた（会話履歴・DB がイメージに入るため）③`.dockerignore` を除外方式から許可リスト方式へ ④`depends_on` を `service_healthy` に ⑤ポートを `127.0.0.1` に限定 ⑥一般ユーザーで実行 ⑦ベースイメージをダイジェストで固定 ⑧イメージごとに依存グループを分けた ⑨`compose.yaml` の `.env` の読み込み先（Composeは compose.yaml のあるフォルダーの `.env` を読む）を `--env-file` で指定
- 第9章の取り込みスクリプトを再利用（`init_db.py` が、実行のたびにDBを作り直す挙動を「無ければ作る」に包む）

## 4. この章で確認するFile

- `src/Dockerfile.api` / `src/Dockerfile.ui`
- `src/Dockerfile.api.dockerignore` / `src/Dockerfile.ui.dockerignore`（`*` から始めて、必要なものだけ許可する）
- `src/compose.yaml`
- `src/init_db.py`
- `scripts/scan_image_for_secret.py`（イメージの層・履歴・設定に、秘密が入っていないかを検査）
- `tests/test_container_config.py`（Docker なし・LLM なしの静的検査。33件）
- `src/snippets/`（比較用の抜粋で、完全版とは内容が異なる。本文では使わない）

## 5. 実行方法

リポジトリのルートで実行する（Setup は第1章 README を参照）。**Docker Desktop（または Docker Engine）が起動している必要がある。**

```bash
# .env に OPENAI_API_KEY を設定しておく（.env.example を参照）
docker compose -f chapters/ch12-docker/src/compose.yaml --env-file .env up --build
```

- 画面: http://127.0.0.1:8501 / API: http://127.0.0.1:8000（`/docs` に Swagger UI）
- 止める（状態は残る）: `docker compose -f chapters/ch12-docker/src/compose.yaml --env-file .env down`
- 状態も消す: 上に `-v` を付ける（`app-data` ボリュームごと消える。レビュー依頼と会話履歴も消える）
- ログ: `... logs -f api`

ビルドだけなら `OPENAI_API_KEY=dummy docker compose -f chapters/ch12-docker/src/compose.yaml build`（`:?` の検査は、ビルドでも評価される）。

テスト・検査：

```bash
uv run --with pytest pytest chapters/ch12-docker/tests -q                 # 設定の静的検査（Docker不要）
SECRET_TO_FIND="$(grep ^OPENAI_API_KEY= .env | cut -d= -f2-)" \
  uv run python chapters/ch12-docker/scripts/scan_image_for_secret.py ai-sales-agent-api:local   # 秘密の混入
```

## 6. Expected Result

- テスト：33 passed
- 起動：`init` が終了コード0で終わり、`api` が healthy になってから `ui` が起動する（約10秒）
- コンテナを削除して作り直しても、レビュー依頼と会話履歴が残る（`init` は「既にあります」と言って何もしない）
- API キーは、イメージの層・履歴・設定のどこにもない。UI コンテナにも渡らない
- LAN の IP からは API に繋がらない（`127.0.0.1` のみ）
- 実行例・計測値は [expected_output/example_run.txt](expected_output/example_run.txt) を参照

注意:
- **認証・認可はない**（第11章のまま）。ポートを `127.0.0.1` に限定しているのはそのため。`0.0.0.0` に変えて公開してはいけない
- `docker inspect` や `docker compose config` は、API キーを表示する（実行時の環境変数だから）。画面共有・ログに貼らない
- 初回のビルドは約4分（依存のダウンロード）。2回目以降、コードだけの変更なら数秒
- ベースイメージはダイジェスト固定。更新するときは、ダイジェストと Python の版を意識して変える
- SQLite のファイルを、複数のコンテナで同時に開くのは避ける（この構成では、`init` と `api` は順番に動く）

## 7. 次章で変更される点

- SQLite のままでは、`api` を1台から増やせず、DB の中で権限を分けることもできない（「同時に書けない」ことが実際に問題になるかは、次章で測る）
- 次章：`../ch13-postgresql/`
