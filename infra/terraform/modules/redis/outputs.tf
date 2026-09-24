output "redis_url" {
  description = "TLS URL with the AUTH token (stored in Secrets Manager by the caller)."
  value       = "rediss://:${random_password.auth.result}@${aws_elasticache_replication_group.this.primary_endpoint_address}:6379/0"
  sensitive   = true
}

output "replication_group_id" {
  value = aws_elasticache_replication_group.this.id
}
