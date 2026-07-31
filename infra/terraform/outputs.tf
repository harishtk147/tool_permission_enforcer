output "ecr_repository_url" {
  description = "Repository to which the production image is pushed."
  value       = aws_ecr_repository.app.repository_url
}

output "application_url" {
  description = "Public URL for the permission proxy."
  value       = var.certificate_arn != "" ? "https://${var.domain_name}" : "http://${aws_lb.main.dns_name}"
}

output "load_balancer_dns_name" {
  description = "DNS target to use when configuring a custom domain."
  value       = aws_lb.main.dns_name
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  value = var.create_service ? aws_ecs_service.app[0].name : ""
}

output "runtime_secret_arn" {
  description = "ARN used to retrieve the demo JWT key for remote acceptance testing."
  value       = aws_secretsmanager_secret.runtime.arn
}

output "demo_oidc_issuer" {
  value = local.oidc_issuer
}

output "demo_oidc_audience" {
  value = local.oidc_audience
}
