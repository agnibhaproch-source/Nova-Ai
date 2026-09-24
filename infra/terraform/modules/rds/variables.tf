variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  description = "Private subnets for the DB subnet group."
  type        = list(string)
}

variable "client_security_group_ids" {
  description = "Security groups allowed to connect (api, worker, migrate)."
  type        = list(string)
}

variable "engine_version" {
  type    = string
  default = "16"
}

variable "instance_class" {
  type    = string
  default = "db.r6g.large"
}

variable "allocated_storage_gb" {
  type    = number
  default = 100
}

variable "max_allocated_storage_gb" {
  type    = number
  default = 500
}

variable "multi_az" {
  type    = bool
  default = true
}

variable "backup_retention_days" {
  type    = number
  default = 14
}

variable "deletion_protection" {
  type    = bool
  default = true
}
