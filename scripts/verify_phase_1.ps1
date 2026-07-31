$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

Write-Host "Running the complete Phase 0 gate first."
& "$PSScriptRoot\verify_phase_0.ps1"

Write-Host "Phase 1 verification: migration, idempotent seed, and restart persistence"
uv run python -m scripts.verify_phase_1
if ($LASTEXITCODE -ne 0) {
    throw "Phase 1 persistence verification failed with exit code $LASTEXITCODE."
}

Write-Host "Phase 1 verification passed." -ForegroundColor Green
