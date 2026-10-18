#!/usr/bin/env bash
# マイグレーション用タスクを 1 回だけ実行し、終わるのを待って、終了コードとログを出す。
set -euo pipefail

cd "$(dirname "$0")/../src/terraform"
OUT() { terraform output -raw "$1"; }
CLUSTER="$(OUT cluster_name)"
SUBNETS="$(terraform output -json task_subnet_ids | python3 -c 'import sys,json;print(",".join(json.load(sys.stdin)))')"
PUBLIC_IP="$([[ "$(OUT task_assign_public_ip)" == "true" ]] && echo ENABLED || echo DISABLED)"

TASK_ARN="$(aws ecs run-task --cluster "$CLUSTER" --launch-type FARGATE \
  --task-definition "$(OUT migrate_task_definition)" \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$(OUT task_security_group_id)],assignPublicIp=$PUBLIC_IP}" \
  --query 'tasks[0].taskArn' --output text)"
echo "起動: $TASK_ARN"

aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ARN"
EXIT_CODE="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK_ARN" --query 'tasks[0].containers[0].exitCode' --output text)"
echo "終了コード: $EXIT_CODE"
aws logs tail "/ecs/${PROJECT_NAME:-ai-agent-practice}/migrate" --since 15m --format short || true
exit "${EXIT_CODE/None/1}"
