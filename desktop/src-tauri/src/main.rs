#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use tauri::{Manager, RunEvent};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_PORT: u16 = 8000;

fn is_backend_ready() -> bool {
    let addr: SocketAddr = format!("{BACKEND_HOST}:{BACKEND_PORT}").parse().unwrap();
    TcpStream::connect_timeout(&addr, Duration::from_millis(250)).is_ok()
}

fn find_backend_dir() -> Option<PathBuf> {
    // 1. Check relative to executable (walk up to 6 parent directories)
    if let Ok(exe) = std::env::current_exe() {
        let mut cur: Option<&Path> = exe.parent();
        for _ in 0..6 {
            if let Some(dir) = cur {
                let candidate = dir.join("backend");
                if candidate.join("app").join("main.py").exists() {
                    return Some(candidate);
                }
                cur = dir.parent();
            } else {
                break;
            }
        }
    }

    // 2. Check current working directory and its parents
    if let Ok(cwd) = std::env::current_dir() {
        let mut cur: Option<&Path> = Some(cwd.as_path());
        for _ in 0..4 {
            if let Some(dir) = cur {
                let candidate = dir.join("backend");
                if candidate.join("app").join("main.py").exists() {
                    return Some(candidate);
                }
                if dir.join("app").join("main.py").exists() {
                    return Some(dir.to_path_buf());
                }
                cur = dir.parent();
            } else {
                break;
            }
        }
    }

    // 3. Fallback to compile-time workspace root
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    if let Some(repo_root) = manifest_dir.parent().and_then(|p| p.parent()) {
        let candidate = repo_root.join("backend");
        if candidate.join("app").join("main.py").exists() {
            return Some(candidate);
        }
    }

    None
}

fn spawn_backend_if_needed() -> Option<Child> {
    if is_backend_ready() {
        return None;
    }

    let backend_dir = find_backend_dir()?;
    let venv_python = if cfg!(target_os = "windows") {
        backend_dir.join(".venv").join("Scripts").join("python.exe")
    } else {
        backend_dir.join(".venv").join("bin").join("python")
    };

    let python_bin = if venv_python.exists() {
        venv_python
    } else {
        PathBuf::from(if cfg!(target_os = "windows") { "python" } else { "python3" })
    };

    let mut cmd = Command::new(python_bin);
    cmd.current_dir(&backend_dir)
        .args([
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            BACKEND_HOST,
            "--port",
            &BACKEND_PORT.to_string(),
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    #[cfg(target_os = "windows")]
    {
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    cmd.spawn().ok()
}

fn main() {
    let backend_child: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));
    let backend_for_setup = Arc::clone(&backend_child);
    let backend_for_exit = Arc::clone(&backend_child);

    let app = tauri::Builder::default()
        .setup(move |app| {
            let handle = app.handle().clone();
            let child_slot = Arc::clone(&backend_for_setup);

            thread::spawn(move || {
                if let Some(child) = spawn_backend_if_needed() {
                    if let Ok(mut guard) = child_slot.lock() {
                        *guard = Some(child);
                    }
                }

                // Wait up to 20s for FastAPI backend to listen on 127.0.0.1:8000
                let mut ready = false;
                for _ in 0..100 {
                    if is_backend_ready() {
                        ready = true;
                        break;
                    }
                    thread::sleep(Duration::from_millis(200));
                }

                if let Some(win) = handle.get_webview_window("main") {
                    if ready {
                        let url = format!("http://{BACKEND_HOST}:{BACKEND_PORT}")
                            .parse()
                            .expect("valid local URL");
                        let _ = win.navigate(url);
                    } else {
                        let _ = win.eval(
                            "const el = document.getElementById('status'); if (el) el.textContent = 'Không thể khởi động backend (127.0.0.1:8000). Hãy kiểm tra backend/.venv.';",
                        );
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Dupin Desktop");

    app.run(move |_app_handle, event| {
        if let RunEvent::Exit = event {
            if let Ok(mut guard) = backend_for_exit.lock() {
                if let Some(mut child) = guard.take() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        }
    });
}
