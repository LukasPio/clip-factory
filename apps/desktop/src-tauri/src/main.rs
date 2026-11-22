#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod source_install;

use serde::{Deserialize, Serialize};
use std::{
    io::{BufRead, BufReader},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};
use tauri::{Manager, RunEvent, State};

#[derive(Clone, Deserialize, Serialize)]
struct Connection {
    url: String,
    token: String,
}

struct Engine {
    connection: Connection,
    child: Mutex<Child>,
}

impl Engine {
    fn stop(&self) {
        if let Ok(mut child) = self.child.lock() {
            drop(child.stdin.take());
            let deadline = Instant::now() + Duration::from_secs(6);
            while Instant::now() < deadline {
                if matches!(child.try_wait(), Ok(Some(_))) {
                    return;
                }
                thread::sleep(Duration::from_millis(50));
            }
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[tauri::command]
fn engine_connection(engine: State<'_, Engine>) -> Connection {
    engine.connection.clone()
}

#[tauri::command]
fn source_updates_enabled() -> bool {
    source_install::enabled()
}

#[tauri::command]
async fn update_from_github(app: tauri::AppHandle) -> Result<bool, String> {
    let updated = tauri::async_runtime::spawn_blocking(source_install::update)
        .await
        .map_err(|error| error.to_string())??;
    let Some(executable) = updated else {
        return Ok(false);
    };
    app.state::<Engine>().stop();
    Command::new(executable)
        .spawn()
        .map_err(|error| format!("Abra a nova versão pelo menu Iniciar. ({error})"))?;
    app.exit(0);
    Ok(true)
}

fn launch(
    executable_dir: PathBuf,
    resources: PathBuf,
    data: PathBuf,
) -> Result<Engine, Box<dyn std::error::Error>> {
    let source_build = source_install::enabled();
    let mut command = if source_build {
        source_install::engine(&executable_dir)?
    } else if cfg!(debug_assertions) {
        let mut command = Command::new(
            std::env::var_os("CLIP_FACTORY_PYTHON").unwrap_or_else(|| "python".into()),
        );
        command.args(["-m", "app.main"]);
        command.current_dir(
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../services/engine"),
        );
        command
    } else {
        Command::new(executable_dir.join(if cfg!(windows) {
            "clip-engine.exe"
        } else {
            "clip-engine"
        }))
    };
    if !cfg!(debug_assertions) {
        command.env("CLIP_FACTORY_MODE", "production");
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
        if !cfg!(debug_assertions) && !source_build {
            command.env("CLIP_FACTORY_BIN", resources.join("media-tools"));
            command.env("CLIP_FACTORY_NODE", resources.join("node.exe"));
        }
    }
    let mut child = command
        .env("CLIP_FACTORY_DATA", data)
        .env("CLIP_FACTORY_MANAGED", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()?;
    let stdout = child.stdout.take().ok_or("Saída do motor indisponível.")?;
    let (tx, rx) = std::sync::mpsc::sync_channel(1);
    thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        if reader.read_line(&mut line).is_ok() {
            let _ = tx.send(serde_json::from_str::<Connection>(&line));
            let _ = std::io::copy(&mut reader, &mut std::io::sink());
        }
    });
    match rx.recv_timeout(Duration::from_secs(75)) {
        Ok(Ok(connection)) => Ok(Engine {
            connection,
            child: Mutex::new(child),
        }),
        _ => {
            let _ = child.kill();
            let _ = child.wait();
            Err("O motor local não iniciou. Execute o diagnóstico de instalação.".into())
        }
    }
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            engine_connection,
            source_updates_enabled,
            update_from_github
        ])
        .setup(|app| {
            let executable_dir = std::env::current_exe()?
                .parent()
                .ok_or("Diretório do aplicativo indisponível.")?
                .to_owned();
            let data = app.path().app_local_data_dir()?;
            app.manage(launch(executable_dir, app.path().resource_dir()?, data)?);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Falha ao abrir o Clip Factory");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            handle.state::<Engine>().stop();
        }
    });
}
