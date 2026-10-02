//! Unprivileged OS adapter isolation, not a capability or final-use authority.
//!
//! The parent admits the effect before launching this same-executable helper.
//! Anonymous inherited pipes bind readiness and the single bounded notification.
//! A same-principal caller can invoke this OS facility directly, as they could
//! invoke the former system notification commands; no authority receipt is issued.
#[cfg(test)]
use std::io::BufRead as _;
use std::io::Read as _;
use std::io::Write as _;
use std::process::Command;
use std::process::ExitStatus;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::time::Instant;

use serde::Deserialize;
use serde::Serialize;

use crate::error::ShellError;
use crate::model::PlatformPayload;
#[cfg(any(target_os = "macos", target_os = "windows"))]
use crate::model::sha256_hex;
use crate::model::validate_digest;

#[cfg(target_os = "macos")]
#[path = "platform_notify_macos.rs"]
mod native;
#[cfg(target_os = "windows")]
#[path = "platform_notify_windows.rs"]
mod native;

const READY_SCHEMA: &str = "hepta.native-notification-ready.v1";
const REQUEST_SCHEMA: &str = "hepta.native-notification.v1";
const MAX_REQUEST_BYTES: u64 = 32 * 1024;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Ready {
    schema: String,
    binary_digest: String,
    nonce: String,
}

#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct NotificationRequest {
    schema: String,
    nonce: String,
    title: String,
    body: String,
}

impl NotificationRequest {
    fn validate(&self, nonce: &str) -> Result<(), ShellError> {
        if self.schema != REQUEST_SCHEMA || self.nonce != nonce {
            return Err(ShellError::Security(
                "notification helper protocol mismatch".into(),
            ));
        }
        PlatformPayload::Notify {
            title: self.title.clone(),
            body: self.body.clone(),
        }
        .validate()
    }
}

#[cfg(target_os = "macos")]
pub(super) fn macos_supported() -> bool {
    native::supported()
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
pub(super) fn run() -> Result<(), ShellError> {
    let mut random = [0; 32];
    getrandom::fill(&mut random)
        .map_err(|error| ShellError::Platform(format!("notification helper entropy: {error}")))?;
    let nonce = sha256_hex(random);
    let ready = Ready {
        schema: READY_SCHEMA.into(),
        binary_digest: crate::update_storage::running_binary_digest()?,
        nonce,
    };
    serde_json::to_writer(std::io::stdout().lock(), &ready)?;
    std::io::stdout().write_all(b"\n")?;
    std::io::stdout().flush()?;
    let mut bytes = Vec::new();
    std::io::stdin()
        .take(MAX_REQUEST_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_REQUEST_BYTES {
        return Err(ShellError::InvalidInput(
            "notification helper input exceeds its bound".into(),
        ));
    }
    let request: NotificationRequest = serde_json::from_slice(&bytes)?;
    request.validate(&ready.nonce)?;
    native::send(&request.title, &request.body, &request.nonce)
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
pub(super) fn launch(
    title: &str,
    body: &str,
    active: &Arc<AtomicUsize>,
) -> Result<ExitStatus, ShellError> {
    let executable = std::env::current_exe()?;
    let expected_digest = crate::update_storage::running_binary_digest()?;
    if crate::update_storage::digest_file(&executable)? != expected_digest {
        return Err(ShellError::Security(
            "notification helper executable changed".into(),
        ));
    }
    let mut command = Command::new(executable);
    #[cfg(target_os = "macos")]
    super::restrict_desktop_environment(&mut command);
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt as _;
        super::restrict_windows_environment(&mut command);
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    command
        .arg("--native-notification-helper")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    run_process(
        command,
        &expected_digest,
        title,
        body,
        active,
        super::NOTIFICATION_TIMEOUT,
    )
}

fn run_process(
    mut command: Command,
    expected_digest: &str,
    title: &str,
    body: &str,
    active: &Arc<AtomicUsize>,
    maximum: std::time::Duration,
) -> Result<ExitStatus, ShellError> {
    let _slot = super::LauncherSlot::acquire(active)?;
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    let mut child = command.spawn()?;
    let deadline = Instant::now() + maximum;
    let result = (|| {
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| ShellError::Platform("notification input pipe unavailable".into()))?;
        let mut stdout = child.stdout.take().ok_or_else(|| {
            ShellError::Platform("notification readiness pipe unavailable".into())
        })?;
        crate::native_pipe::prepare_reader(&stdout)?;
        crate::native_pipe::prepare_writer(&stdin)?;
        let mut ready = Vec::new();
        let mut request = None;
        let mut written = 0;
        let mut stdin = Some(stdin);
        loop {
            if Instant::now() >= deadline {
                return Err(ShellError::Platform("notification helper observation deadline exceeded; effect remains indeterminate".into()));
            }
            if request.is_none() {
                let mut block = [0_u8; 1025];
                match crate::native_pipe::read_available(&mut stdout, &mut block) {
                    Ok(0) => {
                        return Err(ShellError::Platform(
                            "notification helper closed before readiness".into(),
                        ));
                    }
                    Ok(length) => {
                        ready.extend_from_slice(&block[..length]);
                        if ready.len() > 1024 {
                            return Err(ShellError::Security(
                                "notification readiness exceeds its bound".into(),
                            ));
                        }
                        if ready.contains(&b'\n') {
                            request = Some(request_bytes(&ready, expected_digest, title, body)?);
                        }
                    }
                    Err(error) if crate::native_pipe::would_block(&error) => {}
                    Err(error) => return Err(error.into()),
                }
            }
            if let Some(request) = &request
                && let Some(writer) = &mut stdin
            {
                match writer.write(&request[written..]) {
                    Ok(length) => written += length,
                    Err(error) if crate::native_pipe::would_block(&error) => {}
                    Err(error) => return Err(error.into()),
                }
                if written == request.len() {
                    stdin = None;
                    break;
                }
            }
            if child.try_wait()?.is_some() {
                return Err(ShellError::Platform(
                    "notification helper exited before handoff".into(),
                ));
            }
            std::thread::sleep(super::LAUNCHER_POLL_INTERVAL);
        }
        drop(stdin);
        drop(stdout);
        Ok(())
    })();
    // The closure owned and closed both pipe endpoints, even on setup errors.
    let result = result.and_then(|()| loop {
        if let Some(status) = child.try_wait()? {
            break Ok(status);
        }
        if Instant::now() >= deadline {
            break Err(ShellError::Platform("notification helper observation deadline exceeded; effect remains indeterminate".into()));
        }
        std::thread::sleep(super::LAUNCHER_POLL_INTERVAL);
    });
    // Direct child ownership is retained through reaping. Prelaunch image reads
    // and OS scheduling/reaping are outside the cooperative pipe-I/O deadline.
    let _ = child.kill();
    let _ = child.wait();
    result
}

fn request_bytes(
    bytes: &[u8],
    expected_digest: &str,
    title: &str,
    body: &str,
) -> Result<Vec<u8>, ShellError> {
    if bytes.len() > 1024 || bytes.last() != Some(&b'\n') {
        return Err(ShellError::Security(
            "notification readiness is unbounded or incomplete".into(),
        ));
    }
    let ready: Ready = serde_json::from_slice(bytes)?;
    if ready.schema != READY_SCHEMA || ready.binary_digest != expected_digest {
        return Err(ShellError::Security(
            "notification helper binary identity mismatch".into(),
        ));
    }
    validate_digest(&ready.nonce, "notification helper nonce")?;
    let request = NotificationRequest {
        schema: REQUEST_SCHEMA.into(),
        nonce: ready.nonce,
        title: title.into(),
        body: body.into(),
    };
    request.validate(&request.nonce)?;
    let bytes = serde_json::to_vec(&request)?;
    if bytes.len() as u64 > MAX_REQUEST_BYTES {
        return Err(ShellError::InvalidInput(
            "notification helper request exceeds its bound".into(),
        ));
    }
    Ok(bytes)
}

#[cfg(test)]
fn exchange_request(
    mut stdin: impl std::io::Write,
    stdout: impl std::io::Read,
    expected_digest: String,
    title: String,
    body: String,
) -> Result<(), ShellError> {
    let mut reader = std::io::BufReader::new(stdout).take(1025);
    let mut bytes = Vec::new();
    reader.read_until(b'\n', &mut bytes)?;
    let bytes = request_bytes(&bytes, &expected_digest, &title, &body)?;
    stdin.write_all(&bytes)?;
    Ok(())
}

#[cfg(test)]
#[path = "platform_notification_helper_tests.rs"]
mod tests;
