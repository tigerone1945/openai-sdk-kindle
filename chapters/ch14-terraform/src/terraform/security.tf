# 通信の向きを 1 本の鎖にする: Internet → ALB → app(ECS) → db(RDS)
resource "aws_security_group" "alb" {
  name        = "${var.project_name}-alb"
  description = "ALB"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project_name}-alb" }
}

resource "aws_security_group" "app" {
  name        = "${var.project_name}-app"
  description = "ECS tasks (api, ui)"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project_name}-app" }
}

resource "aws_security_group" "db" {
  name        = "${var.project_name}-db"
  description = "RDS PostgreSQL"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project_name}-db" }
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  for_each = toset(var.alb_ingress_cidrs)

  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = each.value
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "app_from_alb" {
  for_each = { api = 8000, ui = 8501 }

  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = each.value
  to_port                      = each.value
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "db_from_app" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

# ALB から app への通信先を絞る。app は ALB が転送する 2 ポートにだけ出られる
resource "aws_vpc_security_group_egress_rule" "alb_to_app" {
  for_each = { api = 8000, ui = 8501 }

  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = each.value
  to_port                      = each.value
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "app_to_db" {
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.db.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

# モデル API(OpenAI)・ECR・CloudWatch への HTTPS。NAT が無ければ実際には出られない
resource "aws_vpc_security_group_egress_rule" "app_https" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}
