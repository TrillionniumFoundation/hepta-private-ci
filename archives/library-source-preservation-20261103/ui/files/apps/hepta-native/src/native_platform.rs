//! Rust-only platform workers, owned and reaped by the existing native adapter.
//! A helper result is never a kernel grant or trustworthy terminal effect proof.
use std::io::Write as _;
use std::path::PathBuf;
use std::process::Command;

use crate::error::ShellError;

mod invocation;
#[cfg(target_os = "linux")]
mod linux;

const HELPER_ARG: &str = "--native-platform-helper";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Helper {
    Picker,
    ProtocolCheck,
    #[cfg(target_os = "linux")]
    PortalProbe,
    #[cfg(target_os = "linux")]
    OpenResource,
    #[cfg(target_os = "linux")]
    RevealResource,
    Notification,
}

impl Helper {
    fn argument(self) -> &'static str {
        match self {
            Self::Picker => "picker",
            Self::ProtocolCheck => "protocol-check",
            #[cfg(target_os = "linux")]
            Self::PortalProbe => "portal-probe",
            #[cfg(target_os = "linux")]
            Self::OpenResource => "open-resource",
            #[cfg(target_os = "linux")]
            Self::RevealResource => "reveal-resource",
            Self::Notification => "notification",
        }
    }
}

pub(crate) fn command(helper: Helper) -> Result<Command, ShellError> {
    // Linux resolves the actual loaded executable in the forked child. It does
    // not reopen a potentially replaced installation pathname.
    #[cfg(target_os = "linux")]
    let executable = PathBuf::from("/proc/self/exe");
    #[cfg(not(target_os = "linux"))]
    let executable = std::env::current_exe().map_err(|error| {
        ShellError::Platform(format!("native helper executable unavailable: {error}"))
    })?;
    if !executable.is_absolute() || !executable.is_file() {
        return Err(ShellError::Platform(
            "native helper executable is unavailable".into(),
        ));
    }
    let mut command = Command::new(executable);
    command.args([HELPER_ARG, helper.argument()]);
    command.env_clear();
    #[cfg(unix)]
    command.env("PATH", "/usr/bin:/bin");
    for key in [
        "HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_MESSAGES",
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XDG_RUNTIME_DIR",
        "XDG_CURRENT_DESKTOP",
        "DBUS_SESSION_BUS_ADDRESS",
        "SystemRoot",
        "WINDIR",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "LOCALAPPDATA",
    ] {
        if let Some(value) = std::env::var_os(key) {
            command.env(key, value);
        }
    }
    invocation::attach(&mut command, helper.argument())?;
    Ok(command)
}

/// Entry for an owned helper process. Normal application invocations return None.
/// Resource modes consume stdin's already-open FD; they accept no resource path.
/// The parent retains final-use admission, worker ownership and effect uncertainty.
pub fn run_child_if_requested(args: &[String]) -> Option<Result<(), ShellError>> {
    if args.first().map(String::as_str) != Some(HELPER_ARG) {
        return None;
    }
    Some((|| {
        if args.len() != 2 {
            return Err(ShellError::InvalidInput(
                "native helper requires one exact mode".into(),
            ));
        }
        invocation::verify(&args[1])?;
        match args[1].as_str() {
            "protocol-check" => Ok(()),
            "picker" => {
                if let Some(path) = select_file()? {
                    let path = path.to_str().ok_or_else(|| {
                        ShellError::InvalidInput("picker path is not UTF-8".into())
                    })?;
                    if !PathBuf::from(path).is_absolute()
                        || path.len() > crate::model::MAX_NATIVE_PATH_BYTES
                        || path.contains(['\0', '\r', '\n'])
                    {
                        return Err(ShellError::InvalidInput(
                            "picker path is not a bounded unambiguous absolute path".into(),
                        ));
                    }
                    // No newline: the exact selected filename is the message.
                    std::io::stdout()
                        .write_all(path.as_bytes())
                        .map_err(|error| {
                            ShellError::Platform(format!("write picker selection: {error}"))
                        })?;
                }
                Ok(())
            }
            "portal-probe" | "open-resource" | "reveal-resource" => {
                #[cfg(target_os = "linux")]
                {
                    linux::run(&args[1])
                }
                #[cfg(not(target_os = "linux"))]
                {
                    Err(ShellError::Platform(
                        "verified resource adapter is unavailable on this platform".into(),
                    ))
                }
            }
            "notification" => notify(),
            _ => Err(ShellError::InvalidInput(
                "unknown native helper mode".into(),
            )),
        }
    })())
}

#[cfg(target_os = "linux")]
fn select_file() -> Result<Option<PathBuf>, ShellError> {
    linux::select_file()
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
fn select_file() -> Result<Option<PathBuf>, ShellError> {
    Ok(rfd::FileDialog::new()
        .set_title("Select a Hepta input file")
        .pick_file())
}

#[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
fn select_file() -> Result<Option<PathBuf>, ShellError> {
    Err(ShellError::Platform("native picker is unsupported".into()))
}

fn notify() -> Result<(), ShellError> {
    let title = std::env::var("HEPTA_NOTIFICATION_TITLE")
        .map_err(|_| ShellError::InvalidInput("notification title is missing".into()))?;
    let body = std::env::var("HEPTA_NOTIFICATION_BODY")
        .map_err(|_| ShellError::InvalidInput("notification body is missing".into()))?;
    crate::model::PlatformPayload::Notify {
        title: title.clone(),
        body: body.clone(),
    }
    .validate()?;
    #[cfg(target_os = "linux")]
    {
        linux::notify(&title, &body)
    }
    #[cfg(target_os = "windows")]
    {
        winrt_notification::Toast::new("Trillionnium.Hepta.Native")
            .title(&title)
            .text1(&body)
            .show()
            .map_err(|_| ShellError::Platform("WinRT notification submission failed".into()))
    }
    #[cfg(target_os = "macos")]
    {
        // Never borrow Finder's identity or an unrelated application's bundle.
        mac_notification_sys::set_application("org.trillionnium.hepta.native")
            .map_err(|_| ShellError::Platform("native notification identity unavailable".into()))?;
        mac_notification_sys::send_notification(&title, None, &body, None)
            .map(|_| ())
            .map_err(|_| ShellError::Platform("native notification submission failed".into()))
    }
    #[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
    {
        Err(ShellError::Platform(
            "native notification is unsupported".into(),
        ))
    }
}

/// Exercise only the private helper handshake, with no desktop API or effect.
pub fn verify_helper_protocol() -> Result<(), ShellError> {
    let mut child = command(Helper::ProtocolCheck)?
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .spawn()
        .map_err(|_| ShellError::Platform("native helper protocol child could not start".into()))?;
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
    loop {
        match child.try_wait() {
            Ok(Some(status)) if status.success() => return Ok(()),
            Ok(Some(_)) => {
                return Err(ShellError::Security(
                    "native helper protocol rejected its parent".into(),
                ));
            }
            Ok(None) if std::time::Instant::now() < deadline => {
                std::thread::sleep(std::time::Duration::from_millis(10))
            }
            outcome => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(ShellError::Platform(format!(
                    "native helper protocol observation failed: {outcome:?}"
                )));
            }
        }
    }
}
