param(
    [Parameter(Mandatory=$true)][string]$FFmpegDir,
    [Parameter(Mandatory=$true)][string]$ThirdPartyNotices
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "windows-common.ps1")
$FFmpegDir = (Resolve-Path -LiteralPath $FFmpegDir).Path
$ThirdPartyNotices = (Resolve-Path -LiteralPath $ThirdPartyNotices).Path
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Shell = Join-Path $Root "apps/desktop/src-tauri"
$Stage = Join-Path $Shell "binaries"
$Media = Join-Path $Stage "media-tools"
New-Item -ItemType Directory -Force $Media | Out-Null
foreach ($name in "ffmpeg", "ffprobe") {
    Copy-Item -LiteralPath (Join-Path $FFmpegDir "$name.exe") $Media -Force
}
Copy-Item -LiteralPath $ThirdPartyNotices (Join-Path $Media "third-party-notices.txt") -Force
& (Join-Path $Media "ffmpeg.exe") -v error -f lavfi -i "color=s=256x256" -frames:v 1 -c:v libx264 -f null -
if ($LASTEXITCODE -ne 0) { throw "A distribuição FFmpeg precisa incluir libx264." }
& (Join-Path $Media "ffprobe.exe") -version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "O FFprobe da distribuicao precisa funcionar de forma independente." }
$filters = & (Join-Path $Media "ffmpeg.exe") -hide_banner -filters
if ($LASTEXITCODE -ne 0 -or !($filters | Select-String ' ass ')) { throw "A distribuição FFmpeg precisa incluir libass." }

$python = Initialize-EngineEnvironment -Root $Root -Extra build
$rustToolchain = Get-WindowsRustToolchain
$target = $WindowsRustTarget
$dist = Join-Path $Stage "dist"
& $python -m PyInstaller --noconfirm --clean --onefile --console --name "clip-engine-$target" --distpath $dist --workpath (Join-Path $Stage "work") --specpath $Stage --collect-all faster_whisper --collect-all ctranslate2 --collect-all onnxruntime --collect-all yt_dlp --collect-all yt_dlp_ejs --copy-metadata yt-dlp-ejs --collect-data certifi services/engine/entrypoint.py
if ($LASTEXITCODE -ne 0) { throw "Falha ao empacotar o motor Python." }
Copy-Item (Join-Path $dist "clip-engine-$target.exe") $Stage -Force

$previousToolchain = $env:RUSTUP_TOOLCHAIN
Push-Location apps/desktop
try {
    if ($rustToolchain) { $env:RUSTUP_TOOLCHAIN = $rustToolchain }
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependências da interface." }
    npm.cmd run tauri -- build --target $target --config src-tauri/tauri.windows-bundle.json
    if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o instalador NSIS." }
} finally {
    $env:RUSTUP_TOOLCHAIN = $previousToolchain
    Pop-Location
}
