$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
& .\.venv\Scripts\python.exe -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& npm.cmd run lint
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& npm.cmd run build
exit $LASTEXITCODE
