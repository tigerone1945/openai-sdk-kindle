#!/usr/bin/env bash
# テスト用のPostgreSQLを、手元に起動する(127.0.0.1:55432 のみ。テストが終わったら停止する)。
#
#   source chapters/ch13-postgresql/scripts/start_test_postgres.sh
#   uv run --with pytest --with pytest-asyncio pytest chapters/ch13-postgresql/tests -q
#   docker rm -f ch13-test-postgres        # 後片付け
#
# 注意: 役割(agent_ro / agent_rw)は、PostgreSQLのクラスタ全体で共通。テストは、役割のパスワードを書き換える。
#       そのため、開発用のPostgreSQLとは別の、専用のコンテナで実行すること(これは、そのためのスクリプト)。
set -euo pipefail

NAME=ch13-test-postgres
IMAGE='postgres:17@sha256:d74eeac9a635390a49bc21bd49fccd973de707e2a53a76ac49b552b8712ec46f'
PASSWORD=test-only-password   # 127.0.0.1 にしか公開しない、使い捨てのコンテナ

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" -e POSTGRES_PASSWORD="$PASSWORD" -p 127.0.0.1:55432:5432 "$IMAGE" >/dev/null

for _ in $(seq 1 60); do
  docker exec "$NAME" pg_isready -U postgres >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$NAME" pg_isready -U postgres >/dev/null

export TEST_PG_URL="postgresql+psycopg://postgres:${PASSWORD}@127.0.0.1:55432/postgres"
echo "PostgreSQL を起動しました。TEST_PG_URL を設定しました。"
