use crate::sha256_hex;
use crate::types::OperationKey;
use crate::types::PlatformAction;
use crate::types::PlatformPayload;
use std::path::Path;
use std::process::Command;
use thiserror::Error;

const MAX_TEXT_BYTES: usize = 1024 * 1024;
const MAX_NOTIFICATION_TITLE_BYTES: usize = 256;
const MAX_NOTIFICATION_BODY_BYTES: usize = 4096;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObservationStatus {
    Succeeded,
    Failed,
}

#[derive(Clone, Debug)]
pub struct PlatformObservation {
    pub terminal_observed: bool,
    pub status: Option<ObservationStatus>,
    pub outcome_digest: Option<String>,
}

impl PlatformObservation {
    pub fn succeeded(detail: &str) -> Self {
        Self {
            terminal_observed: true,
            status: Some(ObservationStatus::Succeeded),
            outcome_digest: Some(sha256_hex(format!(
                "hepta.native.platform.outcome.v1\0succeeded\0{detail}"
            ))),
        }
    }

    pub fn failed(detail: &str) -> Self {
        Self {
            terminal_observed: true,
            status: Some(ObservationStatus::Failed),
            outcome_digest: Some(sha256_hex(format!(
                "hepta.native.platform.outcome.v1\0failed\0{detail}"
            ))),
        }
    }

    pub fn indeterminate() -> Self {
        Self {
            terminal_observed: false,
            status: None,
            outcome_digest: None,
        }
    }
}

#[derive(Debug, Error)]
pub enum PlatformError {
    #[error("platform payload does not match the requested action")]
    Payload,
    #[error("platform payload exceeds its bound")]
    Bounds,
    #[error("platform path must be absolute")]
    Path,
    #[error("platform adapter failed: {0}")]
    Adapter(String),
}

pub trait PlatformAdapter: Send {
    fn invoke(
        &mut self,
        key: &OperationKey,
        action: PlatformAction,
        payload: &PlatformPayload,
    ) -> Result<PlatformObservation, PlatformError>;

    fn reconcile(
        &mut self,
        _key: &OperationKey,
        _action: PlatformAction,
        _payload: &PlatformPayload,
    ) -> Result<Option<PlatformObservation>, PlatformError> {
        Ok(None)
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SystemPlatformAdapter;

impl SystemPlatformAdapter {
    pub fn new() -> Self {
        Self
    }
}

impl PlatformAdapter for SystemPlatformAdapter {
    fn invoke(
        &mut self,
        _key: &OperationKey,
        action: PlatformAction,
        payload: &PlatformPayload,
    ) -> Result<PlatformObservation, PlatformError> {
        validate_payload(&action, payload)?;
        match (action, payload) {
            (PlatformAction::CopyText, PlatformPayload::Text { text }) => {
                let mut clipboard = arboard::Clipboard::new()
                    .map_err(|error| PlatformError::Adapter(error.to_string()))?;
                clipboard
                    .set_text(text.clone())
                    .map_err(|error| PlatformError::Adapter(error.to_string()))?;
                Ok(PlatformObservation::succeeded("clipboard-write-observed"))
            }
            (PlatformAction::Notify, PlatformPayload::Notification { title, body }) => {
                let shown = notify_rust::Notification::new()
                    .summary(title)
                    .body(body)
                    .appname("Hepta Native")
                    .show();
                match shown {
                    Ok(_) => Ok(PlatformObservation::indeterminate()),
                    Err(error) => Ok(PlatformObservation::failed(&format!(
                        "notification:{error}"
                    ))),
                }
            }
            (PlatformAction::OpenPath, PlatformPayload::Path { path }) => launch_path(path, false),
            (PlatformAction::RevealPath, PlatformPayload::Path { path }) => launch_path(path, true),
            _ => Err(PlatformError::Payload),
        }
    }
}

pub fn validate_payload(
    action: &PlatformAction,
    payload: &PlatformPayload,
) -> Result<(), PlatformError> {
    match (action, payload) {
        (PlatformAction::OpenPath | PlatformAction::RevealPath, PlatformPayload::Path { path }) => {
            if !path.is_absolute() {
                return Err(PlatformError::Path);
            }
        }
        (PlatformAction::CopyText, PlatformPayload::Text { text }) => {
            if text.len() > MAX_TEXT_BYTES {
                return Err(PlatformError::Bounds);
            }
        }
        (PlatformAction::Notify, PlatformPayload::Notification { title, body }) => {
            if title.is_empty()
                || title.len() > MAX_NOTIFICATION_TITLE_BYTES
                || body.len() > MAX_NOTIFICATION_BODY_BYTES
            {
                return Err(PlatformError::Bounds);
            }
        }
        _ => return Err(PlatformError::Payload),
    }
    Ok(())
}

fn launch_path(path: &Path, reveal: bool) -> Result<PlatformObservation, PlatformError> {
    #[cfg(target_os = "macos")]
    let mut command = {
        let mut command = Command::new("/usr/bin/open");
        if reveal {
            command.arg("-R");
        }
        command.arg(path);
        command
    };

    #[cfg(target_os = "windows")]
    let mut command = {
        let executable = std::env::var_os("SystemRoot")
            .map(std::path::PathBuf::from)
            .map(|root| root.join("explorer.exe"))
            .filter(|path| path.is_file())
            .unwrap_or_else(|| std::path::PathBuf::from(r"C:\Windows\explorer.exe"));
        let mut command = Command::new(executable);
        if reveal {
            command.arg(format!("/select,{}", path.display()));
        } else {
            command.arg(path);
        }
        command
    };

    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = {
        if reveal {
            if let Some(parent) = path.parent() {
                let mut command = Command::new("/usr/bin/xdg-open");
                command.arg(parent);
                command
            } else {
                return Err(PlatformError::Path);
            }
        } else {
            let mut command = Command::new("/usr/bin/xdg-open");
            command.arg(path);
            command
        }
    };

    let status = command
        .status()
        .map_err(|error| PlatformError::Adapter(error.to_string()))?;
    if status.success() {
        // Process-launch success is not proof that the desktop application
        // presented the resource. Keep it open for reconciliation.
        Ok(PlatformObservation::indeterminate())
    } else {
        Ok(PlatformObservation::failed(&format!(
            "launcher-exit:{}",
            status.code().unwrap_or(-1)
        )))
    }
}
