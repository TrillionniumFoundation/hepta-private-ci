//! Bounded native adapter for the first-party Agentd chat stdio host.
//! Configuration is explicit and operator-owned; no environment-based authority.
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, mpsc};
use std::time::{Duration, Instant};
#[path = "../../hepta-ui-shared/chat_transport.rs"]
pub mod wire;
use wire::*;

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChatConfig {
    pub host_sha256: String,
    pub agentd_socket: PathBuf,
    pub agent_id: String,
    pub generation: u64,
    pub project_id: String,
    pub workspace: PathBuf,
}
impl ChatConfig {
    pub fn load(path: &Path) -> Result<Self, String> {
        let value: Self = crate::file_input::read_json_file(path, 16 * 1024)
            .map_err(|_| "Cannot read chat configuration")?;
        if !value.agentd_socket.is_absolute()
            || !value.workspace.is_absolute()
            || value.generation == 0
            || value.agent_id.is_empty()
            || value.project_id.is_empty()
            || value.host_sha256.len() != 64
            || !value
                .host_sha256
                .bytes()
                .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
        {
            return Err("Invalid chat configuration".into());
        }
        Ok(value)
    }
}

pub struct ChatRuntime {
    requests: mpsc::SyncSender<ChatRequest>,
    responses: mpsc::Receiver<Result<ChatResponse, String>>,
    child: Arc<Mutex<Option<Child>>>,
    session_id: String,
    generation: u64,
    stop: Arc<AtomicBool>,
    worker: Option<std::thread::JoinHandle<()>>,
    watchdog: Option<std::thread::JoinHandle<()>>,
}
impl ChatRuntime {
    pub fn spawn(config: ChatConfig, session_id: String) -> Result<Self, String> {
        ChatRequest {
            session_id: session_id.clone(),
            connection_generation: config.generation,
            command: ChatCommand::Create,
        }
        .validate()
        .map_err(str::to_owned)?;
        let child = Arc::new(Mutex::new(None::<Child>));
        let generation = config.generation;
        let (requests, rx) = mpsc::sync_channel::<ChatRequest>(8);
        let (tx, responses) = mpsc::sync_channel(8);
        let active = Arc::new(Mutex::new(None::<Instant>));
        let deadline = active.clone();
        let killer = child.clone();
        let stop = Arc::new(AtomicBool::new(false));
        let shutdown = stop.clone();
        let watchdog = std::thread::spawn(move || {
            while !shutdown.load(Ordering::Acquire) {
                if deadline
                    .lock()
                    .ok()
                    .and_then(|value| *value)
                    .is_some_and(|at| at.elapsed() >= Duration::from_secs(15))
                {
                    if let Ok(mut child) = killer.lock()
                        && let Some(child) = child.as_mut()
                    {
                        let _ = child.kill();
                    }
                    break;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
        });
        let worker_child = child.clone();
        let worker_stop = stop.clone();
        let worker_session = session_id.clone();
        let worker = std::thread::spawn(move || {
            let (mut stdin, stdout) =
                match launch(&config, &worker_session, &worker_stop, &worker_child) {
                    Ok(pipes) => pipes,
                    Err(error) => {
                        let _ = tx.try_send(Err(error));
                        return;
                    }
                };
            let mut reader = BufReader::new(stdout);
            while let Ok(request) = rx.recv() {
                if let Ok(mut at) = active.lock() {
                    *at = Some(Instant::now());
                }
                let result = exchange(&mut stdin, &mut reader, &request);
                if let Ok(mut at) = active.lock() {
                    *at = None;
                }
                let failed = result.is_err();
                if tx.try_send(result).is_err() || failed {
                    break;
                }
            }
        });
        Ok(Self {
            requests,
            responses,
            child,
            session_id,
            generation,
            stop,
            worker: Some(worker),
            watchdog: Some(watchdog),
        })
    }
    pub fn request(&self, command: ChatCommand) -> Result<(), String> {
        let request = ChatRequest {
            session_id: self.session_id.clone(),
            connection_generation: self.generation,
            command,
        };
        request.validate().map_err(str::to_owned)?;
        self.requests
            .try_send(request)
            .map_err(|_| "Chat is busy or disconnected".into())
    }
    pub fn poll(&self) -> Vec<Result<ChatResponse, String>> {
        self.responses.try_iter().take(8).collect()
    }
}
impl Drop for ChatRuntime {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        // Cancellation and process reaping never block the render thread.
        let (closed, _) = mpsc::sync_channel(1);
        self.requests = closed;
        let child = self.child.clone();
        let worker = self.worker.take();
        let watchdog = self.watchdog.take();
        std::thread::spawn(move || {
            if let Ok(mut child) = child.lock()
                && let Some(child) = child.as_mut()
            {
                let _ = child.kill();
                let _ = child.wait();
            }
            if let Some(worker) = worker {
                let _ = worker.join();
            }
            if let Some(watchdog) = watchdog {
                let _ = watchdog.join();
            }
        });
    }
}
fn launch(
    config: &ChatConfig,
    session_id: &str,
    stop: &AtomicBool,
    owner: &Mutex<Option<Child>>,
) -> Result<(std::process::ChildStdin, std::process::ChildStdout), String> {
    // The installation directory is trusted and must not be concurrently replaced.
    // The digest binds the configured first-party sibling, not an arbitrary env path.
    let executable = std::env::current_exe()
        .map_err(|_| "Cannot locate native installation")?
        .with_file_name(if cfg!(windows) {
            "hepta-agent-chat-host.exe"
        } else {
            "hepta-agent-chat-host"
        });
    let mut file = crate::file_input::open_regular_file(&executable)
        .map_err(|_| "Cannot read installed chat host")?;
    let mut hash = Sha256::new();
    let mut total = 0usize;
    let mut chunk = [0u8; 65536];
    loop {
        if stop.load(Ordering::Acquire) {
            return Err("Chat connection cancelled".into());
        }
        let count = file
            .read(&mut chunk)
            .map_err(|_| "Cannot verify installed chat host")?;
        if count == 0 {
            break;
        }
        total += count;
        if total > 512 * 1024 * 1024 {
            return Err("Installed chat host too large".into());
        }
        hash.update(&chunk[..count]);
    }
    if format!("{:x}", hash.finalize()) != config.host_sha256 {
        return Err("Chat host does not match configured digest".into());
    }
    let mut slot = owner.lock().map_err(|_| "Chat lifecycle unavailable")?;
    if stop.load(Ordering::Acquire) {
        return Err("Chat connection cancelled".into());
    }
    let mut child = Command::new(executable)
        .arg(&config.agentd_socket)
        .arg(&config.agent_id)
        .arg(config.generation.to_string())
        .arg(&config.project_id)
        .arg(&config.workspace)
        .arg(session_id)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| "Cannot start chat host")?;
    let input = child.stdin.take().ok_or("Missing chat input")?;
    let output = child.stdout.take().ok_or("Missing chat output")?;
    *slot = Some(child);
    Ok((input, output))
}

fn exchange(
    writer: &mut impl Write,
    reader: &mut impl BufRead,
    request: &ChatRequest,
) -> Result<ChatResponse, String> {
    let mut bytes = serde_json::to_vec(request).map_err(|_| "Invalid chat request")?;
    if bytes.len() >= MAX_CHAT_FRAME_BYTES {
        return Err("Chat request too large".into());
    }
    bytes.push(b'\n');
    writer
        .write_all(&bytes)
        .and_then(|_| writer.flush())
        .map_err(|_| "Chat disconnected; reconcile pending message")?;
    let mut response = Vec::new();
    reader
        .take(MAX_CHAT_FRAME_BYTES as u64 + 1)
        .read_until(b'\n', &mut response)
        .map_err(|_| "Chat disconnected; reconcile pending message")?;
    if response.len() > MAX_CHAT_FRAME_BYTES || response.last() != Some(&b'\n') {
        return Err("Invalid chat response".into());
    }
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Envelope {
        response: ChatResponse,
    }
    let result: Envelope = serde_json::from_slice(&response)
        .map_err(|_| "Chat request failed; reconcile pending message")?;
    if result.response.session_id != request.session_id
        || result.response.connection_generation != request.connection_generation
    {
        return Err("Stale chat response".into());
    }
    result
        .response
        .validate_for(request)
        .map_err(str::to_owned)?;
    Ok(result.response)
}

#[cfg(test)]
#[path = "chat_runtime_tests.rs"]
mod tests;
