$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

function Invoke-VerificationStep {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host "Phase 0 verification: $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Phase 0 verification failed during '$Name' with exit code $LASTEXITCODE."
    }
}

Invoke-VerificationStep "dependency sync" { uv sync --frozen --python 3.12 }
Invoke-VerificationStep "formatting" { uv run ruff format --check . }
Invoke-VerificationStep "lint" { uv run ruff check . }
Invoke-VerificationStep "static types" { uv run mypy services tests scripts }
Invoke-VerificationStep "tests and coverage" { uv run python -m pytest }

Write-Host "Phase 0 Python verification passed." -ForegroundColor Green

if (Get-Command docker -ErrorAction SilentlyContinue) {
    Invoke-VerificationStep "Docker Compose configuration" { docker compose config --quiet }
    Write-Host "Docker Compose configuration passed." -ForegroundColor Green
}
else {
    Write-Warning "Docker is not installed; Docker Compose runtime verification was skipped."
}
