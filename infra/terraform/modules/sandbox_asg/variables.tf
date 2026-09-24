variable "name" {
  type = string
}

variable "region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "subnet_ids" {
  description = "Isolated subnets (no internet route)."
  type        = list(string)
}

variable "client_cidrs" {
  description = "CIDRs of the app subnets allowed to call the runner."
  type        = list(string)
}

variable "runner_image" {
  description = "ECR image of apps/sandbox-runner."
  type        = string
}

variable "sandbox_image" {
  description = "ECR image the runner starts for each execution."
  type        = string
}

variable "token_secret_arn" {
  description = "Secrets Manager secret holding SANDBOX_RUNNER_TOKEN (JSON key)."
  type        = string
}

variable "ami_id" {
  description = "Custom AMI with gVisor baked in (recommended); null = latest Amazon Linux 2023."
  type        = string
  default     = null
}

variable "architecture" {
  type    = string
  default = "x86_64"
}

variable "instance_type" {
  type    = string
  default = "c7i.large"
}

variable "min_size" {
  type    = number
  default = 2
}

variable "max_size" {
  type    = number
  default = 4
}
