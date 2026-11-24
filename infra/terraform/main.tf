# ONE small ARM64 server running the whole Docker Compose stack. No SSH: you get a shell through SSM Session Manager.

data "aws_caller_identity" "me" {}

# Latest Amazon Linux 2023 for ARM64 (the AMI id comes from a public AWS parameter, so it is never stale)
data "aws_ssm_parameter" "ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

data "aws_vpc" "default" { default = true }
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Only web traffic comes in. Port 22 is NOT open.
resource "aws_security_group" "web" {
  name_prefix = "conduit-web-"
  description = "HTTP and HTTPS only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description      = "HTTP (certificate challenge and redirect to HTTPS)"
    from_port        = 80
    to_port          = 80
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }
  ingress {
    description      = "HTTPS"
    from_port        = 443
    to_port          = 443
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }
  egress {
    description = "all outbound (image pulls, SSM, S3, certificates)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  lifecycle { create_before_destroy = true }
}

resource "aws_instance" "conduit" {
  ami                    = data.aws_ssm_parameter.ami.value
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile   = aws_iam_instance_profile.conduit.name
  user_data              = file("${path.module}/userdata.sh")

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }
  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_gb
    encrypted   = true
  }
  tags = { Name = "conduit" }
}

# A fixed public address, so DNS and the TLS certificate keep working across restarts
resource "aws_eip" "conduit" {
  domain   = "vpc"
  instance = aws_instance.conduit.id
  tags     = { Name = "conduit" }
}
