resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-db"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "postgres" {
  identifier = "${var.project_name}-postgres"

  engine         = "postgres"
  engine_version = "16"

  instance_class        = "db.t4g.micro"
  allocated_storage     = 20
  max_allocated_storage = 100
  storage_encrypted     = true

  db_name  = "ai_agent"
  username = var.db_username

  # パスワードは Terraform が持たない。RDS が生成し、Secrets Manager で管理する
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  backup_retention_period    = 1
  auto_minor_version_upgrade = true
  deletion_protection        = var.db_deletion_protection

  # 学習用: destroy でデータごと消す。本番では false にして、最終スナップショットを取る
  skip_final_snapshot = true
}
