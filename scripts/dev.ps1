$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$rustTarget = "x86_64-pc-windows-msvc"

function Test-Cargo {
    param([string]$Toolchain)

    $ErrorActionPreference = "Continue"
    if ($Toolchain) {
        & rustup.exe run $Toolchain cargo --version *> $null
        return $LASTEXITCODE -eq 0
    }

    if (!(Get-Command cargo.exe -CommandType Application -ErrorAction SilentlyContinue)) { return $false }
    & cargo.exe --version *> $null
    return $LASTEXITCODE -eq 0
}

$rustToolchain = $null
if (!(Test-Cargo)) {
    if (!(Get-Command rustup.exe -CommandType Application -ErrorAction SilentlyContinue)) {
        throw "Cargo e Rustup indisponiveis. Execute scripts/setup-windows.ps1 -Launch."
    }
    $rustToolchain = "stable-$rustTarget"
    if (!(Test-Cargo -Toolchain $rustToolchain)) {
        Write-Host "Preparando Rust stable/MSVC para o Clip Factory..."
        & rustup.exe toolchain install $rustToolchain --profile minimal
        if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar Rust stable/MSVC. Confira a mensagem do Rustup acima." }
    }
}

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
    $previousToolchain = $env:RUSTUP_TOOLCHAIN
    try {
        if ($rustToolchain) { $env:RUSTUP_TOOLCHAIN = $rustToolchain }
        npm.cmd run tauri -- dev --target $rustTarget
        if ($LASTEXITCODE -ne 0) { throw "Falha ao iniciar Tauri. Execute scripts/doctor.ps1." }
    } finally {
        $env:RUSTUP_TOOLCHAIN = $previousToolchain
    }
} finally {
    Pop-Location
}
