output "address" {
  value = aws_db_instance.this.address
}

output "port" {
  value = aws_db_instance.this.port
}

output "identifier" {
  value = aws_db_instance.this.identifier
}

output "database_url" {
  description = "asyncpg URL with TLS required (stored in Secrets Manager by the caller)."
  value       = "postgresql+asyncpg://nova:${random_password.master.result}@${aws_db_instance.this.address}:${aws_db_instance.this.port}/nova?ssl=require"
  sensitive   = true
}
