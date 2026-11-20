# ACM cert for the ALB. DNS validation records must be created in Cloudflare
# (see outputs.acm_validation_records). Run:
#   terraform apply -target=aws_acm_certificate.api
# then add the CNAMEs in Cloudflare (DNS only / grey cloud), wait until Issued,
# then run a full terraform apply.
resource "aws_acm_certificate" "api" {
  count = var.domain_name != "" ? 1 : 0

  domain_name       = var.domain_name
  validation_method = "DNS"

  tags = {
    Name = "${var.project_name}-${var.environment}-api-cert"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "api" {
  count = var.domain_name != "" ? 1 : 0

  certificate_arn = aws_acm_certificate.api[0].arn
  validation_record_fqdns = [
    for dvo in aws_acm_certificate.api[0].domain_validation_options : dvo.resource_record_name
  ]

  timeouts {
    create = "45m"
  }
}
