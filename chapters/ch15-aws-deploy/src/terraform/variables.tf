variable "aws_region" {
  type        = string
  description = "AWS region"
  default     = "ap-northeast-1"
}

variable "project_name" {
  type        = string
  description = "Project name"
  default     = "ai-agent-practice"
}

variable "enable_nat_gateway" {
  type        = bool
  description = "true(標準): タスクを非公開サブネットに置き、NAT Gateway で外へ出す(約 $0.062/時 + 通信量)。false: NAT を作らず、タスクを公開サブネットに置いて公開 IP で外へ出す"
  default     = true
}

variable "alb_ingress_cidrs" {
  type        = list(string)
  description = "ALB へ 80 番で入ってよい送信元。既定は空 = 誰も入れない(第15章で自分の IP などを渡す)"
  default     = []

  validation {
    condition     = !contains(var.alb_ingress_cidrs, "0.0.0.0/0")
    error_message = "0.0.0.0/0 は指定できません。公開するなら、理由を残したうえでこの検証を外してください。"
  }
}

variable "db_username" {
  type        = string
  description = "RDS のマスターユーザー名(パスワードは RDS が Secrets Manager で管理する)"
  default     = "agent_admin"
}

variable "db_deletion_protection" {
  type        = bool
  description = "学習用は false(destroy できる)。本番は true"
  default     = false
}

variable "api_image_tag" {
  type        = string
  description = "ECR の api イメージのタグ(不変タグ。版ごとに新しい値にする)"
  default     = "v1"
}

variable "ui_image_tag" {
  type        = string
  description = "ECR の ui イメージのタグ"
  default     = "v1"
}

# 既定は 0。シークレットとイメージが用意できる前にタスクを起動して失敗させないため
variable "api_desired_count" {
  type        = number
  description = "api タスクの数"
  default     = 0
}

variable "ui_desired_count" {
  type        = number
  description = "ui タスクの数"
  default     = 0
}

variable "mount_data_volume" {
  type        = bool
  description = "api に /app/data の一時ボリュームを付ける。v1(状態をファイルに置く第13章のコード)の実験用。v2 は不要"
  default     = false
}
