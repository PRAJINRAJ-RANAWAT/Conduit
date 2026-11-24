# Deploying Conduit to AWS

**Status: written and rehearsed locally, NOT yet applied to AWS.** Nothing in this file has been run against a real AWS account. What was
verified on a laptop is listed at the bottom ("What was verified, and what was not").

## What gets created
One EC2 instance (ARM64 `t4g.small`, 2 vCPU, 2 GB RAM) running the whole Docker Compose stack, plus:

| Piece | File | Purpose |
|---|---|---|
| EC2 + Elastic IP + 20 GB encrypted gp3 disk | `infra/terraform/main.tf` | the server and a fixed public address |
| Security group | `main.tf` | only 80 and 443 are open. **No SSH**: you get a shell with SSM Session Manager |
| IAM instance role | `iam.tf` | SSM access, read `/conduit/*` parameters, write backups to one bucket |
| SSM Parameter Store | `ssm.tf` | secrets (empty slots; values set by hand, never in git or Terraform state) |
| S3 backup bucket | `s3.tf` | private, encrypted, dumps expire after 14 days |
| AWS Budgets alarm | `budgets.tf` | emails at 50% / 80% actual and 100% forecast of the monthly limit |
| GitHub OIDC role | `github_oidc.tf` | CI deploys with a short-lived token, **no stored AWS keys** |
| Prod compose, NGINX, scripts | `deploy/prod/` | what runs on the server |
| CI: images + deploy | `.github/workflows/release.yml` | multi-arch images to GHCR; deploy over SSM |

## Expected cost (ESTIMATE, not measured)
us-east-1, running 24/7 for a 730-hour month:

| Item | Calculation | Per month |
|---|---|---|
| EC2 `t4g.small` | $0.0168/h x 730 | about $12.26 |
| Public IPv4 address (the Elastic IP) | $0.005/h x 730 | about $3.65 |
| 20 GB gp3 disk | 20 x $0.08 | about $1.60 |
| S3 backups, SSM parameters, Budgets | tiny dumps (hundreds of KB), standard parameters are free, first budgets are free | about $0 |
| **Total** | | **about $17.5 per month**, plus data transfer and tax |

Prices come from third-party calculators and AWS's pricing pages and can change; check the AWS console before applying:
[t4g.small price](https://calculator.holori.com/aws/ec2/t4g.small/us-east-1), [public IPv4 charge](https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights).
If your account is a *new* account on the AWS Free Plan, these charges are drawn from your free credits (up to $200 for six months, per
[AWS](https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan)), and `t4g.small` is listed as eligible. I could not
confirm your account type from here, so check the console's "Free tier eligible" label. When the credits or six months run out, you pay the amounts above.
The default budget alarm is **$20/month** (`budget_usd`).

## Memory budget (measured on a laptop, ARM64 Linux containers)
Peak resident memory per container while the k6 load test ran against the **production compose file** (with its limits), sampled with `docker stats`
every few seconds, so a very short spike could be missed. Source: `bench/results/prod-rehearsal/memory-peak-mib.json`.

| Container | Peak MiB | `mem_limit` |
|---|---|---|
| rabbitmq | 195 | 384 |
| postgres | 71 | 256 |
| gateway-1 | 61 | 160 |
| gateway-2 | 61 | 160 |
| worker x2 | 51 + 50 | 100 each |
| mock-a / mock-b | 34 / 32 | 64 each |
| web | 33 | 96 |
| dispatcher x2 | 25 + 25 | 64 each |
| nginx | 16 | 32 |
| redis | 15 | 128 (maxmemory 96 MB) |
| **Sum of peaks** | **671** | 2,000 if every limit were hit |

The server has about 1.9 GiB usable. The stack peaked around 0.67 GiB, so there is room for the operating system, Docker and the page cache,
and a 2 GB swap file (created at first boot) is the safety net. Load on the real instance may differ (different CPU, real traffic), so this is the number to
re-check after the first deploy (`docker stats` over an SSM session). No container was OOM-killed or restarted in the rehearsal.

**Decision: Postgres stays on the instance** (71 MiB peak, 20 GB disk, nightly dumps to S3) rather than moving to Neon's free tier. Reasons: the
memory budget has plenty of room, it keeps the whole stack in one Compose file that can move to any VM, and it avoids a second provider and a network hop
on every request. The cost is that I run the backups myself (below). If a later load test shows memory pressure, Neon is the first thing to move.

## Run steps (in this order)
You need: an AWS account, the AWS CLI logged in (`aws sso login` or access keys), Terraform >= 1.6, a hostname, and push access to the repo.

1. **Configure.** `cd infra/terraform && cp terraform.tfvars.example terraform.tfvars`; set `budget_email`. If your account already has the GitHub OIDC provider, set `create_github_oidc_provider = false`.
2. **Budget first.** `terraform init && terraform apply -target=aws_budgets_budget.monthly`, then check it exists:
   `aws budgets describe-budgets --account-id $(aws sts get-caller-identity --query Account --output text)`. Confirm the email subscription if AWS asks.
3. **Plan, then read it.** `terraform plan -out=conduit.tfplan`. Review every resource. Nothing is created yet.
4. **Apply.** `terraform apply conduit.tfplan`. Note the outputs (`public_ip`, `instance_id`, `deploy_role_arn`).
5. **Set the secrets** (once; the values never go in git):
   ```
   aws ssm put-parameter --name /conduit/postgres_password --type SecureString --overwrite --value "$(openssl rand -hex 24)"
   aws ssm put-parameter --name /conduit/rabbit_password   --type SecureString --overwrite --value "$(openssl rand -hex 24)"
   aws ssm put-parameter --name /conduit/admin_token       --type SecureString --overwrite --value "$(openssl rand -hex 24)"
   aws ssm put-parameter --name /conduit/domain            --type String       --overwrite --value "conduit.example.com"
   # only if the GHCR packages are private: a GitHub token with read:packages
   aws ssm put-parameter --name /conduit/ghcr_token        --type SecureString --overwrite --value "ghp_..."
   ```
6. **DNS.** Point your hostname's A record at `public_ip`. If you have no domain, a free wildcard-DNS name works: `<ip-with-dashes>.sslip.io` (for example `203-0-113-10.sslip.io`) resolves to that IP with no sign-up. Wait until `dig +short <hostname>` returns the IP.
7. **GitHub repo variables** (Settings > Secrets and variables > Actions > Variables): `AWS_DEPLOY_ROLE_ARN` (output), `AWS_REGION`, `INSTANCE_ID` (output), `DOMAIN`. Leave `DEPLOY_ENABLED` unset for now.
8. **First deploy.** Make sure CI has pushed images for the commit (merge to `main`, `images` job). Then set `DEPLOY_ENABLED=true` and re-run the "Images and deploy" workflow (or push a commit). It copies `deploy/prod/` to the instance and runs `deploy.sh`.
9. **TLS (once).** `aws ssm start-session --target <instance_id>`, then `sudo /opt/conduit/init-tls.sh <hostname> <your-email>`. It starts NGINX with a throw-away certificate, asks Let's Encrypt for the real one through the HTTP challenge, and reloads NGINX. Renewal runs from the `conduit-certbot.timer` systemd timer (twice a day).
10. **Check.** `curl -fsS https://<hostname>/healthz`, open `https://<hostname>/` in a browser, then send one chat request with a key (create a tenant first with the seed in `app/auth.py`, or use the demo keys, which are seeded at startup: **change or remove them for anything real**).

## How a deploy works (`.github/workflows/release.yml`, `deploy/prod/deploy.sh`)
1. Merge to `main` -> CI builds `conduit-app` and `conduit-web` for amd64 **and** arm64, pushes them to GHCR tagged with the git SHA.
2. The deploy job proves its identity to AWS with OIDC (a short-lived token, no stored keys) and assumes the deploy role, which can only run commands on this one instance.
3. It sends the `deploy/prod` files over SSM Run Command and runs `deploy.sh <sha>` on the server.
4. `deploy.sh` reads the secrets from SSM, pulls the new images (the running containers are untouched meanwhile), runs the migrations once with the new image (the schema is idempotent), then **restarts one gateway at a time**: recreate it, wait for `/readyz`, reload NGINX, then the next one. The other gateway serves during each restart.
5. If a gateway does not become ready within 60 seconds, the script **rolls back** to the previous image tag (stored in `/opt/conduit/.prev_tag`) and exits with an error, which fails the workflow.
6. The workflow finishes with a smoke test against the live HTTPS URL.

## Rollback
- **Automatic:** a failed health check during a deploy rolls back to the previous tag (above).
- **Manual, to any earlier version:** open a shell (`aws ssm start-session ...`) and run `sudo /opt/conduit/deploy.sh <older-git-sha>`. Images of recent versions stay on the disk for 72 hours; older ones are pulled again from GHCR.
- **Schema changes** are additive (`CREATE ... IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`), so an older image keeps working against a newer schema. A change that is not additive needs its own rollout plan.

## Backups and restore
- **Postgres:** `conduit-backup.timer` runs `/opt/conduit/backup.sh` at 03:15 UTC: `pg_dump -Fc` of the `conduit` database, uploaded to `s3://<bucket>/pg/`. The bucket deletes dumps after 14 days (`backup_retention_days`).
- **Redis:** append-only file on (`--appendonly yes --appendfsync everysec`) on a Docker volume: a crash loses at most about one second of writes. Redis holds only limiter state, caches and counters, which are safe to lose; it is not backed up to S3.
- **RabbitMQ:** queues are durable and messages persistent on a Docker volume. Postgres is the source of truth for jobs; the dispatcher's reconciler re-publishes lost work.
- **Restore test:** `deploy/prod/restore-test.sh <dump or s3://uri>` restores into a scratch database and compares row counts with the live one. To restore for real: stop the gateways, `dropdb`/`createdb conduit`, `pg_restore -d conduit < dump`, start the gateways.
- **Tested so far (local, real):** a `pg_dump -Fc` of the local database restored into a scratch database with matching row counts for tenants, api_keys, jobs (1,101), usage (14,138), prompt_versions (`docs/restore-test-local.log`). **Not yet tested:** the upload to and download from S3, and the systemd timer. Run the restore test against the first real S3 backup before relying on it.

## Secret rotation
Secrets live only in SSM Parameter Store under `/conduit/`. To rotate one: `aws ssm put-parameter --name /conduit/<name> --overwrite ...`, then redeploy (`deploy.sh` re-reads all parameters).
Two secrets need a matching change inside a service, because the service stores its own copy: **`postgres_password`** (also run `ALTER USER conduit PASSWORD '...'` in Postgres) and **`rabbit_password`** (also `rabbitmqctl change_password conduit ...`). Do those two with the stack up, then redeploy.
`admin_token` and `ghcr_token` need only the parameter change plus a redeploy. API keys are separate: revoke through `POST /admin/keys/revoke`.

## When the free plan ends (or you want to leave AWS)
The whole stack is one Docker Compose file, so it moves to any VM:
1. Create a Linux VM (ARM64 or x86-64, 2 GB RAM or more) with Docker and the compose plugin.
2. Copy `deploy/prod/` to `/opt/conduit`, create `.env` with the same variables `deploy.sh` builds from SSM (`POSTGRES_PASSWORD`, `RABBIT_PASSWORD`, `ADMIN_TOKEN`, `DOMAIN`, `GHCR_OWNER`, `IMAGE_TAG`, `BACKUP_BUCKET` if you keep S3 backups).
3. Restore the latest dump with `pg_restore` (above), run `init-tls.sh`, point DNS at the new IP.
4. To stop AWS charges: `terraform destroy` (it also removes the Elastic IP, which is billed even when idle). Download any backups you want first: the destroy removes the bucket only if it is empty, so empty it deliberately.
The multi-arch images mean the same tags run on x86-64 and ARM64 hosts.

## What was verified, and what was not
Verified on a laptop (real runs, nothing mocked):
- `terraform fmt` and `terraform validate` pass (this caught two invalid security-group descriptions, now fixed).
- The production compose file starts: 13 containers healthy with their memory limits; HTTPS (self-signed locally) works; `/healthz`, `/readyz` and the UI answer; HTTP redirects to HTTPS.
- A rolling restart of both gateways (the same steps as `deploy.sh`) while requests were flowing: **49 of 49 requests returned 200**. Small sample.
- Memory under the k6 load test (table above), no OOM kills.
- Database dump and restore (above).

NOT verified (needs a real AWS account):
- `terraform plan` / `apply` (no AWS credentials were available when this was written), the IAM policies' exact permissions, the OIDC trust, and SSM Run Command.
- `deploy.sh` end to end (it needs SSM Parameter Store and the metadata service); `init-tls.sh` and the real Let's Encrypt issuance; the systemd timers; the S3 backup upload.
- The multi-arch image build runs in CI on every PR (see the workflow run for the result), but the arm64 images have not run on a real Graviton instance.
