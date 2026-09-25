use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::ExitStatus;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use arboard::Clipboard;

use crate::error::ShellError;
use crate::journal::OperationRecord;
use crate::model::OperationKey;
use crate::model::PlatformAction;
use crate::model::PlatformObservation;
use crate::model::PlatformPayload;
use crate::model::TerminalStatus;
use crate::model::sha256_hex;

const MAX_CONCURRENT_LAUNCHERS: usize = 4;
const LAUNCHER_TIMEOUT: Duration = Duration::from_secs(1);
const LAUNCHER_POLL_INTERVAL: Duration = Duration::from_millis(10);

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

pub struct SystemPlatformAdapter {
    policy: PlatformPolicy,
    active_launchers: Arc<AtomicUsize>,
    // X11/Wayland clipboard ownership lasts only while the handle remains alive.
    clipboard: Option<Clipboard>,
}

impl SystemPlatformAdapter {
    pub fn new(policy: PlatformPolicy) -> Self {
        Self {
            policy,
            active_launchers: Arc::new(AtomicUsize::new(0)),
            clipboard: None,
        }
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
            PlatformPayload::Notify { .. } => (
                self.policy.allow_notifications && notification_supported(),
                "notification_policy",
            ),
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
        let final_permission = self.permission(payload)?;
        if !final_permission.allowed {
            return Err(ShellError::Security(
                "platform policy changed or was revoked before final OS entry".to_owned(),
            ));
        }
        match payload {
            PlatformPayload::CopyText { text } => {
                if self.clipboard.is_none() {
                    self.clipboard = Some(Clipboard::new().map_err(|error| {
                        ShellError::Platform(format!("open clipboard: {error}"))
                    })?);
                }
                let clipboard = self.clipboard.as_mut().ok_or_else(|| {
                    ShellError::Platform("clipboard owner is unavailable".to_owned())
                })?;
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
                let canonical = std::fs::canonicalize(path).map_err(|error| {
                    ShellError::Platform(format!("canonicalize open path before OS entry: {error}"))
                })?;
                if !self.policy.path_allowed(&canonical) {
                    return Err(ShellError::Security(
                        "open path escaped admitted platform roots before OS entry".to_owned(),
                    ));
                }
                let status = launch_open(&canonical, &self.active_launchers)?;
                Ok(self.launcher_observation(PlatformAction::OpenPath, status))
            }
            PlatformPayload::RevealPath { path } => {
                let canonical = std::fs::canonicalize(path).map_err(|error| {
                    ShellError::Platform(format!(
                        "canonicalize reveal path before OS entry: {error}"
                    ))
                })?;
                if !self.policy.path_allowed(&canonical) {
                    return Err(ShellError::Security(
                        "reveal path escaped admitted platform roots before OS entry".to_owned(),
                    ));
                }
                let status = launch_reveal(&canonical, &self.active_launchers)?;
                Ok(self.launcher_observation(PlatformAction::RevealPath, status))
            }
            PlatformPayload::Notify { title, body } => {
                let status = launch_notification(title, body, &self.active_launchers)?;
                Ok(self.launcher_observation(PlatformAction::Notify, status))
            }
        }
    }

    fn reconcile(&mut self, _record: &OperationRecord) -> Result<PlatformObservation, ShellError> {
        Ok(PlatformObservation::indeterminate())
    }
}

#[derive(Debug)]
struct LauncherSlot {
    active: Arc<AtomicUsize>,
}

impl LauncherSlot {
    fn acquire(active: &Arc<AtomicUsize>) -> Result<Self, ShellError> {
        active
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                (current < MAX_CONCURRENT_LAUNCHERS).then_some(current + 1)
            })
            .map_err(|_| {
                ShellError::Platform(format!(
                    "native launcher capacity reached {MAX_CONCURRENT_LAUNCHERS}"
                ))
            })?;
        Ok(Self {
            active: Arc::clone(active),
        })
    }
}

impl Drop for LauncherSlot {
    fn drop(&mut self) {
        self.active.fetch_sub(1, Ordering::AcqRel);
    }
}

fn run_bounded_launcher(
    mut command: Command,
    description: &str,
    active: &Arc<AtomicUsize>,
) -> Result<ExitStatus, ShellError> {
    let _slot = LauncherSlot::acquire(active)?;
    let mut child = command
        .spawn()
        .map_err(|error| ShellError::Platform(format!("{description}: {error}")))?;
    let deadline = Instant::now() + LAUNCHER_TIMEOUT;
    loop {
        if let Some(status) = child
            .try_wait()
            .map_err(|error| ShellError::Platform(format!("observe {description}: {error}")))?
        {
            return Ok(status);
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err(ShellError::Platform(format!(
                "{description} exceeded the bounded {LAUNCHER_TIMEOUT:?} launcher window; effect remains indeterminate"
            )));
        }
        std::thread::sleep(LAUNCHER_POLL_INTERVAL);
    }
}

#[cfg(target_os = "macos")]
fn launch_open(path: &Path, active: &Arc<AtomicUsize>) -> Result<ExitStatus, ShellError> {
    let mut command = Command::new("open");
    command.arg(path);
    run_bounded_launcher(command, "open path", active)
}

#[cfg(target_os = "windows")]
fn launch_open(path: &Path, active: &Arc<AtomicUsize>) -> Result<ExitStatus, ShellError> {
    let mut command = Command::new("explorer.exe");
    command.arg(path);
    run_bounded_launcher(command, "open path", active)
}

#[cfg(all(unix, not(target_os = "macos")))]
fn launch_open(path: &Path, active: &Arc<AtomicUsize>) -> Result<ExitStatus, ShellError> {
    let mut command = Command::new("xdg-open");
    command.arg(path);
    run_bounded_launcher(command, "open path", active)
}

#[cfg(target_os = "macos")]
fn launch_reveal(path: &Path, active: &Arc<AtomicUsize>) -> Result<ExitStatus, ShellError> {
    let mut command = Command::new("open");
    command.arg("-R").arg(path);
    run_bounded_launcher(command, "reveal path", active)
}

#[cfg(target_os = "windows")]
fn launch_reveal(path: &Path, active: &Arc<AtomicUsize>) -> Result<ExitStatus, ShellError> {
    let mut command = Command::new("explorer.exe");
    command.arg(format!("/select,{}", path.display()));
    run_bounded_launcher(command, "reveal path", active)
}

#[cfg(all(unix, not(target_os = "macos")))]
fn launch_reveal(path: &Path, active: &Arc<AtomicUsize>) -> Result<ExitStatus, ShellError> {
    let parent = path.parent().unwrap_or(path);
    let mut command = Command::new("xdg-open");
    command.arg(parent);
    run_bounded_launcher(command, "reveal path", active)
}

fn notification_supported() -> bool {
    !cfg!(target_os = "windows")
}

#[cfg(target_os = "macos")]
fn launch_notification(
    title: &str,
    body: &str,
    active: &Arc<AtomicUsize>,
) -> Result<ExitStatus, ShellError> {
    let mut command = Command::new("osascript");
    command.args([
        "-e",
        "on run argv",
        "-e",
        "display notification (item 2 of argv) with title (item 1 of argv)",
        "-e",
        "end run",
        "--",
        title,
        body,
    ]);
    run_bounded_launcher(command, "send notification", active)
}

#[cfg(target_os = "windows")]
fn launch_notification(
    _title: &str,
    _body: &str,
    _active: &Arc<AtomicUsize>,
) -> Result<ExitStatus, ShellError> {
    Err(ShellError::Platform(
        "Windows notification requires packaged AppUserModelID/WinRT integration; the native shell refuses to fake it"
            .to_owned(),
    ))
}

#[cfg(all(unix, not(target_os = "macos")))]
fn launch_notification(
    title: &str,
    body: &str,
    active: &Arc<AtomicUsize>,
) -> Result<ExitStatus, ShellError> {
    let mut command = Command::new("notify-send");
    command.arg("--").arg(title).arg(body);
    run_bounded_launcher(command, "send notification", active)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn local_policy_denies_unapproved_effect_classes() {
        let root = TempDir::new().unwrap();
        let adapter = SystemPlatformAdapter::new(
            PlatformPolicy::new(vec![root.path().to_path_buf()], false, false).unwrap(),
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
    fn launcher_capacity_is_bounded_and_released() {
        let active = Arc::new(AtomicUsize::new(MAX_CONCURRENT_LAUNCHERS));
        assert!(LauncherSlot::acquire(&active).is_err());
        active.store(0, Ordering::Release);
        {
            let _slot = LauncherSlot::acquire(&active).unwrap();
            assert_eq!(active.load(Ordering::Acquire), 1);
        }
        assert_eq!(active.load(Ordering::Acquire), 0);
    }

    #[test]
    fn local_path_policy_is_root_scoped_before_os_entry() {
        let root = TempDir::new().unwrap();
        let allowed = root.path().join("allowed.txt");
        std::fs::write(&allowed, b"allowed").unwrap();
        let adapter = SystemPlatformAdapter::new(
            PlatformPolicy::new(vec![root.path().to_path_buf()], false, false).unwrap(),
        );
        assert!(
            adapter
                .permission(&PlatformPayload::OpenPath { path: allowed })
                .unwrap()
                .allowed
        );

        let outside = root.path().with_extension("outside");
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
