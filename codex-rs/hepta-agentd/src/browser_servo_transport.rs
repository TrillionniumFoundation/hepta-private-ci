//! Bounded private child I/O. A stopped reader must never hold final-use
//! authority indefinitely, and cleanup must tolerate inherited pipe handles.

use std::fmt;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::process::Child;
use std::process::ChildStdout;
use std::process::Command;
use std::process::Stdio;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

use super::BrowserServoError;
use super::BrowserServoProcessConfig;
use super::BrowserServoTransport;
use super::MAX_FRAME_BYTES;
use super::artifact::ServiceSnapshot;
use super::hex_lower;

const MAX_CHANNEL_WAIT: Duration = Duration::from_secs(10);

struct PendingWrite {
    bytes: Vec<u8>,
    completion: mpsc::SyncSender<Result<(), BrowserServoError>>,
}

pub struct ChildBrowserTransport {
    child: Child,
    writes: Option<mpsc::SyncSender<PendingWrite>>,
    frames: Option<mpsc::Receiver<Result<Vec<u8>, BrowserServoError>>>,
    reader: Option<thread::JoinHandle<()>>,
    writer: Option<thread::JoinHandle<()>>,
    channel_wait: Duration,
    service_snapshot: Option<ServiceSnapshot>,
}

impl fmt::Debug for ChildBrowserTransport {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ChildBrowserTransport")
            .field("pid", &self.child.id())
            .finish_non_exhaustive()
    }
}

impl ChildBrowserTransport {
    pub fn spawn(config: &BrowserServoProcessConfig) -> Result<Self, BrowserServoError> {
        let service_snapshot = config.prepare_service_snapshot()?;
        let child = Command::new(&config.node_path)
            .arg(service_snapshot.path())
            .env_clear()
            .env("HEPTA_BROWSER_WORKER_PATH", &config.worker_path)
            .env(
                "HEPTA_BROWSER_WORKER_SHA256",
                hex_lower(&config.worker_sha256),
            )
            .env("HEPTA_BROWSER_PROFILE_ROOT", &config.profile_root)
            .env("HEPTA_BROWSER_JOURNAL_PATH", &config.journal_path)
            .env("HEPTA_BROWSER_BWRAP_PATH", &config.bwrap_path)
            .env(
                "HEPTA_BROWSER_DRIVER_TIMEOUT_MS",
                config.driver_timeout_ms.to_string(),
            )
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|error| {
                BrowserServoError::Unavailable(format!("failed to spawn Browser service: {error}"))
            })?;
        let mut transport = Self::from_child(child, MAX_CHANNEL_WAIT)?;
        transport.service_snapshot = Some(service_snapshot);
        Ok(transport)
    }

    fn from_child(mut child: Child, channel_wait: Duration) -> Result<Self, BrowserServoError> {
        let Some(mut stdin) = child.stdin.take() else {
            let _ = child.kill();
            let _ = child.wait();
            return Err(BrowserServoError::Unavailable(
                "Browser child stdin was not piped".into(),
            ));
        };
        let Some(stdout) = child.stdout.take() else {
            let _ = child.kill();
            let _ = child.wait();
            return Err(BrowserServoError::Unavailable(
                "Browser child stdout was not piped".into(),
            ));
        };
        let (writes, requests) = mpsc::sync_channel::<PendingWrite>(1);
        let writer = thread::Builder::new()
            .name("hepta-browser-private-writer".to_string())
            .spawn(move || {
                while let Ok(request) = requests.recv() {
                    let result = stdin
                        .write_all(&request.bytes)
                        .and_then(|()| stdin.flush())
                        .map_err(|error| {
                            BrowserServoError::Indeterminate(format!(
                                "Browser private-channel write failed: {error}"
                            ))
                        });
                    let terminal = result.is_err();
                    if request.completion.send(result).is_err() || terminal {
                        break;
                    }
                }
            })
            .map_err(|error| {
                let _ = child.kill();
                let _ = child.wait();
                BrowserServoError::Unavailable(format!(
                    "failed to start Browser private-channel writer: {error}"
                ))
            })?;
        let (sender, frames) = mpsc::sync_channel(1);
        let reader = thread::Builder::new()
            .name("hepta-browser-private-reader".to_string())
            .spawn(move || {
                let mut stdout = BufReader::new(stdout);
                loop {
                    let result = read_child_frame(&mut stdout);
                    let terminal = result.is_err();
                    if sender.send(result).is_err() || terminal {
                        break;
                    }
                }
            })
            .map_err(|error| {
                let _ = child.kill();
                let _ = child.wait();
                BrowserServoError::Unavailable(format!(
                    "failed to start Browser private-channel reader: {error}"
                ))
            })?;
        Ok(Self {
            child,
            writes: Some(writes),
            frames: Some(frames),
            reader: Some(reader),
            writer: Some(writer),
            channel_wait,
            service_snapshot: None,
        })
    }
}

impl BrowserServoTransport for ChildBrowserTransport {
    fn write_frame(&mut self, bytes: &[u8]) -> Result<(), BrowserServoError> {
        if bytes.len() < 5 || bytes.len() > MAX_FRAME_BYTES + 4 {
            return Err(BrowserServoError::Protocol(
                "Browser output frame bytes are outside bounds".into(),
            ));
        }
        let writes = self.writes.as_ref().ok_or_else(|| {
            BrowserServoError::Unavailable("Browser private channel is closed".into())
        })?;
        let (completion, completed) = mpsc::sync_channel(1);
        let queued = writes.try_send(PendingWrite {
            bytes: bytes.to_vec(),
            completion,
        });
        let result = match queued {
            Ok(()) => match completed.recv_timeout(self.channel_wait) {
                Ok(result) => result,
                Err(_) => Err(BrowserServoError::Indeterminate(
                    "Browser private-channel write deadline exceeded or writer disconnected".into(),
                )),
            },
            Err(_) => Err(BrowserServoError::Indeterminate(
                "Browser private-channel writer is busy or disconnected".into(),
            )),
        };
        if result.is_err() {
            self.close();
        }
        result
    }

    fn read_frame(&mut self) -> Result<Vec<u8>, BrowserServoError> {
        let frames = self.frames.as_ref().ok_or_else(|| {
            BrowserServoError::Unavailable("Browser private channel is closed".into())
        })?;
        let result = match frames.recv_timeout(self.channel_wait) {
            Ok(result) => result,
            Err(mpsc::RecvTimeoutError::Timeout) => Err(BrowserServoError::Indeterminate(
                "Browser private-channel response deadline exceeded".into(),
            )),
            Err(mpsc::RecvTimeoutError::Disconnected) => Err(BrowserServoError::Indeterminate(
                "Browser private-channel reader disconnected".into(),
            )),
        };
        if result.is_err() {
            self.close();
        }
        result
    }

    fn close(&mut self) {
        // Drop the receiving side before cleanup: a full queue otherwise leaves
        // the reader blocked in send while Drop waits for that same thread.
        self.frames.take();
        self.writes.take();
        let _ = self.child.kill();
        let _ = self.child.wait();
        // A descendant may retain an inherited pipe after the child exits.
        // Such a handle must not turn shutdown into an unbounded thread join.
        for handle in [&mut self.reader, &mut self.writer] {
            if let Some(thread) = handle.take()
                && thread.is_finished()
            {
                let _ = thread.join();
            }
        }
    }
}

impl Drop for ChildBrowserTransport {
    fn drop(&mut self) {
        self.close();
    }
}

fn read_child_frame(stdout: &mut BufReader<ChildStdout>) -> Result<Vec<u8>, BrowserServoError> {
    let mut prefix = [0u8; 4];
    stdout.read_exact(&mut prefix).map_err(|error| {
        BrowserServoError::Indeterminate(format!(
            "Browser private-channel prefix read failed: {error}"
        ))
    })?;
    let length = u32::from_be_bytes(prefix) as usize;
    if length == 0 || length > MAX_FRAME_BYTES {
        return Err(BrowserServoError::Protocol(
            "Browser child announced an invalid frame length".into(),
        ));
    }
    let mut body = vec![0u8; length];
    stdout.read_exact(&mut body).map_err(|error| {
        BrowserServoError::Indeterminate(format!(
            "Browser private-channel body read failed: {error}"
        ))
    })?;
    let mut frame = Vec::with_capacity(length + 4);
    frame.extend_from_slice(&prefix);
    frame.extend_from_slice(&body);
    Ok(frame)
}

#[cfg(all(test, unix))]
#[path = "browser_servo_transport_tests.rs"]
mod tests;
