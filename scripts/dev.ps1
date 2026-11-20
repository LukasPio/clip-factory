param([switch]$PrepareOnly)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "windows-common.ps1")
$Root = Split-Path -Parent $PSScriptRoot
$rustToolchain = Get-WindowsRustToolchain
$python = Initialize-EngineEnvironment -Root $Root -Extra test

Push-Location (Join-Path $Root "apps/desktop")
try {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependencias da interface." }
    if ($PrepareOnly) { return }

    $previousPython = $env:CLIP_FACTORY_PYTHON
    $previousToolchain = $env:RUSTUP_TOOLCHAIN
    try {
        $env:CLIP_FACTORY_PYTHON = $python
        if ($rustToolchain) { $env:RUSTUP_TOOLCHAIN = $rustToolchain }
        npm.cmd run tauri -- dev --target $WindowsRustTarget
        if ($LASTEXITCODE -ne 0) { throw "Falha ao iniciar Tauri. Execute scripts/doctor.ps1." }
    } finally {
        $env:CLIP_FACTORY_PYTHON = $previousPython
        $env:RUSTUP_TOOLCHAIN = $previousToolchain
    }
} finally {
    Pop-Location
}
