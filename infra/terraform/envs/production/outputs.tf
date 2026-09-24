output "alb_dns_name" {
  description = "Point the domain's DNS (CNAME/alias) here."
  value       = aws_lb.public.dns_name
}

output "ecs_cluster" {
  value = aws_ecs_cluster.this.name
}

output "migrate_task_definition" {
  value = module.migrate.task_definition_arn
}

output "private_subnet_ids" {
  description = "For `aws ecs run-task` (migrations)."
  value       = module.network.private_subnet_ids
}

output "migrate_security_group_id" {
  value = module.migrate.security_group_id
}

output "files_bucket" {
  value = module.s3.bucket
}

output "alerts_topic_arn" {
  value = module.observability.alerts_topic_arn
}
