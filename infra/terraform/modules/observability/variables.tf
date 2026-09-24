variable "name" {
  type = string
}

variable "alert_emails" {
  description = "Addresses subscribed to alerts (each must confirm the SNS email)."
  type        = list(string)
  default     = []
}

variable "alb_arn_suffix" {
  type = string
}

variable "web_target_group_arn_suffix" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "api_service_name" {
  type = string
}

variable "db_identifier" {
  type = string
}

variable "redis_replication_group_id" {
  type = string
}

variable "sandbox_nlb_arn_suffix" {
  type = string
}

variable "sandbox_target_group_arn_suffix" {
  type = string
}
