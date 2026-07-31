$ErrorActionPreference = "Stop"

Write-Host "Running the complete Phase 2 gate first."
& "$PSScriptRoot\verify_phase_2.ps1"

Write-Host "Phase 3-5 verification: policy, CRM proxy, audit, and tamper detection"
uv run python -m pytest --no-cov `
    tests/integration/test_local_prototype.py `
    tests/unit/test_policy_manifest.py
if ($LASTEXITCODE -ne 0) {
    throw "Phase 3-5 prototype verification failed."
}

Write-Host "Phase 5 local prototype verification passed."
