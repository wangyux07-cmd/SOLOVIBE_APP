param([switch]$SkipFrontend)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskUv = Join-Path $taskRoot '.tools\bin\uv.exe'
if (-not (Test-Path -LiteralPath $taskUv)) {
    & python -m pip install --target .tools uv==0.12.13
    if ($LASTEXITCODE -ne 0) { throw 'uv installation failed.' }
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $taskRoot '.tools\python'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $taskUv venv --python (Get-Content -LiteralPath '.python-version' -Raw).Trim() .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
}
& $taskUv pip sync backend/requirements-dev.txt --python .venv/Scripts/python.exe
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
if (-not $SkipFrontend) {
    & npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
}
foreach ($taskFolder in @('backend', 'frontend')) {
    $taskEnv = Join-Path $taskFolder '.env'
    if (-not (Test-Path -LiteralPath $taskEnv)) {
        Copy-Item -LiteralPath (Join-Path $taskFolder '.env.example') -Destination $taskEnv
    }
}
Write-Output 'Setup complete. Use scripts/dev.ps1 -Service backend or frontend.'
