output "vpc_id" {
  value = aws_vpc.main.id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "ecr_api_url" {
  value = aws_ecr_repository.api.repository_url
}

output "ecr_ui_url" {
  value = aws_ecr_repository.ui.repository_url
}

output "db_endpoint" {
  value = aws_db_instance.postgres.address
}

# パスワードそのものではなく、それが入っているシークレットの ARN
output "db_master_secret_arn" {
  value = aws_db_instance.postgres.master_user_secret[0].secret_arn
}
