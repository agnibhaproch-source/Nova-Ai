# PostgreSQL 16 (pgvector is created by the app's migrations), Multi-AZ, encrypted, TLS-only,
# PITR backups (docs/48 §5, docs/50). The password is generated here and stored by the caller.
resource "random_password" "master" {
  length  = 40
  special = false
}

resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "this" {
  name_prefix = "${var.name}-rds-"
  description = "PostgreSQL from the app tasks only"
  vpc_id      = var.vpc_id
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "from_app" {
  for_each                     = toset(var.client_security_group_ids)
  security_group_id            = aws_security_group.this.id
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "PostgreSQL from app tasks"
}

resource "aws_db_parameter_group" "this" {
  name_prefix = "${var.name}-pg16-"
  family      = "postgres16"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "500"
  }
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "this" {
  identifier                   = var.name
  engine                       = "postgres"
  engine_version               = var.engine_version
  instance_class               = var.instance_class
  allocated_storage            = var.allocated_storage_gb
  max_allocated_storage        = var.max_allocated_storage_gb
  storage_type                 = "gp3"
  storage_encrypted            = true
  db_name                      = "nova"
  username                     = "nova"
  password                     = random_password.master.result
  multi_az                     = var.multi_az
  db_subnet_group_name         = aws_db_subnet_group.this.name
  vpc_security_group_ids       = [aws_security_group.this.id]
  parameter_group_name         = aws_db_parameter_group.this.name
  backup_retention_period      = var.backup_retention_days
  backup_window                = "02:00-03:00"
  maintenance_window           = "sun:03:30-sun:04:30"
  auto_minor_version_upgrade   = true
  copy_tags_to_snapshot        = true
  deletion_protection          = var.deletion_protection
  skip_final_snapshot          = false
  final_snapshot_identifier    = "${var.name}-final"
  performance_insights_enabled = true
  publicly_accessible          = false
}
