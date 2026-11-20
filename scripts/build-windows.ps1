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
$Runtime = Join-Path $Stage "runtime"
New-Item -ItemType Directory -Force $Media | Out-Null
New-Item -ItemType Directory -Force $Runtime | Out-Null
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

# Ship the verified Windows runtime used by yt-dlp, with its license and without npm.
$nodeVersion = 'v24.22.3'
$nodePackage = "node-$nodeVersion-win-x64"
$nodeArchive = Join-Path $Stage "$nodePackage.zip"
$nodeHash = 'e612af99f626ab415ea225af6bce5c971feb448cb5cae250bb1c3fa50c5f7d9f'
if (!(Test-Path -LiteralPath $nodeArchive) -or (Get-FileHash -LiteralPath $nodeArchive).Hash -ne $nodeHash) {
    Invoke-WebRequest -UseBasicParsing -Uri "https://nodejs.org/dist/$nodeVersion/$nodePackage.zip" -OutFile $nodeArchive
}
if ((Get-FileHash -LiteralPath $nodeArchive).Hash -ne $nodeHash) { throw "Checksum do Node.js inválido." }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$nodeZip = [System.IO.Compression.ZipFile]::OpenRead($nodeArchive)
try {
    [System.IO.Compression.ZipFileExtensions]::ExtractToFile($nodeZip.GetEntry("$nodePackage/node.exe"), (Join-Path $Runtime 'node.exe'), $true)
    [System.IO.Compression.ZipFileExtensions]::ExtractToFile($nodeZip.GetEntry("$nodePackage/LICENSE"), (Join-Path $Runtime 'node-license.txt'), $true)
} finally { $nodeZip.Dispose() }

# App-local CRT avoids a separate Visual C++ installer on the end user's PC.
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vsRoot = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$crt = Get-ChildItem -Path "$vsRoot\VC\Redist\MSVC\*\x64\Microsoft.VC143.CRT" -Directory |
    Sort-Object { [version]$_.Parent.Parent.Name } -Descending | Select-Object -First 1
if (!$crt) { throw "Runtime redistribuível VC143 ausente. Execute o preparo do Windows antes de empacotar." }
$crtArgs = @()
foreach ($dll in Get-ChildItem -LiteralPath $crt.FullName -Filter '*.dll' -File) {
    Copy-Item -LiteralPath $dll.FullName -Destination $Runtime -Force
    $crtArgs += @('--add-binary', "$($dll.FullName):.")
}

$python = Initialize-EngineEnvironment -Root $Root -Extra build
$rustToolchain = Get-WindowsRustToolchain
$target = $WindowsRustTarget
$dist = Join-Path $Stage "dist"
& $python -m PyInstaller --noconfirm --clean --onefile --console --name "clip-engine-$target" --distpath $dist --workpath (Join-Path $Stage "work") --specpath $Stage --collect-all faster_whisper --collect-all ctranslate2 --collect-all onnxruntime --collect-all yt_dlp --collect-all yt_dlp_ejs --copy-metadata yt-dlp-ejs --collect-data certifi @crtArgs services/engine/entrypoint.py
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
