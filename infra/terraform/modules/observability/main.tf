# Alarms → SNS (email/on-call) for the signals in docs/39: ALB 5xx and latency, unhealthy web
# tasks, API CPU, database CPU/storage/connections, Redis memory, sandbox runner health.
resource "aws_sns_topic" "alerts" {
  name = "${var.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  for_each  = toset(var.alert_emails)
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = each.value
}

locals {
  alarms = {
    alb-5xx = {
      namespace = "AWS/ApplicationELB", metric = "HTTPCode_Target_5XX_Count", stat = "Sum", threshold = 25, comparison = "GreaterThanThreshold"
      dims      = { LoadBalancer = var.alb_arn_suffix }, desc = "More than 25 5xx responses in 5 minutes"
    }
    alb-latency = {
      namespace = "AWS/ApplicationELB", metric = "TargetResponseTime", stat = "p95", threshold = 3, comparison = "GreaterThanThreshold"
      dims      = { LoadBalancer = var.alb_arn_suffix }, desc = "p95 time to first byte above 3 s (streams excluded by nature of TTFB)"
    }
    web-unhealthy = {
      namespace = "AWS/ApplicationELB", metric = "UnHealthyHostCount", stat = "Maximum", threshold = 0, comparison = "GreaterThanThreshold"
      dims      = { LoadBalancer = var.alb_arn_suffix, TargetGroup = var.web_target_group_arn_suffix }, desc = "A web task is failing health checks"
    }
    api-cpu = {
      namespace = "AWS/ECS", metric = "CPUUtilization", stat = "Average", threshold = 85, comparison = "GreaterThanThreshold"
      dims      = { ClusterName = var.cluster_name, ServiceName = var.api_service_name }, desc = "API CPU above 85% (autoscaling at its max?)"
    }
    rds-cpu = {
      namespace = "AWS/RDS", metric = "CPUUtilization", stat = "Average", threshold = 80, comparison = "GreaterThanThreshold"
      dims      = { DBInstanceIdentifier = var.db_identifier }, desc = "Database CPU above 80%"
    }
    rds-storage = {
      namespace = "AWS/RDS", metric = "FreeStorageSpace", stat = "Minimum", threshold = 10737418240, comparison = "LessThanThreshold"
      dims      = { DBInstanceIdentifier = var.db_identifier }, desc = "Less than 10 GB database storage left"
    }
    redis-memory = {
      namespace = "AWS/ElastiCache", metric = "DatabaseMemoryUsagePercentage", stat = "Maximum", threshold = 80, comparison = "GreaterThanThreshold"
      dims      = { ReplicationGroupId = var.redis_replication_group_id }, desc = "Redis memory above 80%"
    }
    sandbox-unhealthy = {
      namespace = "AWS/NetworkELB", metric = "UnHealthyHostCount", stat = "Maximum", threshold = 0, comparison = "GreaterThanThreshold"
      dims      = { LoadBalancer = var.sandbox_nlb_arn_suffix, TargetGroup = var.sandbox_target_group_arn_suffix }, desc = "A sandbox runner is unhealthy (code tool degraded)"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "this" {
  for_each            = local.alarms
  alarm_name          = "${var.name}-${each.key}"
  alarm_description   = each.value.desc
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  dimensions          = each.value.dims
  statistic           = contains(["Sum", "Average", "Minimum", "Maximum", "SampleCount"], each.value.stat) ? each.value.stat : null
  extended_statistic  = contains(["Sum", "Average", "Minimum", "Maximum", "SampleCount"], each.value.stat) ? null : each.value.stat
  period              = 300
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = each.value.threshold
  comparison_operator = each.value.comparison
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
