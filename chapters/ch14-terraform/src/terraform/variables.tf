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
  description = "true: プライベートサブネットから外へ出る NAT Gateway を作る(約 $0.062/時 + 通信量)。false: 作らない"
  default     = false
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
