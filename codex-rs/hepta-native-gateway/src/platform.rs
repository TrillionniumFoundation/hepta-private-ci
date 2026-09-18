use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::path::Path;
use std::process::Command;
use std::sync::Mutex;
use std::sync::PoisonError;

use arboard::Clipboard;
use codex_hepta_types::Digest32;

use crate::shell::SessionOperationKey;

const MAX_TEXT_BYTES: usize = 64 * 1024;
const MAX_PATH_BYTES: usize = 16 * 1024;
const MAX_RECENT_OBSERVATIONS: usize = 1_024;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PlatformAction {
    OpenPath,
    RevealPath,
    CopyText,
    Notify,
}

impl PlatformAction {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::OpenPath => "open_path",
            Self::RevealPath => "reveal_path",
            Self::CopyText => "copy_text",
            Self::Notify => "notify",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "open_path" => Some(Self::OpenPath),
            "reveal_path" => Some(Self::RevealPath),
            "copy_text" => Some(Self::CopyText),
            "notify" => Some(Self::Notify),
            _ => None,
        }
    }

    pub fn scope_digest(self) -> Digest32 {
        let mut bytes = b"hepta.ui.native.platform-scope.v1\0".to_vec();
        bytes.extend_from_slice(self.as_str().as_bytes());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlatformPayload {
    OpenPath { path: String },
    RevealPath { path: String },
    CopyText { text: String },
    Notify { title: String, body: String },
}

impl PlatformPayload {
    pub const fn action(&self) -> PlatformAction {
        match self {
            Self::OpenPath { .. } => PlatformAction::OpenPath,
            Self::RevealPath { .. } => PlatformAction::RevealPath,
            Self::CopyText { .. } => PlatformAction::CopyText,
            Self::Notify { .. } => PlatformAction::Notify,
        }
    }

    pub fn validate(&self) -> Result<(), PlatformError> {
        match self {
            Self::OpenPath { path } | Self::RevealPath { path } => {
                validate_string(path, MAX_PATH_BYTES, "path")?;
                if !Path::new(path).exists() {
                    return Err(PlatformError::MissingPath);
                }
            }
            Self::CopyText { text } => validate_string(text, MAX_TEXT_BYTES, "text")?,
            Self::Notify { title, body } => {
                validate_string(title, 512, "notification title")?;
                validate_string(body, 8 * 1024, "notification body")?;
            }
        }
        Ok(())
    }

    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.ui.native.platform-payload.v1\0".to_vec();
        bytes.extend_from_slice(self.action().as_str().as_bytes());
        match self {
            Self::OpenPath { path } | Self::RevealPath { path } => push_text(&mut bytes, path),
            Self::CopyText { text } => push_text(&mut bytes, text),
            Self::Notify { title, body } => {
                push_text(&mut bytes, title);
                push_text(&mut bytes, body);
            }
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PermissionDecision {
    Allowed,
    Denied { outcome_digest: Digest32 },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlatformObservation {
    Succeeded { outcome_digest: Digest32 },
    Failed { outcome_digest: Digest32 },
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlatformError {
    InvalidPayload(&'static str),
    MissingPath,
    UnsupportedAction(&'static str),
    Clipboard(String),
    Command(String),
}

impl fmt::Display for PlatformError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlatformError {}

pub trait PlatformAdapter {
    type Error: StdError;

    fn permission(
        &self,
        action: PlatformAction,
        payload: &PlatformPayload,
    ) -> Result<PermissionDecision, Self::Error>;

    fn invoke(
        &self,
        key: &SessionOperationKey,
        payload: &PlatformPayload,
        payload_digest: Digest32,
    ) -> Result<PlatformObservation, Self::Error>;

    fn reconcile(
        &self,
        key: &SessionOperationKey,
        action: PlatformAction,
        payload_digest: Digest32,
    ) -> Result<PlatformObservation, Self::Error>;
}

#[derive(Default)]
pub struct SystemPlatformAdapter {
    recent: Mutex<BTreeMap<SessionOperationKey, PlatformObservation>>,
    clipboard: Mutex<Option<Clipboard>>,
}

impl SystemPlatformAdapter {
    pub fn new() -> Self {
        Self::default()
    }

    fn remember(&self, key: SessionOperationKey, observation: PlatformObservation) {
        let mut recent = self.recent.lock().unwrap_or_else(PoisonError::into_inner);
        if recent.len() >= MAX_RECENT_OBSERVATIONS
            && let Some(first) = recent.keys().next().cloned()
        {
            recent.remove(&first);
        }
        recent.insert(key, observation);
    }
}

impl PlatformAdapter for SystemPlatformAdapter {
    type Error = PlatformError;

    fn permission(
        &self,
        action: PlatformAction,
        payload: &PlatformPayload,
    ) -> Result<PermissionDecision, Self::Error> {
        if action != payload.action() {
            return Err(PlatformError::InvalidPayload("action mismatch"));
        }
        match payload.validate() {
            Ok(()) => Ok(PermissionDecision::Allowed),
            Err(PlatformError::MissingPath) => Ok(PermissionDecision::Denied {
                outcome_digest: outcome_digest(action, "missing-path"),
            }),
            Err(error) => Err(error),
        }
    }

    fn invoke(
        &self,
        key: &SessionOperationKey,
        payload: &PlatformPayload,
        payload_digest: Digest32,
    ) -> Result<PlatformObservation, Self::Error> {
        if payload.digest() != payload_digest {
            return Err(PlatformError::InvalidPayload("payload digest mismatch"));
        }
        payload.validate()?;
        let action = payload.action();
        let observation = match payload {
            PlatformPayload::CopyText { text } => {
                let mut clipboard = Clipboard::new()
                    .map_err(|error| PlatformError::Clipboard(error.to_string()))?;
                clipboard
                    .set_text(text.clone())
                    .map_err(|error| PlatformError::Clipboard(error.to_string()))?;
                *self
                    .clipboard
                    .lock()
                    .unwrap_or_else(PoisonError::into_inner) = Some(clipboard);
                PlatformObservation::Succeeded {
                    outcome_digest: outcome_digest(action, "clipboard-write-complete"),
                }
            }
            PlatformPayload::OpenPath { path } => command_observation(action, open_command(path)?)?,
            PlatformPayload::RevealPath { path } => {
                command_observation(action, reveal_command(path)?)?
            }
            PlatformPayload::Notify { title, body } => {
                command_observation(action, notify_command(title, body)?)?
            }
        };
        self.remember(key.clone(), observation.clone());
        Ok(observation)
    }

    fn reconcile(
        &self,
        key: &SessionOperationKey,
        _action: PlatformAction,
        _payload_digest: Digest32,
    ) -> Result<PlatformObservation, Self::Error> {
        let recent = self.recent.lock().unwrap_or_else(PoisonError::into_inner);
        Ok(recent
            .get(key)
            .cloned()
            .unwrap_or(PlatformObservation::Indeterminate))
    }
}

fn validate_string(
    value: &str,
    maximum_bytes: usize,
    name: &'static str,
) -> Result<(), PlatformError> {
    if value.is_empty() || value.len() > maximum_bytes || value.contains('\0') {
        return Err(PlatformError::InvalidPayload(name));
    }
    Ok(())
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(
        &u32::try_from(value.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
}

fn outcome_digest(action: PlatformAction, status: &str) -> Digest32 {
    let mut bytes = b"hepta.ui.native.platform-outcome.v1\0".to_vec();
    bytes.extend_from_slice(action.as_str().as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(status.as_bytes());
    Digest32::of_bytes(&bytes)
}

fn command_observation(
    action: PlatformAction,
    mut command: Command,
) -> Result<PlatformObservation, PlatformError> {
    let status = command
        .status()
        .map_err(|error| PlatformError::Command(error.to_string()))?;
    if status.success() {
        // Process-launch acknowledgement is not proof that a desktop opened a
        // path or displayed a notification. Keep the operation indeterminate
        // until a platform-specific observer can prove the external outcome.
        Ok(PlatformObservation::Indeterminate)
    } else {
        Ok(PlatformObservation::Failed {
            outcome_digest: outcome_digest(action, "command-exited-failure"),
        })
    }
}

#[cfg(target_os = "macos")]
fn open_command(path: &str) -> Result<Command, PlatformError> {
    let mut command = Command::new("open");
    command.arg(path);
    Ok(command)
}

#[cfg(target_os = "windows")]
fn open_command(path: &str) -> Result<Command, PlatformError> {
    let mut command = Command::new("explorer.exe");
    command.arg(path);
    Ok(command)
}

#[cfg(all(unix, not(target_os = "macos")))]
fn open_command(path: &str) -> Result<Command, PlatformError> {
    let mut command = Command::new("xdg-open");
    command.arg(path);
    Ok(command)
}

#[cfg(not(any(unix, target_os = "windows")))]
fn open_command(_path: &str) -> Result<Command, PlatformError> {
    Err(PlatformError::UnsupportedAction("open_path"))
}

#[cfg(target_os = "macos")]
fn reveal_command(path: &str) -> Result<Command, PlatformError> {
    let mut command = Command::new("open");
    command.arg("-R").arg(path);
    Ok(command)
}

#[cfg(target_os = "windows")]
fn reveal_command(path: &str) -> Result<Command, PlatformError> {
    let mut command = Command::new("explorer.exe");
    command.arg(format!("/select,{path}"));
    Ok(command)
}

#[cfg(all(unix, not(target_os = "macos")))]
fn reveal_command(path: &str) -> Result<Command, PlatformError> {
    let parent = Path::new(path).parent().ok_or(PlatformError::MissingPath)?;
    let mut command = Command::new("xdg-open");
    command.arg(parent);
    Ok(command)
}

#[cfg(not(any(unix, target_os = "windows")))]
fn reveal_command(_path: &str) -> Result<Command, PlatformError> {
    Err(PlatformError::UnsupportedAction("reveal_path"))
}

#[cfg(target_os = "macos")]
fn notify_command(title: &str, body: &str) -> Result<Command, PlatformError> {
    let mut command = Command::new("osascript");
    command
        .arg("-e")
        .arg("on run argv")
        .arg("-e")
        .arg("display notification (item 2 of argv) with title (item 1 of argv)")
        .arg("-e")
        .arg("end run")
        .arg("--")
        .arg(title)
        .arg(body);
    Ok(command)
}

#[cfg(target_os = "windows")]
fn notify_command(title: &str, body: &str) -> Result<Command, PlatformError> {
    const SCRIPT: &str = r#"
Add-Type -AssemblyName System.Windows.Forms;
Add-Type -AssemblyName System.Drawing;
$n = New-Object System.Windows.Forms.NotifyIcon;
$n.Icon = [System.Drawing.SystemIcons]::Information;
$n.Visible = $true;
$n.BalloonTipTitle = $env:HEPTA_NOTIFY_TITLE;
$n.BalloonTipText = $env:HEPTA_NOTIFY_BODY;
$n.ShowBalloonTip(5000);
Start-Sleep -Milliseconds 750;
$n.Dispose();
"#;
    let mut command = Command::new("powershell.exe");
    command
        .arg("-NoLogo")
        .arg("-NoProfile")
        .arg("-NonInteractive")
        .arg("-Command")
        .arg(SCRIPT)
        .env("HEPTA_NOTIFY_TITLE", title)
        .env("HEPTA_NOTIFY_BODY", body);
    Ok(command)
}

#[cfg(all(unix, not(target_os = "macos")))]
fn notify_command(title: &str, body: &str) -> Result<Command, PlatformError> {
    let mut command = Command::new("notify-send");
    command.arg(title).arg(body);
    Ok(command)
}

#[cfg(not(any(unix, target_os = "windows")))]
fn notify_command(_title: &str, _body: &str) -> Result<Command, PlatformError> {
    Err(PlatformError::UnsupportedAction("notify"))
}
