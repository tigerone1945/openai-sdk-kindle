#!/usr/bin/env bash
# イメージを arm64 で build し、ECR へ push する。使い方: deploy_images.sh <api-の-Dockerfile> <タグ> [api|ui|all]
#   v1(第13章のコードそのまま): deploy_images.sh chapters/ch13-postgresql/src/Dockerfile.api v1
#   v2(第15章で状態を RDS へ):   deploy_images.sh chapters/ch15-aws-deploy/src/Dockerfile.api v2
set -euo pipefail

API_DOCKERFILE="$1"; TAG="$2"; WHAT="${3:-all}"
REGION="${AWS_REGION:-ap-northeast-1}"
PROJECT="${PROJECT_NAME:-ai-agent-practice}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
cd "$(dirname "$0")/../../.."

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null

push() {  # <名前> <Dockerfile>
  # Fargate は ARM64 で動かす(タスク定義の runtime_platform と合わせる)
  docker build --progress=quiet --platform linux/arm64 -f "$2" -t "${REGISTRY}/${PROJECT}-$1:${TAG}" . >/dev/null
  # push は、回線次第でタイムアウトする(実測で 2 回中 2 回、最後の層で失敗)。
  # docker のメッセージではなく、ECR に実際に入ったかで成否を決める
  for attempt in 1 2 3; do
    docker push "${REGISTRY}/${PROJECT}-$1:${TAG}" >/dev/null 2>&1 || true
    if aws ecr describe-images --repository-name "${PROJECT}-$1" --image-ids "imageTag=${TAG}" >/dev/null 2>&1; then
      echo "push 済み: ${PROJECT}-$1:${TAG} (試行 ${attempt} 回目)"; return 0
    fi
  done
  echo "push に失敗: ${PROJECT}-$1:${TAG}" >&2; return 1
}

[[ "$WHAT" == "api" || "$WHAT" == "all" ]] && push api "$API_DOCKERFILE"
[[ "$WHAT" == "ui"  || "$WHAT" == "all" ]] && push ui chapters/ch12-docker/src/Dockerfile.ui

true
