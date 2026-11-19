$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (!(Test-Path .venv/Scripts/python.exe)) {
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Instale Python 3.11 x64." }
}
$env:CLIP_FACTORY_PYTHON = Join-Path $Root ".venv/Scripts/python.exe"
& $env:CLIP_FACTORY_PYTHON -m pip install "uv>=0.8,<1"
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar uv." }
$env:UV_PROJECT_ENVIRONMENT = Join-Path $Root ".venv"
& $env:CLIP_FACTORY_PYTHON -m uv sync --project services/engine --locked --inexact --extra test
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependências do motor." }

Push-Location apps/desktop
try {
    if (Test-Path package-lock.json) { npm.cmd ci } else { npm.cmd install }
    if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependências da interface." }
    npm.cmd run tauri -- dev
    if ($LASTEXITCODE -ne 0) { throw "Falha ao iniciar Tauri. Execute scripts/doctor.ps1." }
} finally {
    Pop-Location
}
