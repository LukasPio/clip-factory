param([switch]$PrepareOnly, [switch]$PrepareModels)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "windows-common.ps1")
$Root = Split-Path -Parent $PSScriptRoot
$rustToolchain = Get-WindowsRustToolchain
$python = Initialize-EngineEnvironment -Root $Root -Extra test

Push-Location (Join-Path $Root "apps/desktop")
try {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependencias da interface." }
    if ($PrepareModels) {
        $tauriConfig = Get-Content -LiteralPath "src-tauri/tauri.conf.json" -Raw | ConvertFrom-Json
        $previousData = $env:CLIP_FACTORY_DATA
        try {
            $env:CLIP_FACTORY_DATA = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) $tauriConfig.identifier
            & $python -m app.prepare_models
            if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar Ollama e os modelos. Confira a mensagem acima e rode o instalador novamente." }
        } finally {
            $env:CLIP_FACTORY_DATA = $previousData
        }
    }
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
