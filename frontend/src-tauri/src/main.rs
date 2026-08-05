// MailSort desktop shell entry point.
//
// Today this just hosts the React UI in Tauri's WebView; the FastAPI
// backend (../../backend) is expected to already be running on
// localhost:8000 (see repo README). Packaging the backend as a Tauri
// "sidecar" binary (PyInstaller output launched via
// tauri_plugin_shell::ShellExt::sidecar) is the Phase 2 step that removes
// the manual `uvicorn` step for end users.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows_subsystem")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running MailSort");
}
