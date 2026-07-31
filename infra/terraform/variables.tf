variable "aws_region" {
  description = "AWS region used for every resource."
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Short lowercase name used to prefix AWS resources."
  type        = string
  default     = "permission-enforcer"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.project_name))
    error_message = "project_name must be 3-31 lowercase letters, numbers, or hyphens."
  }
}

variable "image_tag" {
  description = "Immutable image tag pushed to the ECR repository."
  type        = string
  default     = "bootstrap"
}

variable "create_service" {
  description = "Create the ECS task definition and service after the image has been pushed."
  type        = bool
  default     = false
}

variable "demo_jwt_secret" {
  description = "Temporary HS256 key for the interview demo. Replace this mode with OIDC for real production."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.demo_jwt_secret) >= 32
    error_message = "demo_jwt_secret must contain at least 32 characters."
  }
}

variable "certificate_arn" {
  description = "Optional ACM certificate ARN. When set, HTTP redirects to an HTTPS listener."
  type        = string
  default     = ""

  validation {
    condition = (
      (var.certificate_arn == "" && var.domain_name == "") ||
      (var.certificate_arn != "" && var.domain_name != "")
    )
    error_message = "certificate_arn and domain_name must either both be set or both be empty."
  }
}

variable "domain_name" {
  description = "Optional DNS name covered by certificate_arn and pointed at the ALB."
  type        = string
  default     = ""
}

variable "allowed_ingress_cidr" {
  description = "CIDR allowed to reach the public load balancer. Use your public IP/32 when possible."
  type        = string
  default     = "0.0.0.0/0"
}
