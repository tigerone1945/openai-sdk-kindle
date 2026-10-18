output "alb_dns_name" {
  value = aws_lb.main.dns_name
}

output "ecr_api_url" {
  value = aws_ecr_repository.api.repository_url
}

output "ecr_ui_url" {
  value = aws_ecr_repository.ui.repository_url
}

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "migrate_task_definition" {
  value = aws_ecs_task_definition.migrate.family
}

# run-task(マイグレーション)に渡す、タスクの置き場所
output "task_subnet_ids" {
  value = local.task_subnet_ids
}

output "task_security_group_id" {
  value = aws_security_group.app.id
}

output "task_assign_public_ip" {
  value = local.task_assign_public_ip
}

output "db_endpoint" {
  value = aws_db_instance.postgres.address
}

output "db_master_secret_arn" {
  value = aws_db_instance.postgres.master_user_secret[0].secret_arn
}

output "alarm_topic_arn" {
  value = aws_sns_topic.alarms.arn
}
