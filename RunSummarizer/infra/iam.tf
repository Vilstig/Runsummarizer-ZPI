# AWS Academy / Vocareum learners cannot iam:CreateRole. Reuse the shared LabRole
# (trusts ecs-tasks.amazonaws.com and usually already allows ECR, logs, Secrets Manager).
data "aws_iam_role" "ecs_execution" {
  name = var.ecs_execution_role_name
}

data "aws_iam_role" "ecs_task" {
  name = var.ecs_task_role_name
}

locals {
  ecs_execution_role_arn = data.aws_iam_role.ecs_execution.arn
  ecs_task_role_arn      = data.aws_iam_role.ecs_task.arn
}
