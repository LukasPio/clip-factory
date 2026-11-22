use std::{
    ffi::OsString,
    path::{Path, PathBuf},
    process::Command,
};

pub fn enabled() -> bool {
    cfg!(windows) && option_env!("CLIP_FACTORY_SOURCE_BUILD") == Some("1")
}

pub fn engine(source: &Path) -> Result<Command, Box<dyn std::error::Error>> {
    let mut command = Command::new(source.join(".venv/Scripts/python.exe"));
    command.args(["-m", "app.main"]);
    command.current_dir(source.join("services/engine"));
    let mut paths: Vec<PathBuf> =
        serde_json::from_slice(&std::fs::read(source.join("source-tools.json"))?)?;
    if let Some(path) = std::env::var_os("PATH") {
        paths.extend(std::env::split_paths(&path));
    }
    command.env("PATH", std::env::join_paths(paths)?);
    Ok(command)
}

pub fn update() -> Result<Option<PathBuf>, String> {
    if !enabled() {
        return Err("Atualização pelo GitHub indisponível nesta instalação.".into());
    }

    let current_exe = std::env::current_exe().map_err(|error| error.to_string())?;
    let source = current_exe
        .parent()
        .ok_or("Pasta do aplicativo indisponível.")?;
    let versions = source.parent().ok_or("Pasta de versões indisponível.")?;
    let root = versions.parent().ok_or("Pasta da instalação indisponível.")?;
    let mut powershell = OsString::from("powershell.exe");
    if let Some(windows) = std::env::var_os("SystemRoot") {
        powershell = PathBuf::from(windows)
            .join("System32/WindowsPowerShell/v1.0/powershell.exe")
            .into_os_string();
    }
    let mut installer = Command::new(powershell);
    installer
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
        ])
        .arg(source.join("scripts/install-windows.ps1"))
        .arg("-InstallDir")
        .arg(root)
        .current_dir(source);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        installer.creation_flags(0x08000000);
    }
    let output = installer.output().map_err(|error| error.to_string())?;
    if !output.status.success() {
        let log = root.join("update.log");
        let details = [output.stdout.as_slice(), b"\r\n", output.stderr.as_slice()].concat();
        std::fs::write(&log, details).map_err(|error| error.to_string())?;
        return Err(format!(
            "Não foi possível atualizar pelo GitHub. Consulte o log em {}.",
            log.display()
        ));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let revision = stdout
        .lines()
        .rev()
        .find_map(|line| line.strip_prefix("CLIP_FACTORY_READY="))
        .filter(|sha| sha.len() == 40 && sha.bytes().all(|byte| byte.is_ascii_hexdigit()))
        .ok_or("O instalador não confirmou a revisão instalada.")?;
    let updated = versions.join(revision).join("clip-factory.exe");
    if !updated.is_file() {
        return Err("O executável atualizado não foi encontrado.".into());
    }
    Ok((updated != current_exe).then_some(updated))
}
