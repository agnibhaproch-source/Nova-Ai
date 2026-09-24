variable "name" {
  description = "Name prefix for every resource."
  type        = string
}

variable "region" {
  description = "AWS region (for VPC endpoint service names)."
  type        = string
}

variable "cidr" {
  description = "VPC CIDR; must be a /16 (split into /20 subnets)."
  type        = string
  default     = "10.40.0.0/16"
}

variable "az_count" {
  description = "Availability zones to span (docs/48: 3)."
  type        = number
  default     = 3
}

variable "single_nat_gateway" {
  description = "One shared NAT gateway (cheaper, not AZ-resilient) instead of one per AZ."
  type        = bool
  default     = false
}
