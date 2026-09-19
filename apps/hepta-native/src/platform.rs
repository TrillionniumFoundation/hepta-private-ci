use std::path::Path;
use std::path::PathBuf;
use std::process::Command;

use arboard::Clipboard;

use crate::error::ShellError;
use crate::journal::OperationRecord;
use crate::model::OperationKey;
use crate::model::PlatformAction;
use crate::model::PlatformObservation;
use crate::model::PlatformPayload;
use crate::model::TerminalStatus;
use crate::model::sha256_hex;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PermissionDecision {
    pub allowed: bool,
    pub outcome_digest: String,
}

pub trait PlatformAdapter: Send {
    fn permission(&self, payload: &PlatformPayload) -> Result<PermissionDecision, ShellError>;

    fn invoke(
        &mut self,
        key: &OperationKey,
        payload: &PlatformPayload,
    ) -> Result<PlatformObservation, ShellError>;

    fn reconcile(&mut self, record: &OperationRecord) -> Result<PlatformObservation, ShellError>;
}

#[derive(Debug, Clone)]
pub struct PlatformPolicy {
    allowed_path_roots: Vec<PathBuf>,
    allow_clipboard: bool,
    allow_notifications: bool,
}

impl PlatformPolicy {
    pub fn new(
        allowed_path_roots: Vec<PathBuf>,
        allow_clipboard: bool,
        allow_notifications: bool,
    ) -> Result<Self, ShellError> {
        let mut canonical_roots = Vec::with_capacity(allowed_path_roots.len());
        for root in allowed_path_roots {
            if !root.is_absolute() {
                return Err(ShellError::InvalidInput(
                    "platform policy roots must be absolute".to_owned(),
                ));
            }
            let canonical = std::fs::canonicalize(&root).map_err(|error| {
                ShellError::InvalidInput(format!(
                    "platform policy root {} cannot be canonicalized: {error}",
                    root.display()
                ))
            })?;
            canonical_roots.push(canonical);
        }
        Ok(Self {
            allowed_path_roots: canonical_roots,
            allow_clipboard,
            allow_notifications,
        })
    }

    fn path_allowed(&self, path: &Path) -> bool {
        let Ok(canonical) = std::fs::canonicalize(path) else {
            return false;
        };
        self.allowed_path_roots
            .iter()
            .any(|root| canonical.starts_with(root))
    }
}

#[derive(Debug, Clone)]
pub struct SystemPlatformAdapter {
    policy: PlatformPolicy,
}

impl SystemPlatformAdapter {
    pub fn new(policy: PlatformPolicy) -> Self {
        Self { policy }
    }

    fn launcher_observation(
        &self,
        action: PlatformAction,
        status: std::process::ExitStatus,
    ) -> PlatformObservation {
        if status.success() {
            PlatformObservation::indeterminate()
        } else {
            PlatformObservation {
                terminal_status: Some(TerminalStatus::Failed),
                outcome_digest: Some(sha256_hex(format!(
                    "hepta.platform-launch.v1:{action}:exit:{:?}",
                    status.code()
                ))),
            }
        }
    }
}

impl PlatformAdapter for SystemPlatformAdapter {
    fn permission(&self, payload: &PlatformPayload) -> Result<PermissionDecision, ShellError> {
        payload.validate()?;
        let (allowed, reason) = match payload {
            PlatformPayload::OpenPath { path } | PlatformPayload::RevealPath { path } => {
                (self.policy.path_allowed(path), "path_policy")
            }
            PlatformPayload::CopyText { .. } => (self.policy.allow_clipboard, "clipboard_policy"),
            PlatformPayload::Notify { .. } => {
                (self.policy.allow_notifications, "notification_policy")
            }
        };
        Ok(PermissionDecision {
            allowed,
            outcome_digest: sha256_hex(format!(
                "hepta.platform-permission.v1:{}:{reason}:{allowed}",
                payload.action()
            )),
        })
    }

    fn invoke(
        &mut self,
        _key: &OperationKey,
        payload: &PlatformPayload,
    ) -> Result<PlatformObservation, ShellError> {
        match payload {
            PlatformPayload::CopyText { text } => {
                let mut clipboard = Clipboard::new()
                    .map_err(|error| ShellError::Platform(format!("open clipboard: {error}")))?;
                clipboard
                    .set_text(text.clone())
                    .map_err(|error| ShellError::Platform(format!("write clipboard: {error}")))?;
                match clipboard.get_text() {
                    Ok(observed) if observed == *text => Ok(PlatformObservation {
                        terminal_status: Some(TerminalStatus::Succeeded),
                        outcome_digest: Some(sha256_hex(format!(
                            "hepta.clipboard-observation.v1:{}",
                            sha256_hex(text.as_bytes())
                        ))),
                    }),
                    Ok(_) | Err(_) => Ok(PlatformObservation::indeterminate()),
                }
            }
            PlatformPayload::OpenPath { path } => {
                let status = launch_open(path)?;
                Ok(self.launcher_observation(PlatformAction::OpenPath, status))
            }
            PlatformPayload::RevealPath { path } => {
                let status = launch_reveal(path)?;
                Ok(self.launcher_observation(PlatformAction::RevealPath, status))
            }
            PlatformPayload::Notify { title, body } => {
                let status = launch_notification(title, body)?;
                Ok(self.launcher_observation(PlatformAction::Notify, status))
            }
        }
    }

    fn reconcile(&mut self, _record: &OperationRecord) -> Result<PlatformObservation, ShellError> {
        Ok(PlatformObservation::indeterminate())
    }
}

#[cfg(target_os = "macos")]
fn launch_open(path: &Path) -> Result<std::process::ExitStatus, ShellError> {
    Command::new("open")
        .arg(path)
        .status()
        .map_err(|error| ShellError::Platform(format!("open path: {error}")))
}

#[cfg(target_os = "windows")]
fn launch_open(path: &Path) -> Result<std::process::ExitStatus, ShellError> {
    Command::new("explorer.exe")
        .arg(path)
        .status()
        .map_err(|error| ShellError::Platform(format!("open path: {error}")))
}

#[cfg(all(unix, not(target_os = "macos")))]
fn launch_open(path: &Path) -> Result<std::process::ExitStatus, ShellError> {
    Command::new("xdg-open")
        .arg(path)
        .status()
        .map_err(|error| ShellError::Platform(format!("open path: {error}")))
}

#[cfg(target_os = "macos")]
fn launch_reveal(path: &Path) -> Result<std::process::ExitStatus, ShellError> {
    Command::new("open")
        .arg("-R")
        .arg(path)
        .status()
        .map_err(|error| ShellError::Platform(format!("reveal path: {error}")))
}

#[cfg(target_os = "windows")]
fn launch_reveal(path: &Path) -> Result<std::process::ExitStatus, ShellError> {
    Command::new("explorer.exe")
        .arg("/select,")
        .arg(path)
        .status()
        .map_err(|error| ShellError::Platform(format!("reveal path: {error}")))
}

#[cfg(all(unix, not(target_os = "macos")))]
fn launch_reveal(path: &Path) -> Result<std::process::ExitStatus, ShellError> {
    let parent = path.parent().unwrap_or(path);
    Command::new("xdg-open")
        .arg(parent)
        .status()
        .map_err(|error| ShellError::Platform(format!("reveal path: {error}")))
}

#[cfg(target_os = "macos")]
fn launch_notification(title: &str, body: &str) -> Result<std::process::ExitStatus, ShellError> {
    Command::new("osascript")
        .args([
            "-e",
            "on run argv",
            "-e",
            "display notification (item 2 of argv) with title (item 1 of argv)",
            "-e",
            "end run",
            "--",
            title,
            body,
        ])
        .status()
        .map_err(|error| ShellError::Platform(format!("send notification: {error}")))
}

#[cfg(target_os = "windows")]
fn launch_notification(_title: &str, _body: &str) -> Result<std::process::ExitStatus, ShellError> {
    Err(ShellError::Platform(
        "Windows notification requires packaged AppUserModelID/WinRT integration; the native shell refuses to fake it"
            .to_owned(),
    ))
}

#[cfg(all(unix, not(target_os = "macos")))]
fn launch_notification(title: &str, body: &str) -> Result<std::process::ExitStatus, ShellError> {
    Command::new("notify-send")
        .arg("--")
        .arg(title)
        .arg(body)
        .status()
        .map_err(|error| ShellError::Platform(format!("send notification: {error}")))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn local_policy_denies_unapproved_effect_classes() {
        let root = TempDir::new().unwrap();
        let adapter = SystemPlatformAdapter::new(
            LocalPlatformPolicy::new(vec![root.path().to_path_buf()], false, false).unwrap(),
        );

        let clipboard = adapter
            .permission(&PlatformPayload::CopyText {
                text: "denied".to_owned(),
            })
            .unwrap();
        assert!(!clipboard.allowed);

        let notification = adapter
            .permission(&PlatformPayload::Notify {
                title: "denied".to_owned(),
                body: "denied".to_owned(),
            })
            .unwrap();
        assert!(!notification.allowed);
    }

    #[test]
    fn local_path_policy_is_root_scoped_before_os_entry() {
        let root = TempDir::new().unwrap();
        let allowed = root.path().join("allowed.txt");
        std::fs::write(&allowed, b"allowed").unwrap();
        let adapter = SystemPlatformAdapter::new(
            LocalPlatformPolicy::new(vec![root.path().to_path_buf()], false, false).unwrap(),
        );
        assert!(
            adapter
                .permission(&PlatformPayload::OpenPath { path: allowed })
                .unwrap()
                .allowed
        );

        let outside = root.path().parent().unwrap().join("hepta-native-outside.txt");
        std::fs::write(&outside, b"outside").unwrap();
        assert!(
            !adapter
                .permission(&PlatformPayload::RevealPath {
                    path: outside.clone(),
                })
                .unwrap()
                .allowed
        );
        let _ = std::fs::remove_file(outside);
    }
}
