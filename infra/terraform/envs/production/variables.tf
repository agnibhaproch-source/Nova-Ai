variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "environment" {
  type    = string
  default = "production"
}

variable "domain" {
  description = "Public hostname, e.g. nova.example.com (DNS → the ALB)."
  type        = string
}

variable "acm_certificate_arn" {
  description = "ACM certificate for var.domain in var.region."
  type        = string
}

variable "ecr_registry" {
  description = "<account>.dkr.ecr.<region>.amazonaws.com (images nova-web, nova-api, nova-sandbox-runner, nova-sandbox-python)."
  type        = string
}

variable "image_tag" {
  description = "Image tag to deploy (the git SHA from the deploy workflow)."
  type        = string
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "single_nat_gateway" {
  type    = bool
  default = false
}

variable "files_bucket_name" {
  type = string
}

variable "db_instance_class" {
  type    = string
  default = "db.r6g.large"
}

variable "db_multi_az" {
  type    = bool
  default = true
}

variable "redis_node_type" {
  type    = string
  default = "cache.r7g.large"
}

variable "web_min" {
  type    = number
  default = 2
}

variable "web_max" {
  type    = number
  default = 6
}

variable "api_min" {
  type    = number
  default = 2
}

variable "api_max" {
  type    = number
  default = 10
}

variable "worker_min" {
  type    = number
  default = 1
}

variable "worker_max" {
  type    = number
  default = 6
}

variable "sandbox_min" {
  type    = number
  default = 2
}

variable "sandbox_max" {
  type    = number
  default = 4
}

variable "sandbox_ami_id" {
  description = "Custom AMI with gVisor installed (null = Amazon Linux 2023; runner then won't start)."
  type        = string
  default     = null
}

variable "waf_requests_per_5min_per_ip" {
  type    = number
  default = 2000
}

variable "alert_emails" {
  type    = list(string)
  default = []
}

variable "groq_key_mode" {
  description = "\"user\" = each chat brings its own Groq key (ADR 0001); \"server\" = var.groq_api_key."
  type        = string
  default     = "user"
  validation {
    condition     = contains(["user", "server"], var.groq_key_mode)
    error_message = "groq_key_mode must be \"user\" or \"server\"."
  }
}

variable "groq_api_key" {
  description = "Server Groq key (only used with groq_key_mode = \"server\")."
  type        = string
  default     = ""
  sensitive   = true
}

variable "smtp_host" {
  type    = string
  default = "email-smtp.ap-south-1.amazonaws.com"
}

variable "smtp_port" {
  type    = number
  default = 587
}

variable "smtp_username" {
  type    = string
  default = ""
}

variable "smtp_password" {
  type      = string
  default   = ""
  sensitive = true
}

variable "smtp_from" {
  type    = string
  default = "NOVA AI <no-reply@example.com>"
}

variable "sentry_dsn" {
  type      = string
  default   = ""
  sensitive = true
}
