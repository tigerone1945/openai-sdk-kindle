# ui が api を、IP ではなく名前(api.<project>.internal)で呼ぶための、VPC 内だけの名前解決
resource "aws_service_discovery_private_dns_namespace" "main" {
  name = "${var.project_name}.internal"
  vpc  = aws_vpc.main.id
}

resource "aws_service_discovery_service" "api" {
  name = "api"

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.main.id
    routing_policy = "MULTIVALUE"

    dns_records {
      type = "A"
      ttl  = 10
    }
  }
}
