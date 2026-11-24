# Secrets live in SSM Parameter Store, NOT in git and NOT in Terraform state.
# Terraform only creates the empty slots (placeholder value, ignore_changes). You set the real values once, by hand:
#   aws ssm put-parameter --name /conduit/postgres_password --type SecureString --overwrite --value '...'
# deploy.sh reads everything under /conduit at every deploy (so rotating a secret = put-parameter + redeploy).
locals {
  secrets = ["postgres_password", "rabbit_password", "admin_token", "ghcr_token"]
}

resource "aws_ssm_parameter" "secret" {
  for_each = toset(local.secrets)
  name     = "/conduit/${each.key}"
  type     = "SecureString"
  value    = "CHANGE_ME"
  lifecycle { ignore_changes = [value] }
}

# non-secret settings
resource "aws_ssm_parameter" "backup_bucket" {
  name  = "/conduit/backup_bucket"
  type  = "String"
  value = aws_s3_bucket.backups.bucket
}
resource "aws_ssm_parameter" "ghcr_owner" {
  name  = "/conduit/ghcr_owner"
  type  = "String"
  value = lower(split("/", var.github_repo)[0])
}
resource "aws_ssm_parameter" "domain" {
  name  = "/conduit/domain"
  type  = "String"
  value = "CHANGE_ME" # your hostname, set with put-parameter once you have chosen it
  lifecycle { ignore_changes = [value] }
}
