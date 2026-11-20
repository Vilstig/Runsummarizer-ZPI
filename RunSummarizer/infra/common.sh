#!/usr/bin/env bash
# Shared helpers for deploy.sh / teardown.sh. Source only — do not execute.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INFRA_DIR="${SCRIPT_DIR}"

# Git Bash on Windows runs the native aws.exe and jq.exe, which end lines with CRLF;
# the CR is stripped so values captured with $(...) are the same as on Linux.
case "${OSTYPE:-}" in
  msys* | cygwin*)
    aws() { command aws "$@" | tr -d '\r'; }
    jq() { command jq "$@" | tr -d '\r'; }
    # docker.exe needs a Windows path for its config directory.
    export DOCKER_CONFIG="${DOCKER_CONFIG:-$(cygpath -m "${TMPDIR:-/tmp}")/docker-ecr-config}"
    ;;
esac

need_cmd() {
  type -P "$1" >/dev/null 2>&1 || {
    echo "error: required command not found: $1" >&2
    exit 1
  }
}

require_tools() {
  need_cmd aws
  need_cmd terraform
  need_cmd docker
  need_cmd jq
}

aws_ok() {
  aws sts get-caller-identity >/dev/null
}

tf() {
  (cd "${INFRA_DIR}" && terraform "$@")
}

tf_output() {
  tf output -raw "$1"
}

tfvars_value() {
  local key="$1"
  local default="${2:-}"
  local value
  value="$(grep -E "^${key}" "${INFRA_DIR}/terraform.tfvars" 2>/dev/null \
    | sed -E 's/.*=\s*"?([^"]*)"?/\1/' \
    | tr -d '[:space:]' || true)"
  echo "${value:-${default}}"
}

ensure_tfvars() {
  if [[ ! -f "${INFRA_DIR}/terraform.tfvars" ]]; then
    echo "error: ${INFRA_DIR}/terraform.tfvars missing." >&2
    echo "Copy terraform.tfvars.example and set clerk_authorized_parties." >&2
    exit 1
  fi
}

# Clerk publishable key for the frontend image — not a Terraform variable
# (avoids storing it in state). Order: env → frontend/.env.
vite_clerk_publishable_key() {
  local value env_file
  value="${VITE_CLERK_PUBLISHABLE_KEY:-}"
  if [[ -n "${value}" ]]; then
    echo "${value}"
    return 0
  fi

  env_file="${REPO_ROOT}/frontend/.env"
  if [[ -f "${env_file}" ]]; then
    value="$(grep -E '^VITE_CLERK_PUBLISHABLE_KEY=' "${env_file}" 2>/dev/null \
      | head -n1 \
      | cut -d= -f2- \
      | tr -d '\r' \
      | sed -E 's/^[[:space:]]*//;s/[[:space:]]*$//;s/^["'\'']//;s/["'\'']$//' || true)"
    if [[ -n "${value}" ]]; then
      echo "${value}"
      return 0
    fi
  fi

  echo ""
}

app_secret_name_from_tfvars() {
  echo "$(tfvars_value project_name runsummarizer)/$(tfvars_value environment dev)/app"
}

postgres_dsn_secret_name_from_tfvars() {
  echo "$(tfvars_value project_name runsummarizer)/$(tfvars_value environment dev)/postgres_dsn"
}

# postgres_dsn is rebuilt from RDS on every deploy. If a previous destroy left it
# in the Secrets Manager recovery window (or orphaned), remove it so apply can create.
purge_postgres_dsn_secret_if_blocking() {
  local secret_name deleted
  secret_name="$(postgres_dsn_secret_name_from_tfvars)"

  if ! aws secretsmanager describe-secret --secret-id "${secret_name}" >/dev/null 2>&1; then
    return 0
  fi

  # Already managed by this state — leave it alone.
  if tf state list 2>/dev/null | grep -qx 'aws_secretsmanager_secret.postgres_dsn'; then
    return 0
  fi

  deleted="$(aws secretsmanager describe-secret \
    --secret-id "${secret_name}" \
    --query 'DeletedDate' \
    --output text 2>/dev/null || true)"

  if [[ -n "${deleted}" && "${deleted}" != "None" && "${deleted}" != "null" ]]; then
    echo "==> postgres_dsn secret pending deletion; restoring then force-deleting"
    aws secretsmanager restore-secret --secret-id "${secret_name}" >/dev/null
  else
    echo "==> Removing orphaned postgres_dsn secret ${secret_name}"
  fi

  aws secretsmanager delete-secret \
    --secret-id "${secret_name}" \
    --force-delete-without-recovery >/dev/null

  # Brief pause so CreateSecret does not race the delete.
  sleep 2
}

# If the app secret still exists in AWS (left behind by teardown), import it
# so terraform apply does not try to create a duplicate name.
# Secrets scheduled for deletion (recovery window) are restored first.
import_app_secret_if_present() {
  local secret_name deleted
  secret_name="$(app_secret_name_from_tfvars)"

  if ! aws secretsmanager describe-secret --secret-id "${secret_name}" >/dev/null 2>&1; then
    return 0
  fi

  deleted="$(aws secretsmanager describe-secret \
    --secret-id "${secret_name}" \
    --query 'DeletedDate' \
    --output text 2>/dev/null || true)"

  if [[ -n "${deleted}" && "${deleted}" != "None" && "${deleted}" != "null" ]]; then
    echo "==> App secret ${secret_name} is pending deletion; restoring"
    aws secretsmanager restore-secret --secret-id "${secret_name}" >/dev/null
  fi

  local state secret_id version_id
  state="$(tf state list 2>/dev/null || true)"

  # The version is imported with the secret's id in state (the ARN for a secret
  # imported here): a version whose secret_id differs is replaced on apply with the
  # placeholder values in secrets.tf.
  if grep -qx 'aws_secretsmanager_secret.app' <<<"${state}"; then
    secret_id="$(tf state show -no-color aws_secretsmanager_secret.app \
      | sed -nE 's/^[[:space:]]*id[[:space:]]*=[[:space:]]*"(.*)"$/\1/p' | head -n1)"
  else
    secret_id="$(aws secretsmanager describe-secret --secret-id "${secret_name}" --query ARN --output text)"
    echo "==> Importing existing app secret ${secret_name} into Terraform state"
    tf import aws_secretsmanager_secret.app "${secret_id}" >/dev/null
  fi

  if ! grep -qx 'aws_secretsmanager_secret_version.app' <<<"${state}"; then
    version_id="$(aws secretsmanager get-secret-value --secret-id "${secret_name}" --query VersionId --output text)"
    echo "==> Importing the current app secret version into Terraform state"
    tf import aws_secretsmanager_secret_version.app "${secret_id}|${version_id}" >/dev/null
  fi
}

# ACM cert ARN for domain_name: prefer ISSUED, else PENDING_VALIDATION.
# Prints "STATUS ARN" on stdout when found.
find_acm_cert_arn_for_domain() {
  local domain="$1"
  local region status arn
  region="$(aws_region)"

  for status in ISSUED PENDING_VALIDATION; do
    arn="$(aws acm list-certificates \
      --region "${region}" \
      --certificate-statuses "${status}" \
      --query "CertificateSummaryList[?DomainName=='${domain}'].CertificateArn | [0]" \
      --output text 2>/dev/null || true)"
    if [[ -n "${arn}" && "${arn}" != "None" && "${arn}" != "null" ]]; then
      echo "${status} ${arn}"
      return 0
    fi
  done
  return 1
}

# If teardown left an ACM cert for domain_name, import it so apply does not
# mint a new cert (and new Cloudflare validation CNAMEs).
import_acm_certificate_if_present() {
  local domain found status arn
  domain="$(tfvars_value domain_name "")"
  if [[ -z "${domain}" ]]; then
    return 0
  fi

  if tf state list 2>/dev/null | grep -qxF 'aws_acm_certificate.api[0]'; then
    return 0
  fi

  if ! found="$(find_acm_cert_arn_for_domain "${domain}")"; then
    return 0
  fi
  status="${found%% *}"
  arn="${found#* }"

  echo "==> Importing existing ACM certificate for ${domain} (${status})"
  echo "    ${arn}"
  if ! tf import 'aws_acm_certificate.api[0]' "${arn}" >/dev/null; then
    echo "error: failed to import aws_acm_certificate.api[0] (${arn})" >&2
    exit 1
  fi
  # aws_acm_certificate_validation can't be imported; apply creates it, which
  # completes at once for an ISSUED certificate.
}

aws_region() {
  echo "${AWS_REGION:-$(tfvars_value aws_region us-east-1)}"
}

docker_ecr_login() {
  local region account_id desktop_sock registry token auth_b64 tmp plugins_dir
  region="$(aws_region)"
  export AWS_REGION="${region}"
  account_id="$(aws sts get-caller-identity --query Account --output text)"
  registry="${account_id}.dkr.ecr.${region}.amazonaws.com"

  # Docker Desktop on Linux listens here, not on /var/run/docker.sock.
  desktop_sock="${HOME}/.docker/desktop/docker.sock"
  if [[ -S "${desktop_sock}" ]]; then
    export DOCKER_HOST="unix://${desktop_sock}"
  fi

  # Throwaway config avoids Docker Desktop's broken `pass` credsStore.
  # Do not set currentContext here — that context lives under ~/.docker/contexts
  # and is missing when DOCKER_CONFIG is relocated. DOCKER_HOST selects the engine.
  export DOCKER_CONFIG="${DOCKER_CONFIG:-/tmp/docker-ecr-config}"
  mkdir -p "${DOCKER_CONFIG}"
  if [[ ! -f "${DOCKER_CONFIG}/config.json" ]]; then
    printf '%s\n' '{"auths":{}}' >"${DOCKER_CONFIG}/config.json"
  else
    tmp="$(mktemp)"
    jq 'del(.currentContext)' "${DOCKER_CONFIG}/config.json" >"${tmp}"
    mv "${tmp}" "${DOCKER_CONFIG}/config.json"
  fi

  # Write ECR auth directly (no `docker login` → no credential helper).
  token="$(aws ecr get-login-password --region "${region}")"
  if command -v base64 >/dev/null && base64 --help 2>&1 | grep -q -- '-w'; then
    auth_b64="$(printf 'AWS:%s' "${token}" | base64 -w0)"
  else
    auth_b64="$(printf 'AWS:%s' "${token}" | base64 | tr -d '\n')"
  fi
  tmp="$(mktemp)"
  jq --arg host "${registry}" --arg auth "${auth_b64}" \
    '.auths[$host] = {auth: $auth}' "${DOCKER_CONFIG}/config.json" >"${tmp}"
  mv "${tmp}" "${DOCKER_CONFIG}/config.json"

  # CLI plugins (buildx) installed next to the default config, which the
  # relocated DOCKER_CONFIG would otherwise hide.
  plugins_dir="${HOME}/.docker/cli-plugins"
  if [[ -d "${plugins_dir}" ]]; then
    case "${OSTYPE:-}" in
      msys* | cygwin*) plugins_dir="$(cygpath -m "${plugins_dir}")" ;;
    esac
    tmp="$(mktemp)"
    jq --arg dir "${plugins_dir}" '.cliPluginsExtraDirs = [$dir]' \
      "${DOCKER_CONFIG}/config.json" >"${tmp}"
    mv "${tmp}" "${DOCKER_CONFIG}/config.json"
  fi
  echo "==> ECR login configured for ${registry}"
}

prompt_secret_field() {
  local var_name="$1"
  local label="$2"
  local current="${3:-}"
  local input

  if [[ -n "${current}" ]]; then
    read -r -p "${label} [Enter keeps existing]: " input || true
    if [[ -z "${input}" ]]; then
      printf -v "${var_name}" '%s' "${current}"
      return 0
    fi
  else
    read -r -p "${label}: " input || true
  fi
  printf -v "${var_name}" '%s' "${input}"
}

prompt_multiline_or_file() {
  local var_name="$1"
  local label="$2"
  local current="${3:-}"
  local input

  echo "${label}"
  if [[ -n "${current}" ]]; then
    echo "  Enter keeps existing. Or path to a PEM file, or paste PEM then a line with only END"
  else
    echo "  Path to a PEM file, or paste PEM then a line with only END"
  fi
  read -r -p "> " input || true
  if [[ -z "${input}" && -n "${current}" ]]; then
    printf -v "${var_name}" '%s' "${current}"
    return 0
  fi
  if [[ -n "${input}" && -f "${input}" ]]; then
    printf -v "${var_name}" '%s' "$(cat "${input}")"
    return 0
  fi
  local body="${input}"$'\n'
  while IFS= read -r line; do
    [[ "${line}" == "END" ]] && break
    body+="${line}"$'\n'
  done
  printf -v "${var_name}" '%s' "${body%$'\n'}"
}

fill_app_secrets() {
  local secret_name current
  secret_name="$(tf_output app_secret_name)"
  current="$(aws secretsmanager get-secret-value \
    --secret-id "${secret_name}" \
    --query SecretString --output text)"

  local strava_id strava_secret verify_token path_secret
  local garmin_id garmin_secret garmin_path_secret
  local intervals_id intervals_secret intervals_path_secret intervals_webhook_secret
  local clerk_secret clerk_jwt clerk_webhook
  local oauth_state token_key

  oauth_state="$(echo "${current}" | jq -r '.OAUTH_STATE_SECRET // empty')"
  token_key="$(echo "${current}" | jq -r '.TOKEN_ENCRYPTION_KEY // empty')"

  echo ""
  echo "Update application secrets in Secrets Manager (${secret_name})."
  echo "Leave a prompt empty to keep the current value (when one exists)."
  echo ""

  prompt_secret_field strava_id "STRAVA_CLIENT_ID" \
    "$(echo "${current}" | jq -r '.STRAVA_CLIENT_ID // empty')"
  prompt_secret_field strava_secret "STRAVA_CLIENT_SECRET" \
    "$(echo "${current}" | jq -r '.STRAVA_CLIENT_SECRET // empty')"

  verify_token="$(echo "${current}" | jq -r '.STRAVA_WEBHOOK_VERIFY_TOKEN // empty')"
  path_secret="$(echo "${current}" | jq -r '.STRAVA_WEBHOOK_PATH_SECRET // empty')"
  if [[ -z "${verify_token}" ]]; then
    verify_token="$(openssl rand -base64 32)"
    echo "Generated STRAVA_WEBHOOK_VERIFY_TOKEN"
  else
    prompt_secret_field verify_token "STRAVA_WEBHOOK_VERIFY_TOKEN" "${verify_token}"
  fi
  if [[ -z "${path_secret}" ]]; then
    path_secret="$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)"
    echo "Generated STRAVA_WEBHOOK_PATH_SECRET"
  else
    prompt_secret_field path_secret "STRAVA_WEBHOOK_PATH_SECRET" "${path_secret}"
  fi

  prompt_secret_field garmin_id "GARMIN_CLIENT_ID" \
    "$(echo "${current}" | jq -r '.GARMIN_CLIENT_ID // empty')"
  prompt_secret_field garmin_secret "GARMIN_CLIENT_SECRET" \
    "$(echo "${current}" | jq -r '.GARMIN_CLIENT_SECRET // empty')"
  # Never generated: it must match the webhook URL saved in Garmin API Tools.
  prompt_secret_field garmin_path_secret "GARMIN_WEBHOOK_PATH_SECRET (as in the Garmin API Tools URL)" \
    "$(echo "${current}" | jq -r '.GARMIN_WEBHOOK_PATH_SECRET // empty')"

  prompt_secret_field intervals_id "INTERVALS_CLIENT_ID" \
    "$(echo "${current}" | jq -r '.INTERVALS_CLIENT_ID // empty')"
  prompt_secret_field intervals_secret "INTERVALS_CLIENT_SECRET" \
    "$(echo "${current}" | jq -r '.INTERVALS_CLIENT_SECRET // empty')"

  intervals_path_secret="$(echo "${current}" | jq -r '.INTERVALS_WEBHOOK_PATH_SECRET // empty')"
  if [[ -z "${intervals_path_secret}" ]]; then
    intervals_path_secret="$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)"
    echo "Generated INTERVALS_WEBHOOK_PATH_SECRET"
  else
    prompt_secret_field intervals_path_secret "INTERVALS_WEBHOOK_PATH_SECRET" \
      "${intervals_path_secret}"
  fi
  prompt_secret_field intervals_webhook_secret "INTERVALS_WEBHOOK_SECRET" \
    "$(echo "${current}" | jq -r '.INTERVALS_WEBHOOK_SECRET // empty')"

  prompt_secret_field clerk_secret "CLERK_SECRET_KEY" \
    "$(echo "${current}" | jq -r '.CLERK_SECRET_KEY // empty')"
  prompt_multiline_or_file clerk_jwt "CLERK_JWT_KEY (PEM)" \
    "$(echo "${current}" | jq -r '.CLERK_JWT_KEY // empty')"
  prompt_secret_field clerk_webhook "CLERK_WEBHOOK_SECRET" \
    "$(echo "${current}" | jq -r '.CLERK_WEBHOOK_SECRET // empty')"

  local updated
  updated="$(jq -n \
    --arg sid "${strava_id}" \
    --arg ssec "${strava_secret}" \
    --arg vfy "${verify_token}" \
    --arg path "${path_secret}" \
    --arg gid "${garmin_id}" \
    --arg gsec "${garmin_secret}" \
    --arg gpath "${garmin_path_secret}" \
    --arg iid "${intervals_id}" \
    --arg isec "${intervals_secret}" \
    --arg ipath "${intervals_path_secret}" \
    --arg iwh "${intervals_webhook_secret}" \
    --arg oauth "${oauth_state}" \
    --arg tok "${token_key}" \
    --arg ck "${clerk_secret}" \
    --arg jwt "${clerk_jwt}" \
    --arg wh "${clerk_webhook}" \
    '{
      STRAVA_CLIENT_ID: $sid,
      STRAVA_CLIENT_SECRET: $ssec,
      STRAVA_WEBHOOK_VERIFY_TOKEN: $vfy,
      STRAVA_WEBHOOK_PATH_SECRET: $path,
      GARMIN_CLIENT_ID: $gid,
      GARMIN_CLIENT_SECRET: $gsec,
      GARMIN_WEBHOOK_PATH_SECRET: $gpath,
      INTERVALS_CLIENT_ID: $iid,
      INTERVALS_CLIENT_SECRET: $isec,
      INTERVALS_WEBHOOK_PATH_SECRET: $ipath,
      INTERVALS_WEBHOOK_SECRET: $iwh,
      OAUTH_STATE_SECRET: $oauth,
      TOKEN_ENCRYPTION_KEY: $tok,
      CLERK_SECRET_KEY: $ck,
      CLERK_JWT_KEY: $jwt,
      CLERK_WEBHOOK_SECRET: $wh
    }')"

  aws secretsmanager put-secret-value \
    --secret-id "${secret_name}" \
    --secret-string "${updated}" >/dev/null
  echo "==> App secrets updated"
}

# Keys the ECS task definitions read from the app secret that a secret written by an
# older deploy may lack; each missing one is added empty.
OPTIONAL_APP_SECRET_KEYS=(GARMIN_CLIENT_ID GARMIN_CLIENT_SECRET GARMIN_WEBHOOK_PATH_SECRET)

ensure_app_secret_keys() {
  local secret_name current updated keys
  secret_name="$(tf_output app_secret_name)"
  current="$(aws secretsmanager get-secret-value \
    --secret-id "${secret_name}" \
    --query SecretString --output text)"
  keys="$(printf '%s\n' "${OPTIONAL_APP_SECRET_KEYS[@]}" | jq -R . | jq -s .)"
  updated="$(echo "${current}" | jq --argjson keys "${keys}" \
    'reduce $keys[] as $k (.; if has($k) then . else .[$k] = "" end)')"
  if [[ "$(echo "${current}" | jq -S .)" != "$(echo "${updated}" | jq -S .)" ]]; then
    aws secretsmanager put-secret-value \
      --secret-id "${secret_name}" \
      --secret-string "${updated}" >/dev/null
    echo "==> Added missing app secret keys (empty): ${OPTIONAL_APP_SECRET_KEYS[*]}"
  fi
}

wait_for_ecs_task() {
  local cluster="$1"
  local task_arn="$2"
  local status exit_code reason project_env

  echo "==> Waiting for task ${task_arn##*/} to stop..."
  while true; do
    status="$(aws ecs describe-tasks \
      --cluster "${cluster}" \
      --tasks "${task_arn}" \
      --query 'tasks[0].lastStatus' \
      --output text)"
    if [[ "${status}" == "STOPPED" ]]; then
      break
    fi
    sleep 5
  done

  exit_code="$(aws ecs describe-tasks \
    --cluster "${cluster}" \
    --tasks "${task_arn}" \
    --query 'tasks[0].containers[0].exitCode' \
    --output text)"
  reason="$(aws ecs describe-tasks \
    --cluster "${cluster}" \
    --tasks "${task_arn}" \
    --query 'tasks[0].stoppedReason' \
    --output text)"

  if [[ "${exit_code}" != "0" ]]; then
    project_env="$(tf_output ecs_cluster_name)"
    echo "error: migration task failed (exit=${exit_code}, reason=${reason})" >&2
    echo "Logs: aws logs tail /ecs/${project_env}/migration --since 15m" >&2
    exit 1
  fi
  echo "==> Migration finished successfully"
}

run_migration_task() {
  local cluster subnets sg task_def task_arn

  cluster="$(tf_output ecs_cluster_name)"
  subnets="$(tf output -json private_subnet_ids | jq -r 'join(",")')"
  sg="$(tf_output app_security_group_id)"
  task_def="$(aws ecs describe-task-definition \
    --task-definition "$(tf_output ecs_migration_task_family)" \
    --query 'taskDefinition.taskDefinitionArn' \
    --output text)"

  echo "==> Running migration task (${task_def})"
  task_arn="$(aws ecs run-task \
    --cluster "${cluster}" \
    --launch-type FARGATE \
    --task-definition "${task_def}" \
    --network-configuration "awsvpcConfiguration={subnets=[${subnets}],securityGroups=[${sg}],assignPublicIp=DISABLED}" \
    --query 'tasks[0].taskArn' \
    --output text)"

  if [[ -z "${task_arn}" || "${task_arn}" == "None" ]]; then
    echo "error: run-task did not return a task ARN (image missing from ECR?)" >&2
    exit 1
  fi

  wait_for_ecs_task "${cluster}" "${task_arn}"
}
