locals {
  api_image       = "${aws_ecr_repository.api.repository_url}:${var.ecs_image_tag}"
  worker_image    = "${aws_ecr_repository.worker.repository_url}:${var.ecs_image_tag}"
  migration_image = "${aws_ecr_repository.migration.repository_url}:${var.ecs_image_tag}"
  frontend_image  = "${aws_ecr_repository.frontend.repository_url}:${var.ecs_image_tag}"

  # Shared container secrets injected from Secrets Manager JSON keys.
  app_secret_arns = {
    STRAVA_CLIENT_ID              = "${aws_secretsmanager_secret.app.arn}:STRAVA_CLIENT_ID::"
    STRAVA_CLIENT_SECRET          = "${aws_secretsmanager_secret.app.arn}:STRAVA_CLIENT_SECRET::"
    STRAVA_WEBHOOK_VERIFY_TOKEN   = "${aws_secretsmanager_secret.app.arn}:STRAVA_WEBHOOK_VERIFY_TOKEN::"
    STRAVA_WEBHOOK_PATH_SECRET    = "${aws_secretsmanager_secret.app.arn}:STRAVA_WEBHOOK_PATH_SECRET::"
    GARMIN_CLIENT_ID              = "${aws_secretsmanager_secret.app.arn}:GARMIN_CLIENT_ID::"
    GARMIN_CLIENT_SECRET          = "${aws_secretsmanager_secret.app.arn}:GARMIN_CLIENT_SECRET::"
    GARMIN_WEBHOOK_PATH_SECRET    = "${aws_secretsmanager_secret.app.arn}:GARMIN_WEBHOOK_PATH_SECRET::"
    INTERVALS_CLIENT_ID           = "${aws_secretsmanager_secret.app.arn}:INTERVALS_CLIENT_ID::"
    INTERVALS_CLIENT_SECRET       = "${aws_secretsmanager_secret.app.arn}:INTERVALS_CLIENT_SECRET::"
    INTERVALS_WEBHOOK_PATH_SECRET = "${aws_secretsmanager_secret.app.arn}:INTERVALS_WEBHOOK_PATH_SECRET::"
    INTERVALS_WEBHOOK_SECRET      = "${aws_secretsmanager_secret.app.arn}:INTERVALS_WEBHOOK_SECRET::"
    OAUTH_STATE_SECRET            = "${aws_secretsmanager_secret.app.arn}:OAUTH_STATE_SECRET::"
    TOKEN_ENCRYPTION_KEY          = "${aws_secretsmanager_secret.app.arn}:TOKEN_ENCRYPTION_KEY::"
    CLERK_SECRET_KEY              = "${aws_secretsmanager_secret.app.arn}:CLERK_SECRET_KEY::"
    CLERK_JWT_KEY                 = "${aws_secretsmanager_secret.app.arn}:CLERK_JWT_KEY::"
    CLERK_WEBHOOK_SECRET          = "${aws_secretsmanager_secret.app.arn}:CLERK_WEBHOOK_SECRET::"
    POSTGRES_DSN                  = "${aws_secretsmanager_secret.postgres_dsn.arn}:POSTGRES_DSN::"
  }

  # Same public origin for SPA + API (path-routed on the ALB).
  api_base_url = var.domain_name != "" ? "https://${var.domain_name}" : "http://${aws_lb.main.dns_name}"

  shared_environment = [
    { name = "TRUST_PROXY_HEADERS", value = "true" },
    { name = "FRONTEND_URL", value = local.api_base_url },
    { name = "CLERK_AUTHORIZED_PARTIES", value = var.clerk_authorized_parties },
    {
      name  = "STRAVA_REDIRECT_URI"
      value = "${local.api_base_url}/api/providers/strava/callback"
    },
    {
      name  = "STRAVA_BACKEND_REDIRECT_URI"
      value = "${local.api_base_url}/api/providers/strava/callback"
    },
    {
      name  = "GARMIN_REDIRECT_URI"
      value = "${local.api_base_url}/api/providers/garmin/callback"
    },
    {
      name  = "INTERVALS_REDIRECT_URI"
      value = "${local.api_base_url}/api/providers/intervals/callback"
    },
  ]

  shared_secrets = [
    for name, value_from in local.app_secret_arns : {
      name      = name
      valueFrom = value_from
    }
  ]
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project_name}-${var.environment}/api"
  retention_in_days = 14

  tags = {
    Name = "${var.project_name}-${var.environment}-api-logs"
  }
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${var.project_name}-${var.environment}/worker"
  retention_in_days = 14

  tags = {
    Name = "${var.project_name}-${var.environment}-worker-logs"
  }
}

resource "aws_cloudwatch_log_group" "migration" {
  name              = "/ecs/${var.project_name}-${var.environment}/migration"
  retention_in_days = 14

  tags = {
    Name = "${var.project_name}-${var.environment}-migration-logs"
  }
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/ecs/${var.project_name}-${var.environment}/frontend"
  retention_in_days = 14

  tags = {
    Name = "${var.project_name}-${var.environment}-frontend-logs"
  }
}

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "disabled"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-ecs"
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = ["FARGATE"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project_name}-${var.environment}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ecs_api_cpu
  memory                   = var.ecs_api_memory
  execution_role_arn       = local.ecs_execution_role_arn
  task_role_arn            = local.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = local.api_image
      essential = true
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      environment = local.shared_environment
      secrets     = local.shared_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }
    }
  ])

  tags = {
    Name = "${var.project_name}-${var.environment}-api"
  }
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project_name}-${var.environment}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ecs_worker_cpu
  memory                   = var.ecs_worker_memory
  execution_role_arn       = local.ecs_execution_role_arn
  task_role_arn            = local.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name        = "worker"
      image       = local.worker_image
      essential   = true
      environment = local.shared_environment
      secrets     = local.shared_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.worker.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "worker"
        }
      }
    }
  ])

  tags = {
    Name = "${var.project_name}-${var.environment}-worker"
  }
}

# One-off Fargate task (run via deploy.sh). Image CMD is `alembic upgrade head`.
resource "aws_ecs_task_definition" "migration" {
  family                   = "${var.project_name}-${var.environment}-migration"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ecs_api_cpu
  memory                   = var.ecs_api_memory
  execution_role_arn       = local.ecs_execution_role_arn
  task_role_arn            = local.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name        = "migration"
      image       = local.migration_image
      essential   = true
      environment = local.shared_environment
      secrets     = local.shared_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.migration.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "migration"
        }
      }
    }
  ])

  tags = {
    Name = "${var.project_name}-${var.environment}-migration"
  }
}

resource "aws_ecs_task_definition" "frontend" {
  family                   = "${var.project_name}-${var.environment}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ecs_frontend_cpu
  memory                   = var.ecs_frontend_memory
  execution_role_arn       = local.ecs_execution_role_arn
  task_role_arn            = local.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "frontend"
      image     = local.frontend_image
      essential = true
      portMappings = [
        {
          containerPort = 8080
          hostPort      = 8080
          protocol      = "tcp"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.frontend.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "frontend"
        }
      }
    }
  ])

  tags = {
    Name = "${var.project_name}-${var.environment}-frontend"
  }
}

resource "aws_ecs_service" "api" {
  name            = "${var.project_name}-${var.environment}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.ecs_api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [
    aws_lb_listener.http,
    aws_lb_listener_rule.http_api,
    aws_lb_listener_rule.https_api,
  ]

  tags = {
    Name = "${var.project_name}-${var.environment}-api"
  }
}

resource "aws_ecs_service" "frontend" {
  name            = "${var.project_name}-${var.environment}-frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = var.ecs_frontend_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.frontend.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 8080
  }

  depends_on = [
    aws_lb_listener.http,
    aws_lb_listener.https,
  ]

  tags = {
    Name = "${var.project_name}-${var.environment}-frontend"
  }
}

resource "aws_ecs_service" "worker" {
  name            = "${var.project_name}-${var.environment}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.ecs_worker_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-worker"
  }
}
