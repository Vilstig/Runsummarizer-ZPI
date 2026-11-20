variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short name used in resource names and tags"
  type        = string
  default     = "runsummarizer"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "db_name" {
  description = "Initial PostgreSQL database name"
  type        = string
  default     = "runsummarizer"
}

variable "db_username" {
  description = "Master username for the RDS instance"
  type        = string
  default     = "app"
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "Allocated storage in GiB"
  type        = number
  default     = 20
}

variable "db_engine_version" {
  description = "PostgreSQL major/minor version"
  type        = string
  default     = "18"
}

variable "ecs_image_tag" {
  description = "Image tag to deploy from ECR (push this tag before raising desired counts)"
  type        = string
  default     = "latest"
}

variable "ecs_api_desired_count" {
  description = "Desired API tasks (0 until an image has been pushed to ECR)"
  type        = number
  default     = 0
}

variable "ecs_worker_desired_count" {
  description = "Desired worker tasks (0 until an image has been pushed to ECR)"
  type        = number
  default     = 0
}

variable "ecs_frontend_desired_count" {
  description = "Desired frontend tasks (0 until an image has been pushed to ECR)"
  type        = number
  default     = 0
}

variable "ecs_api_cpu" {
  description = "Fargate CPU units for the API task"
  type        = number
  default     = 256
}

variable "ecs_api_memory" {
  description = "Fargate memory (MiB) for the API task"
  type        = number
  default     = 512
}

variable "ecs_worker_cpu" {
  description = "Fargate CPU units for the worker task"
  type        = number
  default     = 256
}

variable "ecs_worker_memory" {
  description = "Fargate memory (MiB) for the worker task"
  type        = number
  default     = 512
}

variable "ecs_frontend_cpu" {
  description = "Fargate CPU units for the frontend task"
  type        = number
  default     = 256
}

variable "ecs_frontend_memory" {
  description = "Fargate memory (MiB) for the frontend task"
  type        = number
  default     = 512
}

variable "clerk_authorized_parties" {
  description = "Comma-separated Clerk authorized parties (SPA origin = ALB URL or custom domain)"
  type        = string
  default     = ""
}

variable "domain_name" {
  description = "Public API hostname managed in Cloudflare (e.g. api.example.com). Empty keeps HTTP-only on the ALB DNS name."
  type        = string
  default     = ""
}

variable "ecs_execution_role_name" {
  description = "Existing IAM role name used as the ECS task execution role (LabRole on AWS Academy)"
  type        = string
  default     = "LabRole"
}

variable "ecs_task_role_name" {
  description = "Existing IAM role name used as the ECS task role (LabRole on AWS Academy)"
  type        = string
  default     = "LabRole"
}
