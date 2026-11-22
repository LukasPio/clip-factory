param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "ClipFactory\source"),
    [switch]$Launch
)

$ErrorActionPreference = "Stop"
if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    throw "Abra o Windows PowerShell de 64 bits em um Windows x64."
}

$InstallDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($InstallDir)
$versions = Join-Path $InstallDir "versions"
$null = New-Item -ItemType Directory -Path $versions -Force
try {
    $lock = [IO.File]::Open((Join-Path $InstallDir "install.lock"), "OpenOrCreate", "Write", "None")
} catch [IO.IOException] {
    throw "Outra instalacao ou atualizacao do Clip Factory esta em andamento."
}

try {
    $head = Invoke-RestMethod -Uri "https://api.github.com/repos/LukasPio/clip-factory/commits/main" `
        -UserAgent "ClipFactory-Windows-Installer" -TimeoutSec 30
    $revision = $head.sha
    if ($revision -cnotmatch '^[0-9a-f]{40}$') { throw "Revisao invalida recebida do GitHub." }
    $source = Join-Path $versions $revision
    $exe = Join-Path $source "clip-factory.exe"
    $buildPath = "scripts\build-source-windows.ps1"

    if (!(Test-Path -LiteralPath $source)) {
        $staging = Join-Path $versions ("download-" + [guid]::NewGuid())
        $null = New-Item -ItemType Directory -Path $staging
        try {
            $zip = Join-Path $staging "source.zip"
            $extracted = Join-Path $staging "extracted"
            $ProgressPreference = "SilentlyContinue"
            Write-Host "Baixando a revisao $revision do GitHub..."
            Invoke-WebRequest -UseBasicParsing -Uri "https://codeload.github.com/LukasPio/clip-factory/zip/$revision" -OutFile $zip -TimeoutSec 180
            Expand-Archive -LiteralPath $zip -DestinationPath $extracted
            $downloaded = Join-Path $extracted "clip-factory-$revision"
            if (!(Test-Path -LiteralPath (Join-Path $downloaded $buildPath) -PathType Leaf)) {
                throw "A revisao publicada no GitHub nao inclui o instalador do aplicativo."
            }
            [IO.Directory]::Move($downloaded, $source)
        } finally {
            Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    if (!(Test-Path -LiteralPath $exe -PathType Leaf)) {
        & (Join-Path $source $buildPath) -TargetDir (Join-Path $InstallDir "cargo-target")
    }
    if (!(Test-Path -LiteralPath $exe -PathType Leaf)) { throw "O executavel do Clip Factory nao foi gerado." }

    $shell = New-Object -ComObject WScript.Shell
    $programs = [Environment]::GetFolderPath("Programs")
    $shortcut = $shell.CreateShortcut((Join-Path $programs "Clip Factory.lnk"))
    $shortcut.TargetPath = $exe
    $shortcut.WorkingDirectory = $source
    $shortcut.Description = "Clip Factory"
    $shortcut.Save()

    Write-Host "Clip Factory disponivel no menu Iniciar."
    if ($Launch) { Start-Process -FilePath $exe -WorkingDirectory $source }
    Write-Output "CLIP_FACTORY_READY=$revision"
} finally {
    $lock.Dispose()
}
