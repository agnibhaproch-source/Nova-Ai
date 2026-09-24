# NOVA AI on AWS (docs/48): WAF → ALB → web (Next.js BFF) → api (FastAPI, via Service Connect);
# worker (arq); RDS PostgreSQL 16; ElastiCache Redis; S3 files; sandbox runners in isolated
# subnets. Groq is the only LLM provider and is only ever called by api/worker, never the browser.
locals {
  name       = "nova-${var.environment}"
  app_url    = "https://${var.domain}"
  image      = { for k in ["web", "api", "sandbox-runner", "sandbox-python"] : k => "${var.ecr_registry}/nova-${k}:${var.image_tag}" }
  secret_key = { for k in local.secret_keys : k => "${aws_secretsmanager_secret.app.arn}:${k}::" }
  secret_keys = [
    "DATABASE_URL", "REDIS_URL", "AUTH_SECRET", "API_PROXY_SHARED_SECRET", "SANDBOX_RUNNER_TOKEN",
    "GROQ_API_KEY", "SMTP_PASSWORD", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET", "SENTRY_DSN",
  ]
  # Settings shared by api, worker and migrate (docs/42).
  app_env = {
    APP_ENV              = "production"
    APP_URL              = local.app_url
    S3_BUCKET            = module.s3.bucket
    S3_REGION            = var.region
    S3_FORCE_PATH_STYLE  = "false"
    SANDBOX_RUNNER_URL   = module.sandbox.runner_url
    GROQ_KEY_MODE        = var.groq_key_mode
    GROQ_DEFAULT_MODEL   = "primary"
    GROQ_VISION_MODEL    = "vision"
    EMBEDDING_DIMENSIONS = "384"
    SMTP_HOST            = var.smtp_host
    SMTP_PORT            = tostring(var.smtp_port)
    SMTP_USERNAME        = var.smtp_username
    SMTP_FROM            = var.smtp_from
    SMTP_USE_TLS         = "true"
    RAZORPAY_KEY_ID      = var.razorpay_key_id
  }
  app_secrets = { for k in ["DATABASE_URL", "REDIS_URL", "AUTH_SECRET", "API_PROXY_SHARED_SECRET", "SANDBOX_RUNNER_TOKEN", "GROQ_API_KEY", "SMTP_PASSWORD", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET", "SENTRY_DSN"] : k => local.secret_key[k] }
  # The api/worker may only touch their own bucket.
  s3_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"], Resource = "${module.s3.arn}/*" },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = module.s3.arn },
    ]
  })
}

module "network" {
  source             = "../../modules/network"
  name               = local.name
  region             = var.region
  cidr               = var.vpc_cidr
  single_nat_gateway = var.single_nat_gateway
}

# ---- secrets -------------------------------------------------------------------------------
resource "random_password" "generated" {
  for_each = toset(["AUTH_SECRET", "API_PROXY_SHARED_SECRET", "SANDBOX_RUNNER_TOKEN"])
  length   = 64
  special  = false
}

resource "aws_secretsmanager_secret" "app" {
  name_prefix             = "${local.name}/app-"
  description             = "NOVA AI server-side secrets (never exposed to browsers or logs)"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    DATABASE_URL            = module.rds.database_url
    REDIS_URL               = module.redis.redis_url
    AUTH_SECRET             = random_password.generated["AUTH_SECRET"].result
    API_PROXY_SHARED_SECRET = random_password.generated["API_PROXY_SHARED_SECRET"].result
    SANDBOX_RUNNER_TOKEN    = random_password.generated["SANDBOX_RUNNER_TOKEN"].result
    GROQ_API_KEY            = var.groq_api_key
    SMTP_PASSWORD           = var.smtp_password
    RAZORPAY_KEY_SECRET     = var.razorpay_key_secret
    RAZORPAY_WEBHOOK_SECRET = var.razorpay_webhook_secret
    SENTRY_DSN              = var.sentry_dsn
  })
}

# ---- data stores ---------------------------------------------------------------------------
module "rds" {
  source                    = "../../modules/rds"
  name                      = local.name
  vpc_id                    = module.network.vpc_id
  subnet_ids                = module.network.private_subnet_ids
  client_security_group_ids = [module.api.security_group_id, module.worker.security_group_id, module.migrate.security_group_id]
  instance_class            = var.db_instance_class
  multi_az                  = var.db_multi_az
}

module "redis" {
  source                    = "../../modules/redis"
  name                      = local.name
  vpc_id                    = module.network.vpc_id
  subnet_ids                = module.network.private_subnet_ids
  client_security_group_ids = [module.api.security_group_id, module.worker.security_group_id]
  node_type                 = var.redis_node_type
}

module "s3" {
  source          = "../../modules/s3"
  bucket_name     = var.files_bucket_name
  allowed_origins = [local.app_url]
}

# ---- public entry: WAF → ALB (HTTPS) → web -------------------------------------------------
resource "aws_security_group" "alb" {
  name_prefix = "${local.name}-alb-"
  description = "Public HTTPS load balancer"
  vpc_id      = module.network.vpc_id
  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "HTTP (redirected to HTTPS)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    description = "To web tasks"
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_lb" "public" {
  name                       = local.name
  load_balancer_type         = "application"
  subnets                    = module.network.public_subnet_ids
  security_groups            = [aws_security_group.alb.id]
  idle_timeout               = 350 # long-lived SSE chat streams (docs/48 §1)
  drop_invalid_header_fields = true
  enable_deletion_protection = true
}

resource "aws_lb_target_group" "web" {
  name                          = "${local.name}-web"
  port                          = 3000
  protocol                      = "HTTP"
  vpc_id                        = module.network.vpc_id
  target_type                   = "ip"
  deregistration_delay          = 60
  load_balancing_algorithm_type = "least_outstanding_requests"
  health_check {
    path    = "/login"
    matcher = "200"
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.public.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.public.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      protocol    = "HTTPS"
      port        = "443"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_wafv2_web_acl" "this" {
  name  = local.name
  scope = "REGIONAL"
  default_action {
    allow {}
  }
  rule {
    name     = "aws-common"
    priority = 1
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
        # Chat messages and uploads legitimately exceed the 8 KB body inspection limit.
        rule_action_override {
          name = "SizeRestrictions_BODY"
          action_to_use {
            count {}
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aws-common"
      sampled_requests_enabled   = true
    }
  }
  rule {
    name     = "ip-rate-limit"
    priority = 2
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = var.waf_requests_per_5min_per_ip
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "ip-rate-limit"
      sampled_requests_enabled   = true
    }
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = local.name
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "alb" {
  resource_arn = aws_lb.public.arn
  web_acl_arn  = aws_wafv2_web_acl.this.arn
}

# ---- ECS -----------------------------------------------------------------------------------
resource "aws_ecs_cluster" "this" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_service_discovery_http_namespace" "this" {
  name = local.name
}

module "web" {
  source                     = "../../modules/ecs_service"
  name                       = "web"
  image                      = local.image["web"]
  cluster_arn                = aws_ecs_cluster.this.arn
  cluster_name               = aws_ecs_cluster.this.name
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.private_subnet_ids
  cpu                        = 512
  memory                     = 1024
  port                       = 3000
  ingress_security_group_ids = [aws_security_group.alb.id]
  target_group_arn           = aws_lb_target_group.web.arn
  service_connect_namespace  = aws_service_discovery_http_namespace.this.arn
  min_count                  = var.web_min
  max_count                  = var.web_max
  environment = {
    APP_ENV          = "production"
    APP_URL          = local.app_url
    API_INTERNAL_URL = "http://api:8000"
  }
  secrets     = { API_PROXY_SHARED_SECRET = local.secret_key["API_PROXY_SHARED_SECRET"] }
  secret_arns = [aws_secretsmanager_secret.app.arn]
}

module "api" {
  source                     = "../../modules/ecs_service"
  name                       = "api"
  image                      = local.image["api"]
  cluster_arn                = aws_ecs_cluster.this.arn
  cluster_name               = aws_ecs_cluster.this.name
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.private_subnet_ids
  cpu                        = 1024
  memory                     = 2048
  port                       = 8000
  ingress_security_group_ids = [module.web.security_group_id]
  service_connect_namespace  = aws_service_discovery_http_namespace.this.arn
  health_check_command       = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)\""]
  min_count                  = var.api_min
  max_count                  = var.api_max
  environment                = local.app_env
  secrets                    = local.app_secrets
  secret_arns                = [aws_secretsmanager_secret.app.arn]
  task_policy_json           = local.s3_policy
}

module "worker" {
  source                    = "../../modules/ecs_service"
  name                      = "worker"
  image                     = local.image["api"]
  command                   = ["arq", "app.workers.settings.WorkerSettings"]
  cluster_arn               = aws_ecs_cluster.this.arn
  cluster_name              = aws_ecs_cluster.this.name
  vpc_id                    = module.network.vpc_id
  subnet_ids                = module.network.private_subnet_ids
  cpu                       = 1024
  memory                    = 2048
  service_connect_namespace = aws_service_discovery_http_namespace.this.arn
  min_count                 = var.worker_min
  max_count                 = var.worker_max
  environment               = local.app_env
  secrets                   = local.app_secrets
  secret_arns               = [aws_secretsmanager_secret.app.arn]
  task_policy_json          = local.s3_policy
}

# Migrations: a task definition only. The deploy runs it once before updating the services:
#   aws ecs run-task --cluster <cluster> --task-definition migrate --launch-type FARGATE ...
module "migrate" {
  source       = "../../modules/ecs_service"
  name         = "migrate"
  service      = false
  image        = local.image["api"]
  command      = ["alembic", "upgrade", "head"]
  cluster_arn  = aws_ecs_cluster.this.arn
  cluster_name = aws_ecs_cluster.this.name
  vpc_id       = module.network.vpc_id
  subnet_ids   = module.network.private_subnet_ids
  cpu          = 512
  memory       = 1024
  environment  = local.app_env
  secrets      = local.app_secrets
  secret_arns  = [aws_secretsmanager_secret.app.arn]
}

module "sandbox" {
  source           = "../../modules/sandbox_asg"
  name             = "${local.name}-sandbox"
  region           = var.region
  vpc_id           = module.network.vpc_id
  vpc_cidr         = module.network.vpc_cidr
  subnet_ids       = module.network.isolated_subnet_ids
  client_cidrs     = module.network.private_subnet_cidrs
  runner_image     = local.image["sandbox-runner"]
  sandbox_image    = local.image["sandbox-python"]
  token_secret_arn = aws_secretsmanager_secret.app.arn
  ami_id           = var.sandbox_ami_id
  min_size         = var.sandbox_min
  max_size         = var.sandbox_max
}

module "observability" {
  source                          = "../../modules/observability"
  name                            = local.name
  alert_emails                    = var.alert_emails
  alb_arn_suffix                  = aws_lb.public.arn_suffix
  web_target_group_arn_suffix     = aws_lb_target_group.web.arn_suffix
  cluster_name                    = aws_ecs_cluster.this.name
  api_service_name                = module.api.service_name
  db_identifier                   = module.rds.identifier
  redis_replication_group_id      = module.redis.replication_group_id
  sandbox_nlb_arn_suffix          = module.sandbox.nlb_arn_suffix
  sandbox_target_group_arn_suffix = module.sandbox.target_group_arn_suffix
}
