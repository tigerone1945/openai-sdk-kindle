resource "aws_lb" "main" {
  name               = "${var.project_name}-alb"
  load_balancer_type = "application"
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]

  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "api" {
  name                 = "${var.project_name}-api"
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 30

  # ヘルスチェックは /health(プロセスが生きているか)。/ready(DB まで見る)にしない:
  # DB が止まっただけで全タスクが外され、ALB の 503 になって、アプリの 503 が見えなくなる
  health_check {
    path     = "/health"
    matcher  = "200"
    interval = 15
    timeout  = 5
  }
}

resource "aws_lb_target_group" "ui" {
  name                 = "${var.project_name}-ui"
  port                 = 8501
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 30

  health_check {
    path     = "/_stcore/health"
    matcher  = "200"
    interval = 15
    timeout  = 5
  }
}

# HTTP のみ(HTTPS にはドメインと証明書が要る。本書では扱わない)。入口は ALB の SG が絞る
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ui.arn
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = ["/health", "/ready", "/analysis", "/approvals/*"]
    }
  }
}
