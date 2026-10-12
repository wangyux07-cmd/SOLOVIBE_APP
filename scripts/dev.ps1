param(
    [ValidateSet('backend', 'frontend')]
    [string]$Service = 'backend'
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
if ($Service -eq 'backend') {
    $taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $taskPython)) {
        throw 'Missing .venv. Run scripts/setup.ps1 first.'
    }
    & $taskPython backend/run_server.py
} else {
    if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'node_modules\.bin\vite.cmd'))) {
        throw 'Missing frontend dependencies. Run npm ci first.'
    }
    & npm.cmd run dev
}
exit $LASTEXITCODE
