$WindowsRustTarget = "x86_64-pc-windows-msvc"
$Python311Check = "import platform, sys; sys.exit(0 if sys.version_info[:2] == (3, 11) and platform.machine().lower() in ('amd64', 'x86_64') and sys.maxsize > 2**32 else 1)"

function Test-Python311 {
    param([string]$Executable, [string[]]$Arguments = @())

    if (!(Get-Command -Name $Executable -CommandType Application -ErrorAction SilentlyContinue)) { return $false }
    $ErrorActionPreference = "Continue"
    & $Executable @Arguments -c $Python311Check *> $null
    return $LASTEXITCODE -eq 0
}

function Get-Python311 {
    if (Test-Python311 -Executable "py.exe" -Arguments @("-3.11-64")) {
        return @{ Executable = "py.exe"; Arguments = @("-3.11-64") }
    }

    $python = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($python -and $python.Source -notlike "*\Microsoft\WindowsApps\python.exe" -and
        (Test-Python311 -Executable $python.Source)) {
        return @{ Executable = $python.Source; Arguments = @() }
    }
}

function Initialize-EngineEnvironment {
    param([string]$Root, [string]$Extra)

    $venv = Join-Path $Root ".venv"
    $python = Join-Path $venv "Scripts\python.exe"
    if (!(Test-Path -LiteralPath $python)) {
        $base = Get-Python311
        if (!$base) { throw "Python 3.11 x64 indisponivel. Execute scripts/setup-windows.ps1." }
        $arguments = $base.Arguments
        & $base.Executable @arguments -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "Falha ao criar o ambiente Python em $venv." }
    }
    if (!(Test-Python311 -Executable $python)) {
        throw "O ambiente $venv nao usa um Python 3.11 x64 funcional. Renomeie a pasta .venv e execute o script novamente."
    }

    & $python -m pip install --disable-pip-version-check "uv>=0.8,<1" | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar uv." }
    $previousEnvironment = $env:UV_PROJECT_ENVIRONMENT
    try {
        $env:UV_PROJECT_ENVIRONMENT = $venv
        & $python -m uv sync --project (Join-Path $Root "services/engine") --locked --inexact --extra $Extra | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependencias do motor." }
    } finally {
        $env:UV_PROJECT_ENVIRONMENT = $previousEnvironment
    }
    return $python
}

function Test-RustCompiler {
    param([string]$Executable, [string[]]$Arguments = @())

    if (!(Get-Command -Name $Executable -CommandType Application -ErrorAction SilentlyContinue)) { return $false }
    $ErrorActionPreference = "Continue"
    $version = & $Executable @Arguments -vV 2>$null
    return ($LASTEXITCODE -eq 0 -and $version -contains "host: $WindowsRustTarget")
}

function Get-WindowsRustToolchain {
    if ((Test-RustCompiler -Executable "rustc.exe") -and
        (Get-Command cargo.exe -CommandType Application -ErrorAction SilentlyContinue)) { return }

    if (!(Get-Command rustup.exe -CommandType Application -ErrorAction SilentlyContinue)) {
        throw "Rust/MSVC indisponivel. Execute scripts/setup-windows.ps1."
    }
    $toolchain = "stable-$WindowsRustTarget"
    if (!(Test-RustCompiler -Executable "rustup.exe" -Arguments @("run", $toolchain, "rustc"))) {
        Write-Host "Preparando Rust stable/MSVC para o Clip Factory..."
        & rustup.exe toolchain install $toolchain --profile minimal | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar Rust stable/MSVC. Confira a mensagem do Rustup acima." }
    }
    return $toolchain
}
