output "public_ip" {
  value = aws_eip.conduit.public_ip
}
output "instance_id" {
  value = aws_instance.conduit.id
}
output "deploy_role_arn" {
  description = "Put this in the GitHub repo variable AWS_DEPLOY_ROLE_ARN"
  value       = aws_iam_role.deploy.arn
}
output "backup_bucket" {
  value = aws_s3_bucket.backups.bucket
}
output "shell_command" {
  description = "Open a shell on the server (no SSH, no open port 22)"
  value       = "aws ssm start-session --target ${aws_instance.conduit.id} --region ${var.region}"
}
