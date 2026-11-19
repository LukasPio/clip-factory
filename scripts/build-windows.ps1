param(
    [Parameter(Mandatory=$true)][string]$FFmpegDir,
    [Parameter(Mandatory=$true)][string]$ThirdPartyNotices
)
$ErrorActionPreference = "Stop"
$FFmpegDir = (Resolve-Path $FFmpegDir).Path
$ThirdPartyNotices = (Resolve-Path $ThirdPartyNotices).Path
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Shell = Join-Path $Root "apps/desktop/src-tauri"
$Stage = Join-Path $Shell "binaries"
$Media = Join-Path $Stage "media-tools"
New-Item -ItemType Directory -Force $Media | Out-Null
foreach ($name in "ffmpeg", "ffprobe") {
    Copy-Item (Join-Path $FFmpegDir "$name.exe") $Media -Force
}
Copy-Item $ThirdPartyNotices (Join-Path $Media "third-party-notices.txt") -Force
& (Join-Path $Media "ffmpeg.exe") -v error -f lavfi -i "color=s=256x256" -frames:v 1 -c:v libx264 -f null -
if ($LASTEXITCODE -ne 0) { throw "A distribuição FFmpeg precisa incluir libx264." }
$filters = & (Join-Path $Media "ffmpeg.exe") -hide_banner -filters
if (!($filters | Select-String ' ass ')) { throw "A distribuição FFmpeg precisa incluir libass." }

if (!(Test-Path .venv/Scripts/python.exe)) {
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Instale Python 3.11 x64." }
}
$python = Join-Path $Root ".venv/Scripts/python.exe"
& $python -m pip install "uv>=0.8,<1"
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar uv." }
$env:UV_PROJECT_ENVIRONMENT = Join-Path $Root ".venv"
& $python -m uv sync --project services/engine --locked --inexact --extra build
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependências do motor." }

$target = "x86_64-pc-windows-msvc"
$dist = Join-Path $Stage "dist"
& $python -m PyInstaller --noconfirm --clean --onefile --console --name "clip-engine-$target" --distpath $dist --workpath (Join-Path $Stage "work") --specpath $Stage --collect-all faster_whisper --collect-all ctranslate2 --collect-all onnxruntime --collect-all yt_dlp --collect-data certifi services/engine/entrypoint.py
if ($LASTEXITCODE -ne 0) { throw "Falha ao empacotar o motor Python." }
Copy-Item (Join-Path $dist "clip-engine-$target.exe") $Stage -Force

Push-Location apps/desktop
try {
    if (Test-Path package-lock.json) { npm.cmd ci } else { npm.cmd install }
    if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependências da interface." }
    npm.cmd run tauri -- build --target $target --config src-tauri/tauri.windows-bundle.json
    if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o instalador NSIS." }
} finally {
    Pop-Location
}
