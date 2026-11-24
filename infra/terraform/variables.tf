variable "region" {
  type    = string
  default = "us-east-1"
}
variable "instance_type" {
  description = "ARM64 (Graviton). t4g.small = 2 vCPU, 2 GB RAM."
  type        = string
  default     = "t4g.small"
}
variable "root_volume_gb" {
  type    = number
  default = 20
}
variable "github_repo" {
  description = "owner/name of the repo allowed to deploy through OIDC"
  type        = string
  default     = "PRAJINRAJ-RANAWAT/Conduit"
}
variable "create_github_oidc_provider" {
  description = "Set to false if this AWS account already has the token.actions.githubusercontent.com OIDC provider"
  type        = bool
  default     = true
}
variable "budget_email" {
  description = "Where the Budgets alarm emails go"
  type        = string
}
variable "budget_usd" {
  description = "Monthly cost limit that triggers the alarms"
  type        = number
  default     = 20
}
variable "backup_retention_days" {
  type    = number
  default = 14
}
