$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

Write-Host "Running the complete Phase 1 gate first."
& "$PSScriptRoot\verify_phase_1.ps1"

Write-Host "Phase 2 verification: identity and trusted session flow"
uv run python -m scripts.verify_phase_2
if ($LASTEXITCODE -ne 0) {
    throw "Phase 2 security verification failed with exit code $LASTEXITCODE."
}

Write-Host "Phase 2 verification passed." -ForegroundColor Green

