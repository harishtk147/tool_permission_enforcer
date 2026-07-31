# Personal AWS deployment runbook

This runbook deploys the working Phase 5 prototype to a personal AWS account. It is
optimized for an interview demonstration: one ECS Fargate task, one small private RDS
PostgreSQL instance, one public Application Load Balancer, one ECR repository, CloudWatch
logs, and Secrets Manager. It does not use Cisco credentials or infrastructure.

## Important scope

This is a production-shaped demo, not an internet-scale production service. It keeps the
application's short-lived development JWT mode so `scripts/run_local_demo.py` can exercise
the entire remote flow. A real production launch must replace it with external OIDC and
enable HTTPS. No Redis service is deployed because the current request path does not use it.

```text
Internet
   |
Application Load Balancer :80 or :443
   |
ECS Fargate task (one replica)
   +-- migration/seed init container
   +-- permission-proxy :8000  <-- only exposed container
   +-- sample-crm :8001        <-- localhost/private only
   |
Private encrypted RDS PostgreSQL
```

The task receives a public IP so Fargate can pull its image and secrets without a paid NAT
Gateway. Its security group accepts port 8000 only from the load balancer. RDS has no public
endpoint and accepts PostgreSQL only from ECS.

## Cost warning

This is not a free deployment. The load balancer, RDS instance, and running Fargate task
incur charges. Create an AWS Budget first and destroy the stack immediately after the demo.

## 1. Prepare the personal AWS account

1. Enable MFA on the AWS root user.
2. Create an IAM identity for CLI use. For the shortest temporary demo, attach
   `AdministratorAccess`, then delete its access key after destroying the deployment.
3. Create an access key. Never paste it into this repository or chat.
4. Create a monthly AWS Budget with email alerts.

## 2. Install prerequisites on Windows

```powershell
winget install --id Amazon.AWSCLI
winget install --id Docker.DockerDesktop
winget install --id Hashicorp.Terraform
```

Restart PowerShell, start Docker Desktop, and verify:

```powershell
aws --version
docker version
terraform version
uv --version
```

## 3. Configure the AWS CLI

```powershell
aws configure --profile personal
```

Enter the access key values only at the CLI prompts. Use `ap-south-1` for Mumbai (or
another supported region) and `json` output. Then:

```powershell
$env:AWS_PROFILE = "personal"
aws sts get-caller-identity
```

The account number returned must be the personal account.

## 4. Deploy

```powershell
Set-Location "C:\Users\arua\OneDrive - Cisco\Documents\Harish\tool-permission-enforcer"
$publicIp = (Invoke-RestMethod "https://checkip.amazonaws.com").Trim()
.\scripts\deploy_aws_demo.ps1 -Region "ap-south-1" -AllowedIngressCidr "$publicIp/32"
```

The script verifies the AWS identity, generates a temporary JWT key in memory, provisions
the base infrastructure, builds and pushes an immutable ECR image, creates ECS, waits for
service stability, and runs the full end-to-end demo against AWS.

The first deployment commonly takes 15-25 minutes because RDS and the load balancer must
be provisioned. Do not close the terminal. To omit automatic acceptance testing, add
`-SkipDemo`.

## 5. Verify manually

```powershell
Set-Location .\infra\terraform
$applicationUrl = terraform output -raw application_url
Invoke-RestMethod "$applicationUrl/health/live"
Invoke-RestMethod "$applicationUrl/health/ready"
Start-Process "$applicationUrl/docs"
```

Readiness must report `status: ready`, `configuration: ok`, and `database: ok`.

Inspect service state and logs:

```powershell
$cluster = terraform output -raw ecs_cluster_name
$service = terraform output -raw ecs_service_name
aws ecs describe-services --region "ap-south-1" --cluster $cluster --services $service
aws logs tail "/ecs/permission-enforcer" --region "ap-south-1" --since 10m
```

The automatic demo must prove:

- trusted session creation returns HTTP 201;
- same-customer read returns HTTP 200 and `ALLOWED`;
- write and delete return HTTP 403 and `OPERATION_NOT_ALLOWED`;
- cross-customer read returns HTTP 403 and `DATA_SCOPE_VIOLATION`;
- duplicate idempotency key returns HTTP 409;
- audit-chain integrity returns `valid: true`.

## 6. Optional HTTPS

If a domain and ACM certificate already exist in the same region:

```powershell
.\scripts\deploy_aws_demo.ps1 `
    -Region "ap-south-1" `
    -AllowedIngressCidr "$publicIp/32" `
    -CertificateArn "arn:aws:acm:REGION:ACCOUNT:certificate/CERTIFICATE_ID" `
    -DomainName "permissions.example.com"
```

Terraform then redirects HTTP to HTTPS. Point the domain DNS record at the load balancer.

## 7. Troubleshooting

If ECS does not stabilize:

```powershell
Set-Location .\infra\terraform
$cluster = terraform output -raw ecs_cluster_name
$service = terraform output -raw ecs_service_name
aws ecs describe-services --region "ap-south-1" --cluster $cluster --services $service `
    --query "services[0].events[0:10]"
aws logs tail "/ecs/permission-enforcer" --region "ap-south-1" --since 30m
```

Typical causes are Docker not running, the wrong AWS account/profile, missing permissions,
a service quota, or a changed public IP.

## 8. Destroy everything after the demo

```powershell
Set-Location "C:\Users\arua\OneDrive - Cisco\Documents\Harish\tool-permission-enforcer\infra\terraform"
$env:AWS_PROFILE = "personal"
$env:TF_VAR_demo_jwt_secret = "destroy-only-placeholder-secret-32chars"
terraform destroy
Remove-Item Env:\TF_VAR_demo_jwt_secret
terraform state list
```

Review the plan and type `yes`. The final state command should print no resources. Delete
the temporary IAM access key afterward and check the Billing console.
