resource "random_password" "oauth_state_secret" {
  length  = 32
  special = false
}

resource "random_password" "token_encryption_key" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  name        = "${var.project_name}/${var.environment}/app"
  description = "Application secrets for ${var.project_name} (${var.environment})"

  tags = {
    Name = "${var.project_name}-${var.environment}-app-secrets"
  }
}

# Initial placeholder values. Fill Strava/Garmin/Clerk via console or CLI after apply.
# Terraform will not overwrite subsequent manual updates to the secret value.
resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    STRAVA_CLIENT_ID              = ""
    STRAVA_CLIENT_SECRET          = ""
    STRAVA_WEBHOOK_VERIFY_TOKEN   = ""
    STRAVA_WEBHOOK_PATH_SECRET    = ""
    GARMIN_CLIENT_ID              = ""
    GARMIN_CLIENT_SECRET          = ""
    GARMIN_WEBHOOK_PATH_SECRET    = ""
    INTERVALS_CLIENT_ID           = ""
    INTERVALS_CLIENT_SECRET       = ""
    INTERVALS_WEBHOOK_PATH_SECRET = ""
    INTERVALS_WEBHOOK_SECRET      = ""
    OAUTH_STATE_SECRET            = random_password.oauth_state_secret.result
    TOKEN_ENCRYPTION_KEY          = random_password.token_encryption_key.result
    CLERK_SECRET_KEY              = ""
    CLERK_JWT_KEY                 = ""
    CLERK_WEBHOOK_SECRET          = ""
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

data "aws_secretsmanager_secret_version" "rds_master" {
  secret_id = aws_db_instance.main.master_user_secret[0].secret_arn
}

locals {
  rds_master = jsondecode(data.aws_secretsmanager_secret_version.rds_master.secret_string)

  # asyncpg DSN; password is URL-encoded for special characters.
  postgres_dsn = format(
    "postgresql+asyncpg://%s:%s@%s:%s/%s",
    local.rds_master.username,
    urlencode(local.rds_master.password),
    aws_db_instance.main.address,
    tostring(aws_db_instance.main.port),
    aws_db_instance.main.db_name,
  )
}

resource "aws_secretsmanager_secret" "postgres_dsn" {
  name        = "${var.project_name}/${var.environment}/postgres_dsn"
  description = "Postgres DSN for ${var.project_name} (${var.environment})"

  tags = {
    Name = "${var.project_name}-${var.environment}-postgres-dsn"
  }
}

resource "aws_secretsmanager_secret_version" "postgres_dsn" {
  secret_id = aws_secretsmanager_secret.postgres_dsn.id
  secret_string = jsonencode({
    POSTGRES_DSN = local.postgres_dsn
  })
}
