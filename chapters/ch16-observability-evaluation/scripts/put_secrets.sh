#!/usr/bin/env bash
# Secrets Manager の「入れ物」(Terraform が作った)に、値を入れる。値は Terraform にも state にも渡さない。
#   - OpenAI のキー: リポジトリ直下の .env から読む(画面にも出さない)
#   - DB の ro / rw のパスワード: ここで乱数を作って入れる(人は知らなくてよい)
set -euo pipefail

PROJECT="${PROJECT_NAME:-ai-agent-practice}"
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

OPENAI_KEY="$(grep -E '^OPENAI_API_KEY=' "$ROOT/.env" | head -1 | cut -d= -f2- | tr -d '"'"'")"
[[ -n "$OPENAI_KEY" ]] || { echo ".env に OPENAI_API_KEY がありません" >&2; exit 1; }

put() { aws secretsmanager put-secret-value --secret-id "$PROJECT/$1" --secret-string "$2" --query VersionId --output text >/dev/null && echo "入れた: $PROJECT/$1"; }

put openai-api-key "$OPENAI_KEY"
put db-ro-password "$(openssl rand -hex 24)"
put db-rw-password "$(openssl rand -hex 24)"
