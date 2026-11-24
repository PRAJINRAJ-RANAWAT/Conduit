# CHECKPOINT (2026-11-24): stopped before anything is created in AWS

## Done and merged to main (CI green)
- Step 2: 2 gateways behind NGINX, 3 workers, Redis pub/sub key revocation, breaker state in Redis, Postgres-down chaos (+fix), limiter accuracy, CI. Results: `bench/results/STEP2_SUMMARY.md`
- Step 3: fair dispatcher (DRR, max in flight, advisory-lock leader, reconciler), provider-budget priority, noisy-neighbour proof, dispatcher-kill chaos. Results: `bench/results/STEP3_SUMMARY.md`, `chaos/RESULTS.md`
- Step 4 (code only): Terraform (validated), prod compose, NGINX/TLS, deploy.sh with rolling restart and rollback, backup/restore scripts, release workflow, `docs/DEPLOYMENT.md`

## NOT done
- Step 4 g-i: `terraform plan` and `apply`, live URL, HTTPS check, live smoke test. **No AWS credentials on this machine, nothing in AWS exists.**
- Step 5 (benchmarks on AWS, separate load-generator machine, AWS chaos, docs/BENCHMARKS.md, SCALABILITY.md, FAILURE_TESTING.md, final RESUME rewrite) not started.
- Final report is not written (needs the live URL and the real monthly cost).

## What the user must do next (nothing here has been done)
1. Log in to AWS (`aws sso login` or access keys) and tell Claude the profile name and region.
2. Give a budget alarm email (default limit $20/month).
3. Say whether you have a domain, or want a free `<ip>.sslip.io` name.
4. Say whether this is a NEW AWS account on the Free Plan (decides if ~$17.5/month is covered by credits).
5. Say whether the GHCR packages will be public, or provide a read-only token.
6. Reply with an explicit "yes, apply" ONLY after reading the `terraform plan` output Claude shows.

## What Claude does after that (in this order, asking before each costly step)
1. Install the AWS CLI if needed; `terraform apply -target=aws_budgets_budget.monthly`; confirm the budget exists.
2. `terraform plan`, show the output and the cost; WAIT for approval; then apply.
3. Set SSM secrets, DNS, GitHub repo variables, `DEPLOY_ENABLED=true`, first deploy, `init-tls.sh`, HTTPS check, smoke test.
4. Step 5: ask before starting the second (load-generator) instance; ladder 100/1k/5k/10k users with zero-latency and ~300 ms mock; find and fix top 2 bottlenecks; AWS chaos; docs; RESUME.
5. Final report.

## Handy facts
- Repo: https://github.com/PRAJINRAJ-RANAWAT/Conduit (work through PRs, never push to main)
- Local stack: `docker compose up -d --build` (UI :3100, API :8080). Tests: `.venv/bin/pytest`. Chaos: `./chaos/run_all.sh`. Benchmarks: `./bench/run.sh <label> "<note>"`
- Terraform binary is at `/tmp/tfbin/terraform` (not installed system-wide; re-download if /tmp was cleared)
- Ports 3000 and 8000 on the user's machine belong to other programs; Conduit uses 3100 and 8080
