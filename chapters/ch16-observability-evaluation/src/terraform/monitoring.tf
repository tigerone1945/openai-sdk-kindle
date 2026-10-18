# 監視は 2 種類に分ける(第16章)。
#   Runtime Health: サーバーが動いているか(5xx・正常なホスト数・CPU・メモリ・遅延)  ← ここ
#   Agent Quality : 答えが正しいか(評価 = evaluation/)                          ← アラームでは捕まえられない
# 通知先は SNS トピックまで。購読者(メールなど)は付けない(発報は CloudWatch の API で確認する)。

resource "aws_sns_topic" "alarms" {
  name              = "${var.project_name}-alarms"
  kms_master_key_id = "alias/aws/sns"
}

locals {
  alb_dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
  }
  api_target_dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.api.arn_suffix
  }
  alarm_actions = var.alarm_actions_enabled ? [aws_sns_topic.alarms.arn] : []
}

# --- ログから作る独自メトリクス(構造化ログの JSON を数える) ------------------------------
resource "aws_cloudwatch_log_metric_filter" "analysis_failed" {
  name           = "analysis-failed"
  log_group_name = aws_cloudwatch_log_group.api.name
  pattern        = "{ $.event = \"analysis_failed\" }"

  metric_transformation {
    name          = "AnalysisFailed"
    namespace     = "AiAgent"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "analysis_duration" {
  name           = "analysis-duration"
  log_group_name = aws_cloudwatch_log_group.api.name
  pattern        = "{ $.event = \"analysis_completed\" }"

  metric_transformation {
    name      = "AnalysisDurationMs"
    namespace = "AiAgent"
    value     = "$.duration_ms"
    unit      = "Milliseconds"
  }
}

resource "aws_cloudwatch_log_metric_filter" "http_5xx" {
  name           = "http-5xx"
  log_group_name = aws_cloudwatch_log_group.api.name
  pattern        = "{ $.event = \"request_completed\" && $.status >= 500 }"

  metric_transformation {
    name          = "Http5xx"
    namespace     = "AiAgent"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "approval_not_found" {
  name           = "approval-not-found"
  log_group_name = aws_cloudwatch_log_group.api.name
  pattern        = "{ $.event = \"approval_not_found\" }"

  metric_transformation {
    name          = "ApprovalNotFound"
    namespace     = "AiAgent"
    value         = "1"
    default_value = "0"
  }
}

# --- アラーム --------------------------------------------------------------------------
# しきい値は「測った実績」から決める(第16章の本文)。ここでは出発点。
resource "aws_cloudwatch_metric_alarm" "alb_target_5xx" {
  alarm_name          = "${var.project_name}-alb-target-5xx"
  alarm_description   = "api(ターゲット)が 5xx を返している。DB・モデルの障害、またはコードの不具合"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = local.alb_dimensions
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching" # リクエストが無い間は、異常とは言えない
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "api_healthy_hosts" {
  alarm_name          = "${var.project_name}-api-healthy-hosts"
  alarm_description   = "ALB の後ろの正常な api タスクが 0。サービスが止まっている"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HealthyHostCount"
  dimensions          = local.api_target_dimensions
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching" # データが無い = 台が居ない、は異常
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "api_unhealthy_hosts" {
  alarm_name          = "${var.project_name}-api-unhealthy-hosts"
  alarm_description   = "ヘルスチェックに失敗している api タスクがある(一部の台の障害)"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  dimensions          = local.api_target_dimensions
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "api_cpu" {
  alarm_name          = "${var.project_name}-api-cpu"
  alarm_description   = "api の CPU 使用率が高い(台数・サイズの見直しの合図)"
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  dimensions          = { ClusterName = aws_ecs_cluster.main.name, ServiceName = aws_ecs_service.api.name }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "api_memory" {
  alarm_name          = "${var.project_name}-api-memory"
  alarm_description   = "api のメモリ使用率が高い(OOM で落ちる前の合図)"
  namespace           = "AWS/ECS"
  metric_name         = "MemoryUtilization"
  dimensions          = { ClusterName = aws_ecs_cluster.main.name, ServiceName = aws_ecs_service.api.name }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "analysis_failed" {
  alarm_name          = "${var.project_name}-analysis-failed"
  alarm_description   = "分析の実行が例外で失敗した(構造化ログ analysis_failed の件数)。5xx より原因に近い"
  namespace           = "AiAgent"
  metric_name         = "AnalysisFailed"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "analysis_latency_p95" {
  alarm_name          = "${var.project_name}-analysis-latency-p95"
  alarm_description   = "分析の所要時間(p95)が長い。API の時間切れ(120 秒)の手前で気づく"
  namespace           = "AiAgent"
  metric_name         = "AnalysisDurationMs"
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 2
  threshold           = 60000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# --- ダッシュボード ----------------------------------------------------------------------
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.project_name}-runtime"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title = "リクエストと 5xx(ALB)", region = var.aws_region, period = 60, stat = "Sum"
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.main.arn_suffix],
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", aws_lb.main.arn_suffix],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title = "分析の所要時間 p95 / 失敗(ログから)", region = var.aws_region, period = 300
          metrics = [
            ["AiAgent", "AnalysisDurationMs", { stat = "p95" }],
            ["AiAgent", "AnalysisFailed", { stat = "Sum", yAxis = "right" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title = "正常な api タスク数", region = var.aws_region, period = 60, stat = "Minimum"
          metrics = [
            ["AWS/ApplicationELB", "HealthyHostCount", "LoadBalancer", aws_lb.main.arn_suffix, "TargetGroup", aws_lb_target_group.api.arn_suffix],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title = "api の CPU・メモリ", region = var.aws_region, period = 300, stat = "Average"
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", aws_ecs_service.api.name],
            ["AWS/ECS", "MemoryUtilization", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", aws_ecs_service.api.name],
          ]
        }
      },
    ]
  })
}
