//! One owned Rust/OS-native dialog. Its result is untrusted input, never a
//! grant or verified OS resource handoff. Linux uses the desktop portal only.
#[cfg(target_os = "linux")]
use std::ffi::OsStr;
use std::path::PathBuf;
#[cfg(any(target_os = "macos", target_os = "windows", test))]
use std::process::{Command, Stdio};
#[cfg(any(target_os = "macos", target_os = "windows", test))]
use std::time::{Duration, Instant};

use crate::error::ShellError;

const MAX_SELECTION_BYTES: usize = 16 * 1024;
#[cfg(any(target_os = "macos", target_os = "windows", test))]
const MAX_DIALOG_OUTPUT_BYTES: usize = MAX_SELECTION_BYTES * 6 + 1024;
#[cfg(any(target_os = "macos", target_os = "windows"))]
const PICKER_TIMEOUT: Duration = Duration::from_secs(130);

#[cfg(any(target_os = "macos", target_os = "windows", test))]
#[path = "native_picker_helper.rs"]
mod helper;
#[cfg(target_os = "linux")]
#[path = "native_picker_linux.rs"]
mod linux;
#[cfg(any(target_os = "macos", target_os = "windows", test))]
use helper::parse_reply;
#[cfg(any(target_os = "macos", target_os = "windows"))]
pub(super) use helper::run as run_helper;

pub(super) fn choose_file() -> Result<Option<PathBuf>, ShellError> {
    #[cfg(target_os = "linux")]
    {
        validate_linux_backend(std::env::var_os("HEPTA_NATIVE_PICKER_BACKEND").as_deref())?;
        linux::choose_file()
    }
    #[cfg(any(target_os = "macos", target_os = "windows"))]
    {
        let executable = std::env::current_exe()?;
        let expected_digest = crate::update_storage::running_binary_digest()?;
        if crate::update_storage::digest_file(&executable)? != expected_digest {
            return Err(ShellError::Security(
                "native picker executable changed".into(),
            ));
        }
        let mut command = Command::new(executable);
        restrict_desktop_environment(&mut command);
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt as _;
            command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        }
        command.arg("--native-picker-helper");
        run_dialog(command, &expected_digest, PICKER_TIMEOUT)
    }
    #[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
    {
        Err(ShellError::Platform("native picker is unsupported".into()))
    }
}

#[cfg(target_os = "linux")]
fn validate_linux_backend(configured: Option<&OsStr>) -> Result<(), ShellError> {
    match configured {
        None => Ok(()),
        Some(value) if value == "portal" => Ok(()),
        Some(value) if value == "zenity" => Err(ShellError::Platform(
            "Zenity compatibility is retired; set HEPTA_NATIVE_PICKER_BACKEND=portal and install an XDG FileChooser portal backend".into(),
        )),
        Some(_) => Err(ShellError::InvalidInput(
            "HEPTA_NATIVE_PICKER_BACKEND must be portal".into(),
        )),
    }
}

#[cfg(any(target_os = "macos", target_os = "windows", test))]
fn restrict_desktop_environment(command: &mut Command) {
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
}

#[cfg(any(target_os = "macos", target_os = "windows", test))]
fn run_dialog(
    command: Command,
    expected_digest: &str,
    maximum: Duration,
) -> Result<Option<PathBuf>, ShellError> {
    run_dialog_at_boundary(command, expected_digest, maximum, |_| Ok(()))
}

#[cfg(any(target_os = "macos", target_os = "windows", test))]
fn run_dialog_at_boundary(
    mut command: Command,
    expected_digest: &str,
    maximum: Duration,
    mut observe: impl FnMut(&mut std::process::Child) -> Result<(), ShellError>,
) -> Result<Option<PathBuf>, ShellError> {
    let mut child = command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| ShellError::Platform(format!("start native picker: {error}")))?;
    let result = (|| {
        let mut stdout = child
            .stdout
            .take()
            .ok_or_else(|| ShellError::Platform("picker output pipe unavailable".into()))?;
        crate::native_pipe::prepare_reader(&stdout)?;
        let deadline = Instant::now() + maximum;
        let mut output = Vec::new();
        let mut status = None;
        loop {
            if Instant::now() >= deadline {
                return Err(ShellError::Platform(
                    "picker observation deadline exceeded".into(),
                ));
            }
            let mut block = [0_u8; 4096];
            let read_idle = match crate::native_pipe::read_available(&mut stdout, &mut block) {
                Ok(0) => true,
                Ok(length) => {
                    output.extend_from_slice(&block[..length]);
                    if output.len() > MAX_DIALOG_OUTPUT_BYTES {
                        return Err(ShellError::Platform(
                            "picker output exceeded its bound".into(),
                        ));
                    }
                    false
                }
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(error) if crate::native_pipe::would_block(&error) => true,
                Err(error) => return Err(error.into()),
            };
            if status.is_none() {
                observe(&mut child)?;
                status = child.try_wait()?;
                if status.is_some() {
                    // A writer may finish between our previous read and exit
                    // observation. Read again after observing exit before using
                    // WouldBlock/EOF as the final drain boundary.
                    continue;
                }
            }
            if let Some(status) = status {
                if read_idle {
                    if !status.success() {
                        return Err(ShellError::Platform(format!("picker failed: {status}")));
                    }
                    // Direct child exit is the framing boundary. Drain bytes
                    // already available, never wait for a descendant-held EOF.
                    return parse_reply(&output, expected_digest);
                }
            } else if read_idle {
                std::thread::sleep(Duration::from_millis(10));
            }
        }
    })();
    // No output thread survives the operation. Keep direct child ownership
    // through reaping; OS scheduling/reaping are not a real-time guarantee.
    let _ = child.kill();
    let _ = child.wait();
    result
}

fn validate_selection(text: &str) -> Result<PathBuf, ShellError> {
    if text.len() > MAX_SELECTION_BYTES || text.contains(['\0', '\r', '\n']) {
        return Err(ShellError::InvalidInput(
            "picker path exceeds its bound or contains control delimiters".into(),
        ));
    }
    let path = PathBuf::from(text);
    if !path.is_absolute() {
        return Err(ShellError::InvalidInput(
            "picker returned a non-absolute path".into(),
        ));
    }
    Ok(path)
}

#[cfg(test)]
#[path = "native_picker_framing_tests.rs"]
mod tests;
