param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "ClipFactory\source"),
    [switch]$Launch
)

$ErrorActionPreference = "Stop"

if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    throw "Abra o Windows PowerShell de 64 bits em um Windows x64."
}

$InstallDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($InstallDir)
$setupPath = "scripts\setup-windows.ps1"
$modelsPath = "services\engine\app\prepare_models.py"

if (!(Test-Path -LiteralPath $InstallDir)) {
    $parent = Split-Path -Parent $InstallDir
    $null = New-Item -ItemType Directory -Path $parent -Force
    $staging = Join-Path $parent ("clip-factory-download-" + [guid]::NewGuid())
    $null = New-Item -ItemType Directory -Path $staging

    try {
        $zip = Join-Path $staging "source.zip"
        $extracted = Join-Path $staging "extracted"
        Write-Host "Baixando Clip Factory do GitHub..."
        $previousProgress = $ProgressPreference
        try {
            $ProgressPreference = "SilentlyContinue"
            Invoke-WebRequest -UseBasicParsing -Uri "https://codeload.github.com/LukasPio/clip-factory/zip/refs/heads/main" -OutFile $zip
            Expand-Archive -LiteralPath $zip -DestinationPath $extracted
        } finally {
            $ProgressPreference = $previousProgress
        }
        $source = Join-Path $extracted "clip-factory-main"
        if (!(Test-Path -LiteralPath (Join-Path $source $setupPath) -PathType Leaf) -or
            !(Test-Path -LiteralPath (Join-Path $source $modelsPath) -PathType Leaf)) {
            throw "A versao publicada no GitHub ainda nao inclui o instalador completo."
        }
        [System.IO.Directory]::Move($source, $InstallDir)
    } finally {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$setup = Join-Path $InstallDir $setupPath
if (!(Test-Path -LiteralPath $setup -PathType Leaf) -or
    !(Test-Path -LiteralPath (Join-Path $InstallDir $modelsPath) -PathType Leaf)) {
    throw "O destino '$InstallDir' nao contem uma versao compativel. Informe outra pasta com -InstallDir."
}

Write-Host "Preparando Clip Factory em $InstallDir..."
& $setup -PrepareModels -Launch:$Launch
