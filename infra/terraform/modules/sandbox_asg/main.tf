# Code-execution runners (docs/24 §8): EC2 hosts in the isolated subnets (no internet route),
# Docker + gVisor (runsc); the runner container launches sandboxes with networking disabled.
# The api/worker reach it through an internal NLB on 8090 with a bearer token.
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-${var.architecture == "arm64" ? "arm64" : "x86_64"}"
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name_prefix        = "${var.name}-"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "ecr" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_role_policy" "token" {
  name = "read-runner-token"
  role = aws_iam_role.this.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [var.token_secret_arn] }]
  })
}

resource "aws_iam_instance_profile" "this" {
  name_prefix = "${var.name}-"
  role        = aws_iam_role.this.name
}

resource "aws_security_group" "this" {
  name_prefix = "${var.name}-"
  description = "Sandbox runner hosts"
  vpc_id      = var.vpc_id
  ingress {
    description = "Runner API from the app subnets (via the internal NLB, client IP preserved)"
    from_port   = 8090
    to_port     = 8090
    protocol    = "tcp"
    cidr_blocks = var.client_cidrs
  }
  egress {
    description = "VPC only (endpoints for ECR, S3, Secrets Manager, logs, SSM)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }
  lifecycle {
    create_before_destroy = true
  }
}

locals {
  registry  = split("/", var.runner_image)[0]
  user_data = <<-SH
    #!/bin/bash
    set -euo pipefail
    dnf install -y docker
    # gVisor from the S3-hosted release is unreachable without internet; bake it into a custom AMI
    # or mirror it. When absent the runner refuses to start with SANDBOX_RUNTIME=runsc.
    if [ -x /usr/local/bin/runsc ]; then
      /usr/local/bin/runsc install
    fi
    systemctl enable --now docker
    REGION=${var.region}
    aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin ${local.registry}
    TOKEN=$(aws secretsmanager get-secret-value --region "$REGION" --secret-id ${var.token_secret_arn} --query SecretString --output text | python3 -c 'import json,sys; print(json.load(sys.stdin)["SANDBOX_RUNNER_TOKEN"])')
    docker pull ${var.sandbox_image}
    docker pull ${var.runner_image}
    docker run -d --name sandbox-runner --restart unless-stopped -p 8090:8090 \
      -v /var/run/docker.sock:/var/run/docker.sock --user 0:0 \
      -e APP_ENV=production -e SANDBOX_RUNTIME=runsc \
      -e SANDBOX_IMAGE=${var.sandbox_image} -e SANDBOX_RUNNER_TOKEN="$TOKEN" \
      ${var.runner_image}
  SH
}

resource "aws_launch_template" "this" {
  name_prefix            = "${var.name}-"
  image_id               = var.ami_id != null ? var.ami_id : data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  vpc_security_group_ids = [aws_security_group.this.id]
  user_data              = base64encode(local.user_data)
  iam_instance_profile {
    arn = aws_iam_instance_profile.this.arn
  }
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1 # sandboxes can't reach instance credentials
  }
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size = 40
      volume_type = "gp3"
      encrypted   = true
    }
  }
  tag_specifications {
    resource_type = "instance"
    tags          = { Name = var.name }
  }
}

resource "aws_lb" "this" {
  name               = var.name
  internal           = true
  load_balancer_type = "network"
  subnets            = var.subnet_ids
}

resource "aws_lb_target_group" "this" {
  name        = var.name
  port        = 8090
  protocol    = "TCP"
  vpc_id      = var.vpc_id
  target_type = "instance"
  health_check {
    protocol = "HTTP"
    path     = "/healthz"
    port     = "8090"
  }
}

resource "aws_lb_listener" "this" {
  load_balancer_arn = aws_lb.this.arn
  port              = 8090
  protocol          = "TCP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}

resource "aws_autoscaling_group" "this" {
  name_prefix               = "${var.name}-"
  min_size                  = var.min_size
  max_size                  = var.max_size
  desired_capacity          = var.min_size
  vpc_zone_identifier       = var.subnet_ids
  target_group_arns         = [aws_lb_target_group.this.arn]
  health_check_type         = "ELB"
  health_check_grace_period = 300
  launch_template {
    id      = aws_launch_template.this.id
    version = "$Latest"
  }
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
    }
  }
  tag {
    key                 = "Name"
    value               = var.name
    propagate_at_launch = true
  }
}
