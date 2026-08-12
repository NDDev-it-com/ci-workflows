# Smallest configuration that `terraform fmt -check` and
# `terraform init -backend=false` both accept. It declares no provider on
# purpose: a provider would make the fixture download a plugin on every run
# and turn a contract proof into a network test.

terraform {
  required_version = ">= 1.5.0"
}

variable "environment" {
  description = "Name of the environment this fixture pretends to describe."
  type        = string
  default     = "fixture"
}

output "environment" {
  description = "Echoes the environment name back, so the config is not empty."
  value       = var.environment
}
