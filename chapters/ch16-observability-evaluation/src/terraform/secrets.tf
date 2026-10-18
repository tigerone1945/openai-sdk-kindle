# 「入れ物」だけを作る。値は Terraform に渡さない(state に入るため)。
# 値は scripts/put_secrets.sh が、AWS CLI で入れる。
# recovery_window_in_days = 0: destroy で即削除する(学習用。待機期間があると、同じ名前で作り直せない)
resource "aws_secretsmanager_secret" "openai_api_key" {
  name                    = "${var.project_name}/openai-api-key"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "db_ro_password" {
  name                    = "${var.project_name}/db-ro-password"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "db_rw_password" {
  name                    = "${var.project_name}/db-rw-password"
  recovery_window_in_days = 0
}
