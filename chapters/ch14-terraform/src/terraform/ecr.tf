resource "aws_ecr_repository" "api" {
  name = "${var.project_name}-api"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "ui" {
  name = "${var.project_name}-ui"

  image_scanning_configuration {
    scan_on_push = true
  }
}
