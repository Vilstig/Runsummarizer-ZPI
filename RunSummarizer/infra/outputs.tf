output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs (future ALB / NAT)"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet IDs (RDS and future compute)"
  value       = aws_subnet.private[*].id
}

output "app_security_group_id" {
  description = "Attach this SG to API/worker workloads that need DB access"
  value       = aws_security_group.app.id
}

output "frontend_security_group_id" {
  description = "Frontend (nginx) security group — ALB ingress only, no RDS"
  value       = aws_security_group.frontend.id
}

output "rds_security_group_id" {
  description = "Security group attached to the RDS instance"
  value       = aws_security_group.rds.id
}

output "rds_endpoint" {
  description = "RDS hostname:port"
  value       = aws_db_instance.main.endpoint
}

output "rds_address" {
  description = "RDS hostname only"
  value       = aws_db_instance.main.address
}

output "rds_port" {
  description = "RDS port"
  value       = aws_db_instance.main.port
}

output "rds_db_name" {
  description = "Initial database name"
  value       = aws_db_instance.main.db_name
}

output "rds_master_user_secret_arn" {
  description = "Secrets Manager ARN for the RDS-managed master password"
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
}

output "app_secret_arn" {
  description = "Secrets Manager ARN for application secrets (Strava, Clerk, etc.)"
  value       = aws_secretsmanager_secret.app.arn
}

output "app_secret_name" {
  description = "Secrets Manager name for application secrets"
  value       = aws_secretsmanager_secret.app.name
}

output "ecs_task_role_arn" {
  description = "IAM role ARN for ECS tasks (runtime)"
  value       = local.ecs_task_role_arn
}

output "ecs_task_role_name" {
  description = "IAM role name for ECS tasks"
  value       = data.aws_iam_role.ecs_task.name
}

output "ecs_execution_role_arn" {
  description = "IAM role ARN for ECS task execution (pull images, inject secrets)"
  value       = local.ecs_execution_role_arn
}

output "postgres_dsn_secret_arn" {
  description = "Secrets Manager ARN for the assembled POSTGRES_DSN"
  value       = aws_secretsmanager_secret.postgres_dsn.arn
}

output "ecr_api_repository_url" {
  description = "ECR repository URL for the API image"
  value       = aws_ecr_repository.api.repository_url
}

output "ecr_worker_repository_url" {
  description = "ECR repository URL for the worker image"
  value       = aws_ecr_repository.worker.repository_url
}

output "ecr_migration_repository_url" {
  description = "ECR repository URL for the migration image"
  value       = aws_ecr_repository.migration.repository_url
}

output "ecr_frontend_repository_url" {
  description = "ECR repository URL for the frontend image"
  value       = aws_ecr_repository.frontend.repository_url
}

output "ecs_migration_task_family" {
  description = "ECS task definition family for one-off Alembic migrations"
  value       = aws_ecs_task_definition.migration.family
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "ecs_api_service_name" {
  description = "ECS API service name"
  value       = aws_ecs_service.api.name
}

output "ecs_worker_service_name" {
  description = "ECS worker service name"
  value       = aws_ecs_service.worker.name
}

output "ecs_frontend_service_name" {
  description = "ECS frontend service name"
  value       = aws_ecs_service.frontend.name
}

output "alb_dns_name" {
  description = "Public DNS name of the Application Load Balancer (Cloudflare CNAME target)"
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "Hosted zone ID of the ALB (for Route53 alias records; not needed for Cloudflare CNAME)"
  value       = aws_lb.main.zone_id
}

output "alb_url" {
  description = "Public origin for the SPA and API (same ALB, path-routed)"
  value       = var.domain_name != "" ? "https://${var.domain_name}" : "http://${aws_lb.main.dns_name}"
}

output "domain_name" {
  description = "Configured custom domain (empty if using raw ALB DNS)"
  value       = var.domain_name
}

output "acm_certificate_arn" {
  description = "ACM certificate ARN (null when domain_name is unset)"
  value       = try(aws_acm_certificate.api[0].arn, null)
}

output "acm_validation_records" {
  description = "Create these CNAME records in Cloudflare (DNS only / grey cloud) to validate the ACM certificate"
  value = var.domain_name != "" ? [
    for dvo in aws_acm_certificate.api[0].domain_validation_options : {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  ] : []
}
