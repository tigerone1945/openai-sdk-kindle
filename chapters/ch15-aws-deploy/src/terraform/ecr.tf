# タグは不変。「v1 の中身が、後から差し替わる」ことを防ぐ(版を上げるときは新しいタグを使う)。
# force_delete: 学習用。destroy のたびにイメージごと消し、次の回で push し直す。
resource "aws_ecr_repository" "api" {
  name                 = "${var.project_name}-api"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "ui" {
  name                 = "${var.project_name}-ui"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}
