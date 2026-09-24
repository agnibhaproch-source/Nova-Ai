# One Fargate workload: task definition, IAM roles, log group, security group and (optionally)
# a long-running service with CPU autoscaling, a load-balancer target and Service Connect.
# With service = false only the task definition exists (e.g. migrations run via `aws ecs run-task`).
data "aws_region" "current" {}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Execution role: pull the image, write logs, read the secrets injected into the container.
resource "aws_iam_role" "execution" {
  name_prefix        = "${var.name}-exec-"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "secrets" {
  count = length(var.secret_arns) > 0 ? 1 : 0
  name  = "read-secrets"
  role  = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = var.secret_arns
    }]
  })
}

# Task role: what the app itself may call (e.g. S3 for the api/worker).
resource "aws_iam_role" "task" {
  name_prefix        = "${var.name}-task-"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy" "task" {
  count  = var.task_policy_json == null ? 0 : 1
  name   = "app"
  role   = aws_iam_role.task.id
  policy = var.task_policy_json
}

resource "aws_security_group" "this" {
  name_prefix = "${var.name}-"
  description = "${var.name} tasks"
  vpc_id      = var.vpc_id
  egress {
    description = "Outbound (NAT for Groq, Razorpay, email; VPC for data stores)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "from" {
  for_each                     = var.port == null ? toset([]) : toset(var.ingress_security_group_ids)
  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = var.port
  to_port                      = var.port
  description                  = "App port"
}

locals {
  container = merge(
    {
      name        = var.name
      image       = var.image
      essential   = true
      environment = [for k in sort(keys(var.environment)) : { name = k, value = var.environment[k] }]
      secrets     = [for k in sort(keys(var.secrets)) : { name = k, valueFrom = var.secrets[k] }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.this.name
          awslogs-region        = data.aws_region.current.region
          awslogs-stream-prefix = var.name
        }
      }
      readonlyRootFilesystem = false
      stopTimeout            = var.stop_timeout_seconds
    },
    var.command == null ? {} : { command = var.command },
    var.port == null ? {} : { portMappings = [{ name = var.name, containerPort = var.port, protocol = "tcp" }] },
    var.health_check_command == null ? {} : {
      healthCheck = { command = var.health_check_command, interval = 15, timeout = 5, retries = 3, startPeriod = 30 }
    },
  )
}

resource "aws_ecs_task_definition" "this" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions    = jsonencode([local.container])
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }
}

resource "aws_ecs_service" "this" {
  count                              = var.service ? 1 : 0
  name                               = var.name
  cluster                            = var.cluster_arn
  task_definition                    = aws_ecs_task_definition.this.arn
  desired_count                      = var.min_count
  launch_type                        = "FARGATE"
  enable_execute_command             = true
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = var.target_group_arn == null ? null : 60

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.this.id]
    assign_public_ip = false
  }

  dynamic "load_balancer" {
    for_each = var.target_group_arn == null ? [] : [1]
    content {
      target_group_arn = var.target_group_arn
      container_name   = var.name
      container_port   = var.port
    }
  }

  dynamic "service_connect_configuration" {
    for_each = var.service_connect_namespace == null ? [] : [1]
    content {
      enabled   = true
      namespace = var.service_connect_namespace
      dynamic "service" {
        for_each = var.port == null ? [] : [1]
        content {
          port_name      = var.name
          discovery_name = var.name
          client_alias {
            port     = var.port
            dns_name = var.name
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [desired_count] # owned by autoscaling
  }
}

resource "aws_appautoscaling_target" "this" {
  count              = var.service && var.max_count > var.min_count ? 1 : 0
  service_namespace  = "ecs"
  resource_id        = "service/${var.cluster_name}/${aws_ecs_service.this[0].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.min_count
  max_capacity       = var.max_count
}

resource "aws_appautoscaling_policy" "cpu" {
  count              = length(aws_appautoscaling_target.this)
  name               = "${var.name}-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = "ecs"
  resource_id        = aws_appautoscaling_target.this[0].resource_id
  scalable_dimension = aws_appautoscaling_target.this[0].scalable_dimension
  target_tracking_scaling_policy_configuration {
    target_value       = var.cpu_target_percent
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
