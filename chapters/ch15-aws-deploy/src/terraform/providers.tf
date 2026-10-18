terraform {
  required_version = ">= 1.10.0" # S3 backend の use_lockfile が使える最小版

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # 全リソースに付く。destroy 後の「残存確認」を、タグで引けるようにする
  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
      Chapter   = "15"
    }
  }
}
