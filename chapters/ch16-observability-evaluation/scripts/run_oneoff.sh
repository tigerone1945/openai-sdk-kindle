#!/usr/bin/env bash
# migrate 用のタスク(DB の管理者資格情報つき)で、Python の 1 行を実行し、標準出力を表示する。
#   run_oneoff.sh "print(1+1)"
# 非公開サブネットの RDS には、VPC の中のタスクからしか届かない。確認のための「のぞき窓」。
set -euo pipefail
cd "$(dirname "$0")/../src/terraform"
OUT() { terraform output -raw "$1"; }
CLUSTER="$(OUT cluster_name)"
SUBNETS="$(terraform output -json task_subnet_ids | python3 -c 'import sys,json;print(",".join(json.load(sys.stdin)))')"
PUBLIC_IP="$([[ "$(OUT task_assign_public_ip)" == "true" ]] && echo ENABLED || echo DISABLED)"
OVERRIDES="$(python3 -c 'import json,sys;print(json.dumps({"containerOverrides":[{"name":"migrate","command":["python","-c",sys.argv[1]]}]}))' "$1")"

TASK_ARN="$(aws ecs run-task --cluster "$CLUSTER" --launch-type FARGATE --task-definition "$(OUT migrate_task_definition)" \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$(OUT task_security_group_id)],assignPublicIp=$PUBLIC_IP}" \
  --overrides "$OVERRIDES" --query 'tasks[0].taskArn' --output text)"
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ARN"
TASK_ID="${TASK_ARN##*/}"
sleep 3
aws logs get-log-events --log-group-name "/ecs/${PROJECT_NAME:-ai-agent-practice}/migrate" --log-stream-name "migrate/migrate/$TASK_ID" --query 'events[].message' --output text
