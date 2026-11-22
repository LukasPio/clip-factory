param([Parameter(Mandatory)][string]$TargetDir)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "windows-common.ps1")
$root = Split-Path -Parent $PSScriptRoot

# Refresh the process PATH after WinGet installs any missing Windows dependencies.
. (Join-Path $PSScriptRoot "setup-windows.ps1") -PrepareModels
$toolDirectories = @(
    foreach ($name in "ffmpeg.exe", "ffprobe.exe", "node.exe") {
        Split-Path -Parent (Get-Command $name -CommandType Application | Select-Object -First 1 -ExpandProperty Source)
    }
) | Select-Object -Unique
[IO.File]::WriteAllText(
    (Join-Path $root "source-tools.json"),
    (ConvertTo-Json -InputObject @($toolDirectories) -Compress),
    [Text.UTF8Encoding]::new($false)
)

$previousTargetDir = $env:CARGO_TARGET_DIR
$previousSourceBuild = $env:CLIP_FACTORY_SOURCE_BUILD
$previousToolchain = $env:RUSTUP_TOOLCHAIN
Push-Location (Join-Path $root "apps\desktop")
try {
    $env:CARGO_TARGET_DIR = $TargetDir
    $env:CLIP_FACTORY_SOURCE_BUILD = "1"
    $rustToolchain = Get-WindowsRustToolchain
    if ($rustToolchain) { $env:RUSTUP_TOOLCHAIN = $rustToolchain }
    npm.cmd run tauri -- build --ci --no-bundle --target $WindowsRustTarget -- --locked
    if ($LASTEXITCODE -ne 0) { throw "Falha ao compilar o aplicativo Clip Factory." }
} finally {
    $env:CARGO_TARGET_DIR = $previousTargetDir
    $env:CLIP_FACTORY_SOURCE_BUILD = $previousSourceBuild
    $env:RUSTUP_TOOLCHAIN = $previousToolchain
    Pop-Location
}

# Publish the executable only after all runtime files and the build are ready.
$exe = Join-Path $root "clip-factory.exe"
$stagedExe = Join-Path $root "clip-factory-build.exe"
Copy-Item -LiteralPath (Join-Path $TargetDir "$WindowsRustTarget/release/clip-factory.exe") -Destination $stagedExe -Force
[IO.File]::Move($stagedExe, $exe)
