# Production readiness checklist

This separates the implemented interview deployment from a real production launch.

## Implemented for the AWS demo

- [x] Dependencies are locked with `uv.lock`.
- [x] A repeatable image runs migration, proxy, and sample CRM containers.
- [x] Runtime containers use an unprivileged UID/GID.
- [x] Build context excludes secrets, databases, tests, caches, and Terraform state.
- [x] ECR scanning and unique immutable image tags are enabled.
- [x] RDS PostgreSQL is encrypted, private, and restricted to ECS.
- [x] The CRM is reachable only inside its ECS task.
- [x] Runtime connection strings and keys come from Secrets Manager.
- [x] Public ingress can be restricted to one interview IP.
- [x] Container and load-balancer health checks use readiness endpoints.
- [x] Migrations and deterministic seed data run before application startup.
- [x] CloudWatch keeps application logs for 14 days.
- [x] ECS Container Insights is enabled.
- [x] The deployment runs an end-to-end remote acceptance demo.
- [x] Terraform can reproduce and destroy the environment.
- [x] A strict production environment template and deployment runbook exist.

## Accepted shortcuts for the interview demo

- [ ] Replace development JWT signing with an external OIDC provider.
- [ ] Set `PROXY_APP_ENV=production` and `PROXY_DEV_AUTH_ENABLED=false`.
- [ ] Use a custom domain and ACM certificate for HTTPS.
- [ ] Put Terraform state in encrypted remote storage with locking.
- [ ] Replace broad temporary deployer access with least privilege.
- [ ] Add WAF and rate limiting before unrestricted internet exposure.
- [ ] Move ECS to private subnets with endpoints or a NAT design.
- [ ] Enable longer RDS backups, deletion protection, and restore testing.
- [ ] Use Multi-AZ RDS and at least two ECS tasks.
- [ ] Add autoscaling, latency/error alarms, and alert routing.
- [ ] Export audits to append-only/object-locked storage or a SIEM.
- [ ] Add SBOM/signature policy, load tests, penetration tests, and recovery tests.
- [ ] Add CI/CD only if submission requirements change.

## Release decision

The current design is suitable for a time-boxed, IP-restricted interview demonstration
with synthetic data. It is not suitable for real customer data or unrestricted production
traffic until the unchecked identity, TLS, availability, audit, and operational controls
are complete.

