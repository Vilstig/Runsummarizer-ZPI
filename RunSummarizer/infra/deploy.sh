#!/usr/bin/env bash
# Bring up the stack, optionally fill secrets, build/push images, migrate, scale.
#
# Usage:
#   ./deploy.sh                 # prompt whether to enter secrets
#   ./deploy.sh --fill-secrets  # always prompt for Secrets Manager values
#   ./deploy.sh --no-secrets    # skip secrets prompt
#   ./deploy.sh --skip-build    # reuse images already in ECR
#   ./deploy.sh --skip-migrate  # skip the one-off migration task
#   ./deploy.sh --yes           # terraform apply -auto-approve

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

FILL_SECRETS="ask"
SKIP_BUILD=0
SKIP_MIGRATE=0
AUTO_APPROVE=0

usage() {
  sed -n '2,12p' "$0" | tr -d '#'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fill-secrets | -s) FILL_SECRETS=1 ;;
    --no-secrets) FILL_SECRETS=0 ;;
    --skip-build) SKIP_BUILD=1 ;;
    --skip-migrate) SKIP_MIGRATE=1 ;;
    --yes | -y) AUTO_APPROVE=1 ;;
    -h | --help) usage 0 ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage 1
      ;;
  esac
  shift
done

require_tools
aws_ok
ensure_tfvars

echo "==> terraform init"
tf init -input=false

import_app_secret_if_present
import_acm_certificate_if_present
purge_postgres_dsn_secret_if_blocking

echo "==> terraform apply (desired counts stay 0 until images + migrate are done)"
APPLY_ARGS=(
  -var "ecs_api_desired_count=0"
  -var "ecs_worker_desired_count=0"
  -var "ecs_frontend_desired_count=0"
)
if [[ "${AUTO_APPROVE}" -eq 1 ]]; then
  APPLY_ARGS+=(-auto-approve)
fi
tf apply "${APPLY_ARGS[@]}"

if [[ "${FILL_SECRETS}" == "ask" ]]; then
  read -r -p "Enter/update application secrets now? [y/N] " ans || true
  case "${ans}" in
    y | Y | yes | YES) FILL_SECRETS=1 ;;
    *) FILL_SECRETS=0 ;;
  esac
fi

if [[ "${FILL_SECRETS}" == "1" ]]; then
  fill_app_secrets
else
  echo "==> Skipping secrets prompt (reuse existing Secrets Manager values)"
  ensure_app_secret_keys
fi

TAG="$(tfvars_value ecs_image_tag latest)"
CLERK_PK="$(vite_clerk_publishable_key)"

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  if [[ -z "${CLERK_PK}" ]]; then
    echo "error: VITE_CLERK_PUBLISHABLE_KEY is empty" >&2
    echo "Set it in frontend/.env or export VITE_CLERK_PUBLISHABLE_KEY before building." >&2
    exit 1
  fi

  echo "==> Build & push images (tag=${TAG})"
  docker_ecr_login

  API_REPO="$(tf_output ecr_api_repository_url)"
  WORKER_REPO="$(tf_output ecr_worker_repository_url)"
  MIGRATION_REPO="$(tf_output ecr_migration_repository_url)"
  FRONTEND_REPO="$(tf_output ecr_frontend_repository_url)"

  docker build -f "${REPO_ROOT}/backend/Dockerfile" --target api \
    -t "${API_REPO}:${TAG}" "${REPO_ROOT}/backend"
  docker build -f "${REPO_ROOT}/backend/Dockerfile" --target worker \
    -t "${WORKER_REPO}:${TAG}" "${REPO_ROOT}/backend"
  docker build -f "${REPO_ROOT}/backend/Dockerfile" --target migration \
    -t "${MIGRATION_REPO}:${TAG}" "${REPO_ROOT}/backend"
  # Same-origin /api on the ALB — leave VITE_API_BASE_URL empty.
  docker build -f "${REPO_ROOT}/frontend/Dockerfile" --target runner \
    --build-arg "VITE_CLERK_PUBLISHABLE_KEY=${CLERK_PK}" \
    --build-arg "VITE_API_BASE_URL=" \
    -t "${FRONTEND_REPO}:${TAG}" "${REPO_ROOT}/frontend"

  docker push "${API_REPO}:${TAG}"
  docker push "${WORKER_REPO}:${TAG}"
  docker push "${MIGRATION_REPO}:${TAG}"
  docker push "${FRONTEND_REPO}:${TAG}"
else
  echo "==> Skipping image build/push"
fi

if [[ "${SKIP_MIGRATE}" -eq 0 ]]; then
  run_migration_task
else
  echo "==> Skipping migrations"
fi

echo "==> Scaling API, worker, and frontend to 1"
CLUSTER="$(tf_output ecs_cluster_name)"
aws ecs update-service \
  --cluster "${CLUSTER}" \
  --service "$(tf_output ecs_api_service_name)" \
  --desired-count 1 \
  --force-new-deployment >/dev/null
aws ecs update-service \
  --cluster "${CLUSTER}" \
  --service "$(tf_output ecs_worker_service_name)" \
  --desired-count 1 \
  --force-new-deployment >/dev/null
aws ecs update-service \
  --cluster "${CLUSTER}" \
  --service "$(tf_output ecs_frontend_service_name)" \
  --desired-count 1 \
  --force-new-deployment >/dev/null

ALB_URL="$(tf_output alb_url)"
CLERK_PARTIES="$(tfvars_value clerk_authorized_parties "")"
echo ""
echo "Deploy finished."
echo "  App URL:      ${ALB_URL}"
echo "  SPA:          curl -sS -o /dev/null -w '%{http_code}\\n' ${ALB_URL}/"
echo "  Health:       curl -sS ${ALB_URL}/api/health"
echo "  Ready:        curl -sS ${ALB_URL}/api/health/ready"
echo "  API logs:     aws logs tail /ecs/${CLUSTER}/api --follow"
echo "  Frontend logs: aws logs tail /ecs/${CLUSTER}/frontend --follow"
echo ""
if [[ "${CLERK_PARTIES}" != "${ALB_URL}" ]]; then
  echo "NOTE: Set clerk_authorized_parties = \"${ALB_URL}\" in terraform.tfvars,"
  echo "      add that origin in the Clerk dashboard, then re-run ./deploy.sh --skip-build --skip-migrate --yes"
  echo ""
fi
echo "Give the load balancer a minute for targets to become healthy."
