variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "client_security_group_ids" {
  type = list(string)
}

variable "engine_version" {
  type    = string
  default = "7.1"
}

variable "node_type" {
  type    = string
  default = "cache.r7g.large"
}

variable "replicas" {
  description = "Read replicas (1+ enables automatic failover across AZs)."
  type        = number
  default     = 1
}
