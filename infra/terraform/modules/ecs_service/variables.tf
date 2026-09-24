variable "name" {
  type = string
}

variable "image" {
  type = string
}

variable "cluster_arn" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "cpu" {
  type = number
}

variable "memory" {
  type = number
}

variable "cpu_architecture" {
  description = "X86_64 or ARM64 (must match the pushed image)."
  type        = string
  default     = "X86_64"
}

variable "port" {
  description = "Container port (null for workers without one)."
  type        = number
  default     = null
}

variable "command" {
  type    = list(string)
  default = null
}

variable "environment" {
  description = "Plain environment variables."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Env var name → Secrets Manager valueFrom (\"<arn>:<json-key>::\")."
  type        = map(string)
  default     = {}
}

variable "secret_arns" {
  description = "Secret ARNs the execution role may read."
  type        = list(string)
  default     = []
}

variable "task_policy_json" {
  description = "IAM policy for the app itself (null = no permissions)."
  type        = string
  default     = null
}

variable "ingress_security_group_ids" {
  description = "Security groups allowed to reach the container port."
  type        = list(string)
  default     = []
}

variable "health_check_command" {
  type    = list(string)
  default = null
}

variable "service" {
  description = "Run as a long-lived service (false = task definition only)."
  type        = bool
  default     = true
}

variable "min_count" {
  type    = number
  default = 2
}

variable "max_count" {
  type    = number
  default = 2
}

variable "cpu_target_percent" {
  type    = number
  default = 60
}

variable "target_group_arn" {
  type    = string
  default = null
}

variable "service_connect_namespace" {
  description = "Cloud Map HTTP namespace ARN; the service is reachable as http://<name>:<port>."
  type        = string
  default     = null
}

variable "stop_timeout_seconds" {
  description = "Grace period on shutdown (SSE streams drain; docs/48 §3)."
  type        = number
  default     = 60
}

variable "log_retention_days" {
  type    = number
  default = 30
}
