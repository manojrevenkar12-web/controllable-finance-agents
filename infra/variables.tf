variable "project" {
  type        = string
  description = "GCP project id"
}

variable "region" {
  type    = string
  default = "europe-west3" # Frankfurt
}

variable "env" {
  type    = string
  default = "dev"
  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "env is dev or prod"
  }
}

variable "image" {
  type        = string
  description = "Container image with the cfa CLI, the ledger API and the built console"
}
