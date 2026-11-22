param([switch]$Launch, [switch]$PrepareModels)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "windows-common.ps1")
$cppWorkload = "--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --passive --norestart"

if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    throw "Abra o Windows PowerShell de 64 bits em um Windows x64."
}

function Update-SessionPath {
    # Installers write Path to the registry, but this process keeps its original copy.
    $paths = @(
        [Environment]::GetEnvironmentVariable("Path", "Machine")
        [Environment]::GetEnvironmentVariable("Path", "User")
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links")
        (Join-Path $env:ProgramFiles "WinGet\Links")
        $env:Path
    )
    $env:Path = (($paths -split ";" | Where-Object { $_ } | Select-Object -Unique) -join ";")
}

function Install-WinGetPackage {
    param([string]$Id, [string[]]$Options = @())

    if (!(Get-Command winget.exe -CommandType Application -ErrorAction SilentlyContinue)) {
        throw "WinGet indisponivel. Instale ou atualize o Instalador de Aplicativo (App Installer) pela Microsoft Store e abra um novo PowerShell."
    }

    Write-Host "Instalando $Id..."
    & winget.exe install --id $Id --exact --source winget --architecture x64 --accept-source-agreements --accept-package-agreements @Options
    if ($LASTEXITCODE -ne 0) {
        throw "WinGet falhou ao instalar $Id (codigo $LASTEXITCODE). Confira a mensagem acima. Se o instalador pedir, reinicie o Windows e rode este script novamente."
    }
    Update-SessionPath
}

function Add-RustupToSessionPath {
    if (Get-Command rustup.exe -CommandType Application -ErrorAction SilentlyContinue) { return }

    $cargoHome = if ($env:CARGO_HOME) { $env:CARGO_HOME } else { Join-Path $env:USERPROFILE ".cargo" }
    $cargoBin = Join-Path $cargoHome "bin"
    if (Test-Path -LiteralPath (Join-Path $cargoBin "rustup.exe") -PathType Leaf) {
        $env:Path = "$cargoBin;$env:Path"
    }
}

function Install-Rustup {
    Write-Host "Baixando o Rustup oficial para Windows x64..."
    $ProgressPreference = "SilentlyContinue"
    $url = "https://static.rust-lang.org/rustup/dist/$WindowsRustTarget/rustup-init.exe"
    $tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("clip-factory-rustup-" + [guid]::NewGuid())
    $null = New-Item -ItemType Directory -Path $tempDir

    try {
        $installer = Join-Path $tempDir "rustup-init.exe"
        $checksum = Join-Path $tempDir "rustup-init.exe.sha256"
        Invoke-WebRequest -UseBasicParsing -Uri "${url}.sha256" -OutFile $checksum
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $installer
        $expectedHash = ((Get-Content -LiteralPath $checksum -Raw).Trim() -split "\s+")[0]
        $actualHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash
        if ($expectedHash -notmatch "^[0-9a-f]{64}$" -or $expectedHash -ne $actualHash) {
            throw "O SHA-256 do instalador do Rustup nao confere. Rode o script novamente para baixar outra copia."
        }

        Write-Host "Instalando Rust stable com MSVC..."
        & $installer -y --default-host $WindowsRustTarget --default-toolchain stable --profile minimal
        if ($LASTEXITCODE -ne 0) {
            throw "rustup-init.exe falhou (codigo $LASTEXITCODE). Confira a mensagem do instalador acima."
        }
    } finally {
        Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Test-Node {
    if (!(Get-Command node.exe -CommandType Application -ErrorAction SilentlyContinue)) { return $false }
    $nodeVersion = & node.exe --version
    return ($LASTEXITCODE -eq 0 -and $nodeVersion -match "^v(\d+)\." -and
        [int]$Matches[1] -ge 22 -and
        [bool](Get-Command npm.cmd -CommandType Application -ErrorAction SilentlyContinue))
}

function Test-FFmpeg {
    foreach ($tool in "ffmpeg.exe", "ffprobe.exe") {
        if (!(Get-Command $tool -CommandType Application -ErrorAction SilentlyContinue)) { return $false }
    }

    $ErrorActionPreference = "Continue"
    & ffprobe.exe -version *> $null
    if ($LASTEXITCODE -ne 0) { return $false }
    $filters = & ffmpeg.exe -hide_banner -filters 2>$null
    if ($LASTEXITCODE -ne 0 -or !($filters | Select-String -Quiet ' ass ')) { return $false }

    & ffmpeg.exe -v error -f lavfi -i "color=s=256x256:r=30" -frames:v 1 -c:v libx264 -f null - *> $null
    return $LASTEXITCODE -eq 0
}

function Test-WebView2 {
    $client = "Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    foreach ($key in "HKLM:\SOFTWARE\WOW6432Node\$client", "HKCU:\SOFTWARE\$client") {
        $version = Get-ItemPropertyValue -Path $key -Name pv -ErrorAction SilentlyContinue
        if ($version -and $version -ne "0.0.0.0") { return $true }
    }
    return $false
}

function Test-CppBuildTools {
    if (!(Test-Path -LiteralPath $vswhere)) { return $false }
    $compiler = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    $sdkKey = "Microsoft\Windows Kits\Installed Roots"
    $sdkRoot = Get-ItemPropertyValue -Path "HKLM:\SOFTWARE\WOW6432Node\$sdkKey" -Name KitsRoot10 -ErrorAction SilentlyContinue
    if (!$sdkRoot) {
        $sdkRoot = Get-ItemPropertyValue -Path "HKLM:\SOFTWARE\$sdkKey" -Name KitsRoot10 -ErrorAction SilentlyContinue
    }
    if (!$compiler -or !$sdkRoot) { return $false }

    foreach ($sdk in Get-ChildItem -LiteralPath (Join-Path $sdkRoot "Lib") -Directory -ErrorAction SilentlyContinue) {
        if ((Test-Path -LiteralPath (Join-Path $sdk.FullName "um\x64\kernel32.lib")) -and
            (Test-Path -LiteralPath (Join-Path $sdk.FullName "ucrt\x64\ucrt.lib"))) {
            return $true
        }
    }
    return $false
}

Update-SessionPath

if (!(Get-Python311)) { Install-WinGetPackage "Python.Python.3.11" }
if (!(Get-Python311)) { throw "Python 3.11 x64 indisponivel. Verifique o comando py -3.11-64 em um novo PowerShell." }

if (!(Test-Node)) { Install-WinGetPackage "OpenJS.NodeJS.LTS" @("--installer-type", "wix") }
if (!(Test-Node)) { throw "Node.js 22+ ou npm indisponivel. Verifique node --version e npm.cmd --version em um novo PowerShell." }

if (!(Test-FFmpeg)) { Install-WinGetPackage "Gyan.FFmpeg" }
if (!(Test-FFmpeg)) { throw "FFmpeg/FFprobe indisponiveis ou sem libass/libx264. Confira qual executavel aparece em Get-Command ffmpeg.exe." }

if (!(Test-WebView2)) { Install-WinGetPackage "Microsoft.EdgeWebView2Runtime" }
if (!(Test-WebView2)) { throw "WebView2 Runtime indisponivel. Conclua o instalador do runtime e tente novamente." }

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (!(Test-CppBuildTools)) {
    $buildTools = $null
    if (Test-Path -LiteralPath $vswhere) {
        $buildTools = & $vswhere -latest -products Microsoft.VisualStudio.Product.BuildTools -version '[17.0,18.0)' -property installationPath
    }
    if ($buildTools) {
        Write-Host "Adicionando C++ e Windows SDK ao Visual Studio Build Tools..."
        $installer = Join-Path (Split-Path -Parent $vswhere) "setup.exe"
        $process = Start-Process -FilePath $installer -ArgumentList ('modify --installPath "{0}" {1}' -f $buildTools, $cppWorkload) -Verb RunAs -PassThru -Wait
        if ($process.ExitCode -ne 0) {
            throw "Visual Studio Installer retornou $($process.ExitCode). Se ele pedir, reinicie o Windows e rode este script novamente."
        }
    } else {
        Install-WinGetPackage "Microsoft.VisualStudio.2022.BuildTools" @("--override", "$cppWorkload --wait")
    }
}
if (!(Test-CppBuildTools)) { throw "C++ MSVC ou Windows SDK ausente. Abra o Visual Studio Installer e confira a carga de trabalho Desenvolvimento para desktop com C++." }

$vcRuntime = Get-ItemPropertyValue -Path "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" -Name Installed -ErrorAction SilentlyContinue
if ($vcRuntime -ne 1) {
    Install-WinGetPackage "Microsoft.VCRedist.2015+.x64"
}

Update-SessionPath
Add-RustupToSessionPath
if (!(Get-Command rustup.exe -CommandType Application -ErrorAction SilentlyContinue)) {
    Install-Rustup
    Update-SessionPath
    Add-RustupToSessionPath
}
if (!(Get-Command rustup.exe -CommandType Application -ErrorAction SilentlyContinue)) {
    throw "Rustup indisponivel. Abra um novo PowerShell e rode este script novamente."
}

$null = Get-WindowsRustToolchain

Write-Host "Dependencias do Windows prontas."
if ($Launch -or $PrepareModels) {
    & (Join-Path $PSScriptRoot "dev.ps1") -PrepareModels:$PrepareModels -PrepareOnly:(!$Launch)
    if (!$Launch) {
        $dev = Join-Path $PSScriptRoot "dev.ps1"
        Write-Host ('Para abrir o Clip Factory, execute: powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $dev)
    }
} else {
    Write-Host "Na raiz do Clip Factory, execute: powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1"
}
