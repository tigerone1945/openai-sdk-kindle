locals {
  db_secret_arn = aws_db_instance.postgres.master_user_secret[0].secret_arn

  # api と migrate が共有する、DB の接続先(秘密ではない)
  db_environment = [
    { name = "DB_BACKEND", value = "postgres" },
    { name = "DB_HOST", value = aws_db_instance.postgres.address },
    { name = "DB_NAME", value = aws_db_instance.postgres.db_name },
  ]

  # 値はタスクの起動時に ECS が Secrets Manager から取り出す。タスク定義にも state にも、値は入らない
  # (RDS が管理するシークレットは JSON。":キー::" でそのキーだけを取り出す)
  app_db_secrets = [
    { name = "DB_RO_PASSWORD", valueFrom = aws_secretsmanager_secret.db_ro_password.arn },
    { name = "DB_RW_PASSWORD", valueFrom = aws_secretsmanager_secret.db_rw_password.arn },
  ]

  hardening = {
    readonlyRootFilesystem = true
    linuxParameters = {
      initProcessEnabled = true
      capabilities       = { add = [], drop = ["ALL"] }
    }
  }

  # ECS が受け取った定義に自分で補う既定値。書いておかないと、plan のたびに「差分あり」になり、
  # タスク定義が毎回作り直される(実測。本文参照)
  ecs_defaults = {
    systemControls = []
    volumesFrom    = []
  }

  python_healthcheck = {
    interval    = 15
    timeout     = 5
    retries     = 3
    startPeriod = 30
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project_name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.api_task.arn

  # Apple Silicon で作ったイメージ(arm64)と同じ。Fargate の Graviton は x86 より約 20% 安い
  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  # 読み取り専用のルートの上で、書いてよい場所。タスクが消えると中身も消える。
  # data は v1(第13章のコード。状態をファイルに置く)の実験のときだけ。v2 は状態を DB に置くので不要
  dynamic "volume" {
    for_each = var.mount_data_volume ? ["data"] : []
    content {
      name                = volume.value
      configure_at_launch = false
    }
  }
  volume {
    name                = "tmp"
    configure_at_launch = false
  }

  container_definitions = jsonencode([merge(local.hardening, local.ecs_defaults, {
    name         = "api"
    image        = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
    essential    = true
    stopTimeout  = 30
    portMappings = [{ containerPort = 8000, hostPort = 8000, protocol = "tcp" }]
    environment  = local.db_environment
    secrets = concat(local.app_db_secrets, [
      { name = "OPENAI_API_KEY", valueFrom = aws_secretsmanager_secret.openai_api_key.arn },
    ])
    mountPoints = concat(
      var.mount_data_volume ? [{ sourceVolume = "data", containerPath = "/app/data", readOnly = false }] : [],
      [{ sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }],
    )
    healthCheck = merge(local.python_healthcheck, {
      command = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
    })
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "api"
      }
    }
  })])
}

resource "aws_ecs_task_definition" "ui" {
  family                   = "${var.project_name}-ui"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ui_task.arn

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  volume {
    name                = "tmp"
    configure_at_launch = false
  }

  container_definitions = jsonencode([merge(local.hardening, local.ecs_defaults, {
    name         = "ui"
    image        = "${aws_ecr_repository.ui.repository_url}:${var.ui_image_tag}"
    essential    = true
    stopTimeout  = 30
    portMappings = [{ containerPort = 8501, hostPort = 8501, protocol = "tcp" }]
    environment = [
      { name = "API_URL", value = "http://api.${aws_service_discovery_private_dns_namespace.main.name}:8000" },
    ]
    mountPoints = [{ sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }]
    healthCheck = merge(local.python_healthcheck, {
      command = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=2)"]
    })
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.ui.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "ui"
      }
    }
  })])
}

# 1 回だけ実行するタスク(サービスにはしない): DB のマイグレーションと、デモデータの投入。
# 非公開サブネットの RDS に届くのは、VPC の中のタスクだけだから、同じイメージ・同じネットワークで動かす。
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.project_name}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  volume {
    name                = "tmp"
    configure_at_launch = false
  }

  container_definitions = jsonencode([merge(local.hardening, local.ecs_defaults, {
    name      = "migrate"
    image     = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
    essential = true
    command   = ["python", "migrate.py"]
    environment = concat(local.db_environment, [
      { name = "SEED_DEMO_DATA", value = "true" },
    ])
    # DDL ができる管理者(RDS のマスターユーザー)の資格情報は、このタスクにだけ渡す。api には渡さない
    secrets = concat(local.app_db_secrets, [
      { name = "DB_OWNER_USER", valueFrom = "${local.db_secret_arn}:username::" },
      { name = "DB_OWNER_PASSWORD", valueFrom = "${local.db_secret_arn}:password::" },
    ])
    mountPoints = [{ sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.migrate.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "migrate"
      }
    }
  })])
}

resource "aws_ecs_service" "api" {
  name            = "${var.project_name}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  health_check_grace_period_seconds = 60
  wait_for_steady_state             = true

  # 起動に失敗し続ける版は、自動で前の版に戻す
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = local.task_subnet_ids
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = local.task_assign_public_ip
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  service_registries {
    registry_arn = aws_service_discovery_service.api.arn
  }

  depends_on = [aws_lb_listener_rule.api]
}

resource "aws_ecs_service" "ui" {
  name            = "${var.project_name}-ui"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.ui.arn
  desired_count   = var.ui_desired_count
  launch_type     = "FARGATE"

  health_check_grace_period_seconds = 60
  wait_for_steady_state             = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = local.task_subnet_ids
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = local.task_assign_public_ip
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.ui.arn
    container_name   = "ui"
    container_port   = 8501
  }

  depends_on = [aws_lb_listener.http]
}
