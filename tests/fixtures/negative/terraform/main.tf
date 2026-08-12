terraform {
  required_version = ">= 1.5.0"
}

variable "environment" {
  description="Misaligned on purpose so terraform fmt -check fails."
      type = string
  default   =    "fixture"
}
