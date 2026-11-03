#[cfg(target_os = "linux")]
use std::fs::File;
#[cfg(target_os = "linux")]
use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::ExitStatus;
#[cfg(target_os = "linux")]
use std::process::Stdio;
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
const NOTIFICATION_TIMEOUT: Duration = Duration::from_secs(8);
#[cfg(target_os = "linux")]
const PORTAL_PROBE_TIMEOUT: Duration = Duration::from_secs(3);
#[cfg(target_os = "linux")]
const RESOURCE_HANDOFF_TIMEOUT: Duration = Duration::from_secs(40);
const LAUNCHER_POLL_INTERVAL: Duration = Duration::from_millis(10);
const RESOURCE_HANDOFF_ERROR: &str = "path effects require an OS adapter that consumes an already-verified resource capability; mutable path-string launch is disabled";

#[cfg(any(target_os = "windows", test))]
const WINDOWS_AUMID: &str = "Trillionnium.Hepta.Native";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PermissionDecision {
    pub allowed: bool,
    pub outcome_digest: String,
}

pub trait PlatformAdapter: Send {
    /// Adapter-specific, non-authorizing confirmation context. Producing this
    /// context happens before the operation journal enters Prepared. Adapters
    /// must therefore reject effect classes that cannot be handed to the OS
    /// without reopening a mutable name.
    fn confirmation_resource(
        &self,
        _payload: &PlatformPayload,
    ) -> Result<Option<String>, ShellError> {
        Ok(None)
    }

    fn invoke_confirmed(
        &mut self,
        key: &OperationKey,
        payload: &PlatformPayload,
        expected_resource: &Option<String>,
    ) -> Result<PlatformObservation, ShellError> {
        if self.confirmation_resource(payload)? != *expected_resource {
            return Err(ShellError::Security(
                "confirmed resource changed before effect entry".to_owned(),
            ));
        }
        self.invoke(key, payload)
    }

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
    #[cfg(target_os = "linux")]
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
        #[cfg(target_os = "linux")]
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
            #[cfg(target_os = "linux")]
            canonical_roots.push(canonical);
            #[cfg(not(target_os = "linux"))]
            let _ = canonical;
        }
        Ok(Self {
            #[cfg(target_os = "linux")]
            allowed_path_roots: canonical_roots,
            allow_clipboard,
            allow_notifications,
        })
    }

    #[cfg(target_os = "linux")]
    fn path_allowed(&self, path: &Path) -> bool {
        let Ok(canonical) = std::fs::canonicalize(path) else {
            return false;
        };
        self.allowed_path_roots
            .iter()
            .any(|root| canonical.starts_with(root))
    }

    #[cfg(target_os = "linux")]
    fn open_handle_allowed(&self, file: &File) -> bool {
        use std::os::fd::AsRawFd as _;

        let descriptor = PathBuf::from(format!("/proc/self/fd/{}", file.as_raw_fd()));
        let Ok(canonical) = std::fs::canonicalize(descriptor) else {
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
        _action: PlatformAction,
        _status: std::process::ExitStatus,
    ) -> PlatformObservation {
        // A launcher or portal can apply the effect and then fail. Neither zero
        // nor nonzero exit proves the terminal state of the external consumer.
        // Only a queryable, operation-bound receipt may resolve it.
        PlatformObservation::indeterminate()
    }

    #[cfg(target_os = "linux")]
    fn open_verified_resource(&self, path: &Path) -> Result<(File, String), ShellError> {
        use std::os::unix::fs::MetadataExt as _;
        use std::os::unix::fs::OpenOptionsExt as _;

        if !path.is_absolute() || !self.policy.path_allowed(path) {
            return Err(ShellError::Security(
                "resource is outside the native path policy".to_owned(),
            ));
        }
        let mut options = OpenOptions::new();
        options.read(true).custom_flags(
            (rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::NONBLOCK).bits() as i32,
        );
        let file = options.open(path).map_err(|error| {
            ShellError::Platform(format!(
                "open verified resource without following links: {error}"
            ))
        })?;
        let metadata = file.metadata()?;
        if !metadata.is_file() && !metadata.is_dir() {
            return Err(ShellError::Security(
                "path effect requires a regular file or directory capability".to_owned(),
            ));
        }
        if !self.policy.open_handle_allowed(&file) {
            return Err(ShellError::Security(
                "opened resource handle is outside the native path policy".to_owned(),
            ));
        }
        let digest = sha256_hex(format!(
            "hepta.os-resource.v1:{}:{}:{}:{}:{}:{}:{}:{}",
            metadata.dev(),
            metadata.ino(),
            metadata.mode(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec()
        ));
        Ok((file, digest))
    }

    #[cfg(target_os = "linux")]
    fn ensure_portal_runtime(&self) -> Result<(), ShellError> {
        if std::env::var_os("DBUS_SESSION_BUS_ADDRESS").is_none()
            && std::env::var_os("XDG_RUNTIME_DIR").is_none()
        {
            return Err(ShellError::Platform(
                "XDG portal session bus is unavailable".into(),
            ));
        }
        let mut command =
            crate::native_platform::command(crate::native_platform::Helper::PortalProbe)?;
        command.stdin(Stdio::null()).stdout(Stdio::null());
        let status = run_bounded_launcher(
            command,
            "probe Rust XDG portal runtime",
            &self.active_launchers,
            PORTAL_PROBE_TIMEOUT,
        )?;
        if !status.success() {
            return Err(ShellError::Platform(format!(
                "XDG portal runtime probe failed: {status}"
            )));
        }
        Ok(())
    }
}

fn clipboard_readback_observation<E>(
    expected: &str,
    observed: Result<String, E>,
) -> PlatformObservation {
    match observed {
        Ok(value) if value == expected => PlatformObservation {
            terminal_status: Some(TerminalStatus::Succeeded),
            outcome_digest: Some(sha256_hex(format!(
                "hepta.clipboard-observation.v1:{}",
                sha256_hex(expected.as_bytes())
            ))),
        },
        Ok(_) | Err(_) => PlatformObservation::indeterminate(),
    }
}

impl PlatformAdapter for SystemPlatformAdapter {
    fn confirmation_resource(
        &self,
        payload: &PlatformPayload,
    ) -> Result<Option<String>, ShellError> {
        match payload {
            PlatformPayload::OpenPath { path } | PlatformPayload::RevealPath { path } => {
                #[cfg(target_os = "linux")]
                {
                    self.ensure_portal_runtime()?;
                    let (_file, digest) = self.open_verified_resource(path)?;
                    Ok(Some(digest))
                }
                #[cfg(not(target_os = "linux"))]
                {
                    let _ = path;
                    Err(unsupported_resource_handoff(payload.action()))
                }
            }
            _ => Ok(None),
        }
    }

    fn invoke_confirmed(
        &mut self,
        key: &OperationKey,
        payload: &PlatformPayload,
        expected_resource: &Option<String>,
    ) -> Result<PlatformObservation, ShellError> {
        match payload {
            PlatformPayload::OpenPath { path } | PlatformPayload::RevealPath { path } => {
                #[cfg(target_os = "linux")]
                {
                    let final_permission = self.permission(payload)?;
                    if !final_permission.allowed {
                        return Err(ShellError::Security(
                            "platform policy changed or was revoked before final OS entry"
                                .to_owned(),
                        ));
                    }
                    self.ensure_portal_runtime()?;
                    let (file, digest) = self.open_verified_resource(path)?;
                    if expected_resource.as_ref() != Some(&digest) {
                        return Err(ShellError::Security(
                            "verified resource identity changed before effect entry".to_owned(),
                        ));
                    }
                    let status =
                        launch_portal_resource(file, payload.action(), &self.active_launchers)?;
                    if !status.success() {
                        return Err(ShellError::Platform(format!(
                            "XDG resource handoff failed: {status}"
                        )));
                    }
                    Ok(self.launcher_observation(payload.action(), status))
                }
                #[cfg(not(target_os = "linux"))]
                {
                    let _ = (key, path, expected_resource);
                    Err(unsupported_resource_handoff(payload.action()))
                }
            }
            _ => {
                if self.confirmation_resource(payload)? != *expected_resource {
                    return Err(ShellError::Security(
                        "confirmed resource changed before effect entry".to_owned(),
                    ));
                }
                self.invoke(key, payload)
            }
        }
    }

    fn permission(&self, payload: &PlatformPayload) -> Result<PermissionDecision, ShellError> {
        payload.validate()?;
        let (allowed, reason) = match payload {
            PlatformPayload::OpenPath { path } | PlatformPayload::RevealPath { path } => {
                #[cfg(target_os = "linux")]
                {
                    (
                        self.policy.path_allowed(path),
                        if self.policy.path_allowed(path) {
                            "verified_resource_portal"
                        } else {
                            "path_policy"
                        },
                    )
                }
                #[cfg(not(target_os = "linux"))]
                {
                    let _ = path;
                    (false, "resource_capability_handoff_unavailable")
                }
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
            return Err(match payload {
                PlatformPayload::OpenPath { .. } | PlatformPayload::RevealPath { .. } => {
                    unsupported_resource_handoff(payload.action())
                }
                _ => ShellError::Security(
                    "platform policy changed or was revoked before final OS entry".to_owned(),
                ),
            });
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
                Ok(clipboard_readback_observation(text, clipboard.get_text()))
            }
            PlatformPayload::OpenPath { .. } | PlatformPayload::RevealPath { .. } => {
                // Path effects must enter through invoke_confirmed so the exact
                // verified open handle is handed to the portal.
                Err(unsupported_resource_handoff(payload.action()))
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

fn unsupported_resource_handoff(action: PlatformAction) -> ShellError {
    ShellError::Security(format!("{action}: {RESOURCE_HANDOFF_ERROR}"))
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
    maximum: Duration,
) -> Result<ExitStatus, ShellError> {
    let _slot = LauncherSlot::acquire(active)?;
    let mut child = command
        .spawn()
        .map_err(|error| ShellError::Platform(format!("{description}: {error}")))?;
    let deadline = Instant::now() + maximum;
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
                "{description} exceeded the bounded {maximum:?} launcher window; effect remains indeterminate"
            )));
        }
        std::thread::sleep(LAUNCHER_POLL_INTERVAL);
    }
}

#[cfg(target_os = "linux")]
fn launch_portal_resource(
    file: File,
    action: PlatformAction,
    active: &Arc<AtomicUsize>,
) -> Result<ExitStatus, ShellError> {
    let helper = match action {
        PlatformAction::OpenPath => crate::native_platform::Helper::OpenResource,
        PlatformAction::RevealPath => crate::native_platform::Helper::RevealResource,
        _ => {
            return Err(ShellError::State(
                "portal resource adapter received a non-resource action".into(),
            ));
        }
    };
    let mut command = crate::native_platform::command(helper)?;
    command.stdin(Stdio::from(file)).stdout(Stdio::null());
    run_bounded_launcher(
        command,
        "hand verified resource to XDG portal",
        active,
        RESOURCE_HANDOFF_TIMEOUT,
    )
}

#[cfg(target_os = "macos")]
fn notification_supported() -> bool {
    crate::native_platform::command(crate::native_platform::Helper::Notification).is_ok()
}

#[cfg(target_os = "windows")]
fn windows_identity_marker() -> Option<PathBuf> {
    let root = PathBuf::from(std::env::var_os("LOCALAPPDATA")?);
    if !root.is_absolute() {
        return None;
    }
    Some(root.join("Hepta/identity/aumid.txt"))
}

#[cfg(target_os = "windows")]
fn notification_supported() -> bool {
    let Some(marker) = windows_identity_marker() else {
        return false;
    };
    crate::native_platform::command(crate::native_platform::Helper::Notification).is_ok()
        && registered_notification_identity(&marker)
}

#[cfg(any(target_os = "windows", test))]
fn registered_notification_identity(marker: &Path) -> bool {
    crate::file_input::read_bytes(marker, 128).is_ok_and(|bytes| {
        std::str::from_utf8(&bytes).is_ok_and(|value| value.trim() == WINDOWS_AUMID)
    })
}

#[cfg(target_os = "linux")]
fn notification_supported() -> bool {
    (std::env::var_os("DBUS_SESSION_BUS_ADDRESS").is_some()
        || std::env::var_os("XDG_RUNTIME_DIR").is_some())
        && crate::native_platform::command(crate::native_platform::Helper::Notification).is_ok()
}

#[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
fn notification_supported() -> bool {
    false
}

fn launch_notification(
    title: &str,
    body: &str,
    active: &Arc<AtomicUsize>,
) -> Result<ExitStatus, ShellError> {
    #[cfg(target_os = "windows")]
    if !notification_supported() {
        return Err(ShellError::Platform(
            "Windows notification identity is not registered for Trillionnium.Hepta.Native".into(),
        ));
    }
    let mut command =
        crate::native_platform::command(crate::native_platform::Helper::Notification)?;
    command
        .env("HEPTA_NOTIFICATION_TITLE", title)
        .env("HEPTA_NOTIFICATION_BODY", body);
    run_bounded_launcher(
        command,
        "send native Rust notification",
        active,
        NOTIFICATION_TIMEOUT,
    )
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
    fn clipboard_exact_readback_is_the_only_terminal_success() {
        let expected = "read-back equality";
        let observation =
            clipboard_readback_observation(expected, Ok::<String, &str>(expected.to_owned()));
        assert_eq!(observation.terminal_status, Some(TerminalStatus::Succeeded));
        assert_eq!(
            observation.outcome_digest,
            Some(sha256_hex(format!(
                "hepta.clipboard-observation.v1:{}",
                sha256_hex(expected.as_bytes())
            )))
        );
    }

    #[test]
    fn clipboard_mismatch_or_read_failure_stays_indeterminate() {
        assert_eq!(
            clipboard_readback_observation("expected", Ok::<String, &str>("different".to_owned())),
            PlatformObservation::indeterminate()
        );
        assert_eq!(
            clipboard_readback_observation("expected", Err::<String, &str>("read failed")),
            PlatformObservation::indeterminate()
        );
    }

    #[test]
    fn path_outside_allowlist_is_denied() {
        let root = TempDir::new().unwrap();
        let outside = root.path().with_extension("outside");
        std::fs::write(&outside, b"outside").unwrap();
        let adapter = SystemPlatformAdapter::new(
            PlatformPolicy::new(vec![root.path().to_path_buf()], false, false).unwrap(),
        );
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

    #[cfg(target_os = "linux")]
    #[test]
    fn verified_resource_identity_changes_when_the_name_is_replaced() {
        let root = TempDir::new().unwrap();
        let path = root.path().join("resource.txt");
        std::fs::write(&path, b"first").unwrap();
        let adapter = SystemPlatformAdapter::new(
            PlatformPolicy::new(vec![root.path().to_path_buf()], false, false).unwrap(),
        );
        let (_first, first_digest) = adapter.open_verified_resource(&path).unwrap();
        let replacement = root.path().join("replacement.txt");
        std::fs::write(&replacement, b"second").unwrap();
        std::fs::rename(&replacement, &path).unwrap();
        let (_second, second_digest) = adapter.open_verified_resource(&path).unwrap();
        assert_ne!(first_digest, second_digest);
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn verified_resource_rejects_final_symlinks() {
        let root = TempDir::new().unwrap();
        let target = root.path().join("target.txt");
        let link = root.path().join("link.txt");
        std::fs::write(&target, b"target").unwrap();
        std::os::unix::fs::symlink(&target, &link).unwrap();
        let adapter = SystemPlatformAdapter::new(
            PlatformPolicy::new(vec![root.path().to_path_buf()], false, false).unwrap(),
        );
        assert!(adapter.open_verified_resource(&link).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn native_launchers_use_absolute_system_paths_and_cleared_environments() {
        let command = crate::native_platform::command(crate::native_platform::Helper::Notification)
            .expect("native notification command");
        assert_eq!(
            command.get_args().next(),
            Some(std::ffi::OsStr::new("--native-platform-helper"))
        );
        assert!(Path::new(command.get_program()).is_absolute());
        assert!(
            command
                .get_envs()
                .all(|(key, _)| key != "HEPTA_UNTRUSTED_TEST_VALUE")
        );
    }
}

#[cfg(all(test, unix))]
#[path = "platform_terminality_tests.rs"]
mod terminality_tests;

#[cfg(test)]
#[path = "platform_identity_tests.rs"]
mod identity_tests;
