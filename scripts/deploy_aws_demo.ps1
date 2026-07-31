[CmdletBinding()]
param(
    [string]$Region = "ap-south-1",
    [string]$ProjectName = "permission-enforcer",
    [string]$AllowedIngressCidr = "0.0.0.0/0",
    [string]$CertificateArn = "",
    [string]$DomainName = "",
    [switch]$SkipDemo
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$terraformDirectory = Join-Path $projectRoot "infra\terraform"
$imageTag = (Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmss")

foreach ($commandName in @("aws", "docker", "terraform")) {
    if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
        throw "Required command '$commandName' is not installed or is not on PATH."
    }
}
if (-not $SkipDemo -and -not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    throw "Required command 'uv' is not installed or is not on PATH."
}

$identityJson = aws sts get-caller-identity --output json
if ($LASTEXITCODE -ne 0) {
    throw "AWS authentication failed. Run 'aws configure' and retry."
}
$identity = $identityJson | ConvertFrom-Json
Write-Host "Deploying with AWS account $($identity.Account) as $($identity.Arn)"

$randomBytes = New-Object byte[] 48
[Security.Cryptography.RandomNumberGenerator]::Fill($randomBytes)
$demoJwtSecret = [Convert]::ToBase64String($randomBytes)

$env:TF_VAR_aws_region = $Region
$env:TF_VAR_project_name = $ProjectName
$env:TF_VAR_image_tag = $imageTag
$env:TF_VAR_demo_jwt_secret = $demoJwtSecret
$env:TF_VAR_allowed_ingress_cidr = $AllowedIngressCidr
$env:TF_VAR_certificate_arn = $CertificateArn
$env:TF_VAR_domain_name = $DomainName

Push-Location $terraformDirectory
try {
    terraform init
    terraform apply -auto-approve -var="create_service=false"

    $repositoryUrl = terraform output -raw ecr_repository_url
    $registryHost = $repositoryUrl.Split("/")[0]
    aws ecr get-login-password --region $Region |
        docker login --username AWS --password-stdin $registryHost

    docker build --file (Join-Path $projectRoot "docker\Dockerfile.production") `
        --tag "${repositoryUrl}:${imageTag}" $projectRoot
    docker push "${repositoryUrl}:${imageTag}"

    terraform apply -auto-approve -var="create_service=true"

    $applicationUrl = terraform output -raw application_url
    $clusterName = terraform output -raw ecs_cluster_name
    $serviceName = terraform output -raw ecs_service_name
    Write-Host "Waiting for ECS service '$serviceName' to become stable..."
    aws ecs wait services-stable `
        --region $Region `
        --cluster $clusterName `
        --services $serviceName

    Write-Host "Application URL: $applicationUrl"
    Write-Host "API docs: $applicationUrl/docs"

    if (-not $SkipDemo) {
        $env:PROXY_DEMO_BASE_URL = $applicationUrl
        $env:PROXY_APP_ENV = "staging"
        $env:PROXY_OIDC_ISSUER = terraform output -raw demo_oidc_issuer
        $env:PROXY_OIDC_AUDIENCE = terraform output -raw demo_oidc_audience
        $env:PROXY_DEV_AUTH_ENABLED = "true"
        $env:PROXY_DEV_JWT_SECRET = $demoJwtSecret
        Push-Location $projectRoot
        try {
            uv run python -m scripts.run_local_demo
        }
        finally {
            Pop-Location
        }
    }
}
finally {
    Pop-Location
    Remove-Item Env:\TF_VAR_demo_jwt_secret -ErrorAction SilentlyContinue
    Remove-Item Env:\PROXY_DEV_JWT_SECRET -ErrorAction SilentlyContinue
}
