# Deploy (Cloudflare HTTPS + Clerk SSO)

Bring up the full stack on AWS Academy: SPA + API on one HTTPS hostname, Clerk sign-in, Strava OAuth.

| Script | Purpose |
|--------|---------|
| [`deploy.sh`](./deploy.sh) | Apply infra → secrets → build/push images → migrate → scale API/worker/frontend |
| [`teardown.sh`](./teardown.sh) | Destroy the stack but **keep** the app Secrets Manager secret and the ACM certificate |

**ALB routing:** `/*` → SPA (nginx); `/api/*`, `/docs*`, `/openapi.json`, `/redoc*` → API.

**Recommended hostname:** a subdomain of an existing Cloudflare zone (e.g. `app.example.com`), so a marketing/landing site can stay on the apex.

---

## Prerequisites

- `aws` CLI, `terraform` ≥ 1.5, `docker`, `jq`
- **Windows:** run the scripts in **Git Bash** (not PowerShell; there `bash` starts WSL).
  Install the Windows builds with
  `winget install -e --id Amazon.AWSCLI`, `winget install -e --id Hashicorp.Terraform`
  and `winget install -e --id jqlang.jq`, and start Docker Desktop. In Git Bash, prefix
  commands whose arguments start with `/` (e.g. `aws logs tail /ecs/…`) with
  `MSYS_NO_PATHCONV=1`, or Git Bash rewrites them into Windows paths.
- AWS credentials: `aws sts get-caller-identity`
- **AWS Academy / Vocareum:** stack reuses `LabRole` (`iam:CreateRole` is denied)
- A domain in Cloudflare (Free plan is fine)
- A Clerk application (API keys + JWT public key)
- A Strava API application (for Connect Strava)
- Optional: a Garmin Connect Developer Program app (for Connect Garmin)

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` before deploying:

```hcl
domain_name              = "app.yourdomain.com"          # Cloudflare subdomain
clerk_authorized_parties = "https://app.yourdomain.com"  # must match the SPA origin
```

Also set the Clerk publishable key in `frontend/.env` (used by `deploy.sh` as a Docker build-arg — not a Terraform variable):

```bash
# frontend/.env
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...
```

`FRONTEND_URL` and the Strava and Garmin redirect URIs on ECS are derived from `domain_name` automatically (`https://<domain_name>`).

---

## Step-by-step

### 1. Create the ACM certificate

```bash
cd infra
terraform init
terraform apply -target=aws_acm_certificate.api
```

### 2. Prove domain ownership in Cloudflare (ACM validation)

```bash
terraform output acm_validation_records
```

In Cloudflare → your zone → **DNS** → **Add record** for each entry:

| Field | Value |
|-------|--------|
| Type | `CNAME` |
| Name | Prefer the left-hand label only, e.g. `_hash.app` (Cloudflare appends the zone). Pasting the full FQDN is OK if the preview does **not** show `….online.online`. |
| Target | The `value` from Terraform (ends with `acm-validations.aws.`) — copy exactly |
| Proxy | **DNS only** (grey cloud) |
| TTL | Auto |

Wait until the certificate is **Issued**:

```bash
aws acm describe-certificate \
  --certificate-arn "$(terraform output -raw acm_certificate_arn)" \
  --region "$(grep aws_region terraform.tfvars | cut -d'"' -f2)" \
  --query 'Certificate.Status' --output text
```

Expect: `ISSUED` (not `PENDING_VALIDATION`). Usually a few minutes after the CNAME is correct.

### 3. Configure Clerk (SSO) for the app origin

In the [Clerk Dashboard](https://dashboard.clerk.com) for your application:

1. **API Keys** — copy Publishable key (`pk_…`) into `frontend/.env` as `VITE_CLERK_PUBLISHABLE_KEY`.
2. **API Keys** — copy Secret key (`sk_…`); you will paste it into `./deploy.sh` secrets later.
3. **API Keys** → **Show JWT public key** → PEM — paste during secrets prompt as `CLERK_JWT_KEY`.
4. **Configure** → paths / domains:
   - Add `https://app.yourdomain.com` as an allowed origin / application URL / redirect URL (wording varies by Clerk UI).
5. Ensure `clerk_authorized_parties` in tfvars is exactly that origin (scheme + host, no trailing slash).

Optional: Clerk webhooks → endpoint `https://app.yourdomain.com/api/webhooks/clerk` (or whatever path the API exposes); copy the Svix signing secret into secrets as `CLERK_WEBHOOK_SECRET`.

### 4. Configure Strava callback domain

In [Strava API Application settings](https://www.strava.com/settings/api):

- **Authorization Callback Domain:** `app.yourdomain.com`  
  (domain only — no `https://`, no path)

The app sends:

`https://app.yourdomain.com/api/providers/strava/callback`

That host must match the callback domain. Localhost and production usually need **separate** Strava apps (one callback domain per app).

Copy Client ID / Client Secret for the secrets prompt in step 6.

### 5. Configure Garmin (optional)

Skip this step to deploy without Garmin: with `GARMIN_CLIENT_ID` empty, Garmin stays
hidden and its connect URL answers 404.

On the app page in the Garmin developer portal:

- **Redirect URL:** `https://app.yourdomain.com/api/providers/garmin/callback`  
  (ECS sets `GARMIN_REDIRECT_URI` to this.)
- Copy the Client ID / Client Secret for the secrets prompt in step 6.

In **API Tools → Endpoint Configuration** (`https://apis.garmin.com/tools/endpoints`):

1. Pick a random webhook path secret, e.g.
   `openssl rand -base64 32 | tr -d '/+=' | head -c 32`.
2. Save `https://app.yourdomain.com/api/webhooks/garmin/<path secret>` as the URL of
   these three notification types, and mark each **Enabled**:
   - **Activity Files**
   - **Deregistrations**
   - **User Permissions Change**

   Leave every other type disabled.
3. Enter the same path secret at the `GARMIN_WEBHOOK_PATH_SECRET` prompt in step 6.
   `deploy.sh` never generates it, because it must match the saved URL. To change it,
   update the three URLs in API Tools as well.

Saving the endpoints starts Garmin's review of the domain; no notifications arrive until
it passes. If the `app` record is proxied (orange cloud), add a Cloudflare rule that
skips bot checks for `/api/webhooks/garmin/`, so Garmin's posts aren't challenged.

**Before planned downtime** with connected Garmin users (a teardown included), check
**On Hold** for the endpoints in API Tools: Garmin keeps the notifications and delivers
them once it is unchecked again. Never uncheck **Enabled** for this: that drops every
queued notification.

### 6. Deploy

```bash
./deploy.sh
```

When asked, enter/update Secrets Manager values (empty Enter keeps existing):

- `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET`
- `GARMIN_CLIENT_ID` / `GARMIN_CLIENT_SECRET` and `GARMIN_WEBHOOK_PATH_SECRET` (step 5;
  leave them empty to deploy without Garmin)
- Clerk `CLERK_SECRET_KEY`, `CLERK_JWT_KEY` (PEM file path or paste until a line `END`), `CLERK_WEBHOOK_SECRET`
- Strava's webhook path/verify tokens are auto-generated if missing

The ECS tasks read every key above from the app secret, and won't start while one is
missing. When the secrets prompt is skipped, `deploy.sh` adds any missing `GARMIN_*` key
to a secret kept from an older deploy, empty, which leaves Garmin off.

Useful flags:

```bash
./deploy.sh --fill-secrets   # always prompt for secrets
./deploy.sh --no-secrets     # reuse Secrets Manager as-is
./deploy.sh --skip-build     # do not rebuild/push images
./deploy.sh --skip-migrate   # skip Alembic task
./deploy.sh --yes            # terraform apply -auto-approve
```

### What `deploy.sh` does

1. `terraform init`
2. Imports the app secret and ACM certificate if they survived a previous teardown (the
   certificate's validation resource is recreated by apply, at once for an issued cert)
3. `terraform apply` with API/worker/frontend desired count **0** (waits on ACM validation only when minting a **new** cert)
4. Optional Secrets Manager fill
5. Builds and pushes **api**, **worker**, **migration**, **frontend** to ECR  
   Frontend: `--build-arg VITE_CLERK_PUBLISHABLE_KEY=…` and empty `VITE_API_BASE_URL` (same-origin `/api`)
6. One-off Fargate migration (`alembic upgrade head`)
7. Scales API, worker, and frontend to **1**
8. Prints the app URL

### 7. Point the subdomain at the ALB

```bash
terraform output -raw alb_dns_name
```

Cloudflare → **DNS** → **Add record** (or edit the `app` record if you used a placeholder):

| Field | Value |
|-------|--------|
| Type | `CNAME` |
| Name | `app` (→ `app.yourdomain.com`) |
| Target | ALB DNS name from the output (e.g. `runsummarizer-dev-….elb.amazonaws.com`) |
| Proxy | **DNS only** (grey cloud) while validating |
| TTL | Auto |

Do **not** confuse this with the ACM validation CNAME from step 2 — you need **both**.

Optional later: orange-cloud the `app` record and set Cloudflare SSL/TLS mode to **Full (strict)**.

### 8. Smoke test

Prefer a network that does not filter new domains (campus firewalls often block them as “high-risk”).

```bash
APP_URL=$(terraform output -raw alb_url)   # https://app.yourdomain.com when domain_name is set
curl -sS -o /dev/null -w '%{http_code}\n' "$APP_URL/"
curl -sS "$APP_URL/api/health"
curl -sS "$APP_URL/api/health/ready"
```

| Endpoint | Expect |
|----------|--------|
| `/` | `200` (SPA) |
| `/api/health` | `{"status":"ok"}` |
| `/api/health/ready` | postgres + secrets ok |
| `/docs` | `200` |
| Browser | Clerk sign-in works; Strava connect does not return `redirect_uri` invalid |

Logs:

```bash
CLUSTER=$(terraform output -raw ecs_cluster_name)
aws logs tail "/ecs/${CLUSTER}/api" --follow
aws logs tail "/ecs/${CLUSTER}/frontend" --follow
aws logs tail "/ecs/${CLUSTER}/worker" --follow
aws logs tail "/ecs/${CLUSTER}/migration" --since 30m
```

---

## Frontend image / env

- Do **not** copy `frontend/.env` into the image (`.dockerignore` excludes it).
- `deploy.sh` reads `VITE_CLERK_PUBLISHABLE_KEY` from the environment or `frontend/.env`, then passes it as a Docker **build-arg** (with empty `VITE_API_BASE_URL` for same-origin `/api`).
- Local `npm run dev` uses `frontend/.env`; empty `VITE_API_BASE_URL` uses the Vite `/api` proxy.
- Local Compose always bakes `VITE_API_BASE_URL=http://localhost:8000` (split ports). Pass `VITE_CLERK_PUBLISHABLE_KEY` via the host env or a root `.env`.

---

## Teardown

```bash
cd infra
./teardown.sh
# or
./teardown.sh --yes
```

1. Confirms (type `destroy`, unless `--yes`)
2. Removes from **Terraform state only** (AWS objects stay):
   - app secret (+ related `random_password` resources)
   - ACM certificate + validation (when `domain_name` is set)
3. `terraform destroy` — VPC, NAT, ALB, RDS, ECS, ECR, logs, `postgres_dsn` secret, etc.

**Kept:** app secret (`runsummarizer/dev/app` by default); ACM cert for `domain_name`.  
**Not kept:** RDS data, ECR images, networking, ALB (so the `app` → ALB CNAME must be updated next deploy).

With Garmin users connected, put the Garmin endpoints **On Hold** first (step 5).

Leave the **ACM validation** CNAMEs in Cloudflare — they stay valid for the kept cert.  
Remove or rewrite the **`app` → ALB** CNAME after the next deploy (new ALB DNS name).

Next `./deploy.sh` imports the leftover secret and ACM cert before apply (no new cert / no new validation records). Cost: NAT + ALB + RDS burn Academy credits while up — tear down between sessions.

---

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| ACM stuck `PENDING_VALIDATION` | Wrong/missing validation CNAME, or proxied (must be DNS only); Target typo |
| New ACM cert after every teardown | Old behavior; current teardown keeps the cert — ensure `./deploy.sh` imports it |
| `Could not resolve host: app.…` | Missing `app` → ALB CNAME, or still pointing at `placeholder` |
| Browser “Web Page Blocked” / high-risk | Campus/corp firewall — try hotspot/home; app can still be healthy |
| Task starts then stops | Missing/invalid Clerk secret or PEM — `--fill-secrets` and redeploy |
| Task fails to start: `GARMIN_…` key not found in the secret | App secret edited by hand without the key — `--fill-secrets` and redeploy |
| No Garmin activities arrive | Endpoint domain review not passed yet; path secret differs from the API Tools URL; endpoints On Hold; Cloudflare challenging `/api/webhooks/garmin/` |
| Migration task fails | `/ecs/<cluster>/migration` logs; image not in ECR; DSN/SG |
| Ready 503 postgres | Re-run without `--skip-migrate` |
| SPA 503 / frontend unhealthy | Rebuild frontend image; frontend SG must allow ALB → 8080 |
| Clerk 401 / `azp` mismatch | `clerk_authorized_parties` ≠ `https://<domain_name>`; origin missing in Clerk Dashboard |
| Strava `redirect_uri` / `invalid` | Callback domain in Strava must be `app.yourdomain.com` (no scheme/path) |
| `VITE_CLERK_PUBLISHABLE_KEY is empty` | Set `pk_…` in `frontend/.env` (or export it) before build |
| `iam:CreateRole` AccessDenied | Expected on Academy — use `LabRole` |
| `pass not initialized` on docker login | Handled by deploy.sh via temp `DOCKER_CONFIG` |
| Secret already exists on apply | App secret: deploy imports it. `postgres_dsn`: deploy force-deletes orphans in recovery window |

### HTTP-only (no Cloudflare)

Omit `domain_name` for a raw ALB HTTP URL. Strava OAuth/webhooks and some Clerk setups are unreliable without HTTPS — use the Cloudflare path above for a real demo.
