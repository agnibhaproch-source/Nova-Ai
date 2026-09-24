output "security_group_id" {
  value = aws_security_group.this.id
}

output "task_definition_arn" {
  value = aws_ecs_task_definition.this.arn
}

output "service_name" {
  value = var.service ? aws_ecs_service.this[0].name : null
}

output "log_group" {
  value = aws_cloudwatch_log_group.this.name
}
