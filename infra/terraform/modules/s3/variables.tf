variable "bucket_name" {
  type = string
}

variable "allowed_origins" {
  description = "Browser origins allowed to use presigned URLs (the app's https origin)."
  type        = list(string)
}

variable "noncurrent_version_days" {
  description = "Keep overwritten/deleted object versions this long (restore window)."
  type        = number
  default     = 30
}
