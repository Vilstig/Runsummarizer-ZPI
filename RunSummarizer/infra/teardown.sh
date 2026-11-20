#!/usr/bin/env bash
# Destroy the stack but keep the application Secrets Manager secret and the
# ACM certificate (when domain_name is set) in AWS.
# (Strava/Clerk/OAuth keys and the Issued cert survive so the next deploy can
# import them — no new Cloudflare ACM validation CNAMEs.)
#
# The postgres_dsn secret is destroyed with RDS and recreated on the next deploy.
#
# Usage:
#   ./teardown.sh
#   ./teardown.sh --yes

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

AUTO_APPROVE=0

usage() {
  sed -n '2,12p' "$0" | tr -d '#'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
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

SECRET_NAME="$(app_secret_name_from_tfvars)"
DOMAIN_NAME="$(tfvars_value domain_name "")"

echo "This will destroy VPC, NAT, ALB, RDS, ECS, ECR, logs, and the postgres_dsn secret."
echo "Kept in AWS (removed from Terraform state only):"
echo "  ${SECRET_NAME}"
if [[ -n "${DOMAIN_NAME}" ]]; then
  echo "  ACM certificate for ${DOMAIN_NAME} (and validation resource)"
fi
echo ""

if [[ "${AUTO_APPROVE}" -ne 1 ]]; then
  read -r -p "Type 'destroy' to continue: " ans || true
  if [[ "${ans}" != "destroy" ]]; then
    echo "Aborted."
    exit 1
  fi
fi

echo "==> terraform init"
tf init -input=false

# Drop app secret resources from state so destroy leaves them in AWS.
for addr in \
  aws_secretsmanager_secret_version.app \
  aws_secretsmanager_secret.app \
  random_password.oauth_state_secret \
  random_password.token_encryption_key
do
  if tf state list 2>/dev/null | grep -qx "${addr}"; then
    echo "==> Detaching ${addr} from state (AWS resource kept where applicable)"
    tf state rm "${addr}" >/dev/null
  fi
done

# Keep the Issued ACM cert so the next deploy reuses it (same Cloudflare CNAMEs).
if [[ -n "${DOMAIN_NAME}" ]]; then
  for addr in \
    'aws_acm_certificate_validation.api[0]' \
    'aws_acm_certificate.api[0]'
  do
    if tf state list 2>/dev/null | grep -qxF "${addr}"; then
      echo "==> Detaching ${addr} from state (ACM cert kept in AWS)"
      tf state rm "${addr}" >/dev/null
    fi
  done
fi

echo "==> terraform destroy"
DESTROY_ARGS=()
if [[ "${AUTO_APPROVE}" -eq 1 ]]; then
  DESTROY_ARGS+=(-auto-approve)
fi
tf destroy "${DESTROY_ARGS[@]}"

echo ""
echo "Teardown finished."
echo "App secret still in AWS: ${SECRET_NAME}"
if [[ -n "${DOMAIN_NAME}" ]]; then
  echo "ACM certificate for ${DOMAIN_NAME} still in AWS (leave Cloudflare validation CNAMEs in place)."
fi
echo "Next ./deploy.sh will import kept resources automatically."
echo "RDS data is gone — the next deploy creates a fresh database and re-runs migrations."
echo "Re-create the app → ALB CNAME after the next deploy (ALB DNS name changes)."
