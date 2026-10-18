# state は S3 に置く。バケット名などの環境依存の値は、コードに書かず
# `terraform init -backend-config=backend.hcl` で渡す(backend.hcl.example を参照)
terraform {
  backend "s3" {
    encrypt      = true
    use_lockfile = true # S3 のロックファイル。DynamoDB は不要
  }
}
