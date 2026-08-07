// MailSort desktop shell entry point.
//
// Spawns the bundled FastAPI backend (a PyInstaller-frozen executable, see
// backend/mailsort_backend.spec and backend/run_server.py) as a Tauri
// sidecar on startup, and kills it when the app exits — this is what turns
// "run uvicorn manually, then open the frontend" (the dev workflow, see
// repo README) into a single double-click for an end user of the packaged
// installer. See build_installer.ps1 for how the sidecar binary itself
// gets built and placed where tauri.conf.json's bundle.externalBin expects
// it (src-tauri/binaries/mailsort-backend-<target-triple>[.exe]).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows_subsystem")]

use std::sync::Mutex;

use tauri::Manager;
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandChild;

/// Holds the running backend sidecar's handle so it can be killed on exit.
/// A `None` here (rather than the sidecar simply not existing) covers the
/// window between app startup and the spawn actually completing, and the
/// window after it's already been killed — both are valid, non-error
/// states, not bugs.
struct BackendProcess(Mutex<Option<CommandChild>>);

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            let sidecar_command = app
                .shell()
                .sidecar("mailsort-backend")
                .expect("failed to resolve the mailsort-backend sidecar binary");
            let (mut rx, child) = sidecar_command
                .spawn()
                .expect("failed to spawn the mailsort-backend sidecar");

            *app.state::<BackendProcess>().0.lock().unwrap() = Some(child);

            // The frontend has its own "backend unreachable" fallback
            // message (see App.tsx) for the few hundred ms between the
            // window appearing and uvicorn finishing startup — piping the
            // sidecar's own stdout/stderr into this process's own console
            // is purely for diagnosing failures during setup, not
            // something the packaged app's end user needs to see.
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            println!("[backend] {}", String::from_utf8_lossy(&line).trim_end());
                        }
                        CommandEvent::Stderr(line) => {
                            eprintln!("[backend] {}", String::from_utf8_lossy(&line).trim_end());
                        }
                        CommandEvent::Error(err) => {
                            eprintln!("[backend] error: {err}");
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[backend] exited: {:?}", payload);
                        }
                        _ => {}
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building MailSort")
        .run(|app_handle, event| {
            // Without this, closing the MailSort window left the backend
            // sidecar running forever as an orphaned background process —
            // invisible to the user, still holding the sqlite file open,
            // and (since it keeps listening on 127.0.0.1:8000) blocking
            // the next launch's own sidecar from binding the same port.
            if let tauri::RunEvent::ExitRequested { .. } = event {
                if let Some(child) = app_handle.state::<BackendProcess>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
