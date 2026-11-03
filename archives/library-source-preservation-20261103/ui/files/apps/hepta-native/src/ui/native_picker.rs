//! One owned platform dialog. Its result is untrusted file input, never a grant
//! or verified OS resource handoff. Every production adapter is Rust; Linux
//! uses the XDG portal without a script or silent fallback.
#[cfg(target_os = "linux")]
use std::ffi::OsStr;
use std::io::Read;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use crate::error::ShellError;

const MAX_SELECTION_BYTES: usize = 16 * 1024;
// Portal observation owns up to 120 seconds plus a five-second Close RPC;
// allow a further reap margin instead of killing it at that exact boundary.
const PICKER_TIMEOUT: Duration = Duration::from_secs(130);

pub(super) fn choose_file() -> Result<Option<PathBuf>, ShellError> {
    let (command, cancel_exit) = dialog_command()?;
    run_dialog(command, cancel_exit, PICKER_TIMEOUT)
}

#[cfg(target_os = "linux")]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum LinuxPickerBackend {
    Portal,
}

#[cfg(target_os = "linux")]
fn parse_linux_picker_backend(
    configured: Option<&OsStr>,
) -> Result<LinuxPickerBackend, ShellError> {
    match configured {
        None => Ok(LinuxPickerBackend::Portal),
        Some(value) if value == "portal" => Ok(LinuxPickerBackend::Portal),
        Some(_) => Err(ShellError::InvalidInput(
            "the picker requires the Rust portal adapter; script/Zenity backends are retired"
                .into(),
        )),
    }
}

fn dialog_command() -> Result<(Command, Option<i32>), ShellError> {
    #[cfg(target_os = "linux")]
    let _ = parse_linux_picker_backend(std::env::var_os("HEPTA_NATIVE_PICKER_BACKEND").as_deref())?;
    let command = crate::native_platform::command(crate::native_platform::Helper::Picker)?;
    Ok((command, None))
}

fn run_dialog(
    mut command: Command,
    cancel_exit: Option<i32>,
    maximum: Duration,
) -> Result<Option<PathBuf>, ShellError> {
    let mut child = command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .spawn()
        .map_err(|error| ShellError::Platform(format!("start native picker: {error}")))?;
    let Some(stdout) = child.stdout.take() else {
        let _ = child.kill();
        let _ = child.wait();
        return Err(ShellError::Platform(
            "picker output pipe unavailable".into(),
        ));
    };
    let reader = std::thread::Builder::new()
        .name("hepta-picker-output".into())
        .spawn(move || {
            let mut bytes = Vec::new();
            stdout
                .take((MAX_SELECTION_BYTES + 1) as u64)
                .read_to_end(&mut bytes)
                .map(|_| bytes)
        });
    let mut reader = match reader {
        Ok(reader) => Some(reader),
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(ShellError::Platform(format!(
                "start picker reader: {error}"
            )));
        }
    };
    let started = Instant::now();
    let mut output = None;
    let status = loop {
        if reader.as_ref().is_some_and(|reader| reader.is_finished()) {
            let result = reader
                .take()
                .expect("finished reader is still owned")
                .join();
            match result {
                Ok(Ok(bytes)) if bytes.len() <= MAX_SELECTION_BYTES => output = Some(bytes),
                _ => {
                    let _ = child.kill();
                    let _ = child.wait();
                    break Err(ShellError::Platform(
                        "picker output failed or exceeded its bound".into(),
                    ));
                }
            }
        }
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status),
            Ok(None) if started.elapsed() < maximum => {
                std::thread::sleep(Duration::from_millis(10));
            }
            Ok(None) => {
                let _ = child.kill();
                let _ = child.wait();
                break Err(ShellError::Platform(
                    "picker observation deadline exceeded".into(),
                ));
            }
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                break Err(ShellError::Platform(format!("observe picker: {error}")));
            }
        }
    };
    // Reaping may block at the OS boundary. Retain ownership; no detached task,
    // automatic update activation, or claim of forced cancellation is permitted.
    if let Some(reader) = reader {
        output = Some(
            reader
                .join()
                .map_err(|_| ShellError::Platform("picker reader panicked".into()))?
                .map_err(|error| ShellError::Platform(format!("read picker selection: {error}")))?,
        );
    }
    let status = status?;
    if cancel_exit.is_some() && status.code() == cancel_exit {
        return Ok(None);
    }
    if !status.success() {
        return Err(ShellError::Platform(format!("picker failed: {status}")));
    }
    parse_selection(&output.unwrap_or_default())
}

fn parse_selection(bytes: &[u8]) -> Result<Option<PathBuf>, ShellError> {
    if bytes.len() > MAX_SELECTION_BYTES {
        return Err(ShellError::InvalidInput(
            "picker output exceeds byte bound".into(),
        ));
    }
    let text = std::str::from_utf8(bytes)
        .map_err(|_| ShellError::InvalidInput("picker selection is not UTF-8".into()))?;
    let text = text
        .strip_suffix("\r\n")
        .or_else(|| text.strip_suffix('\n'))
        .unwrap_or(text);
    if text.is_empty() {
        return Ok(None);
    }
    if text.contains(['\0', '\r', '\n']) {
        return Err(ShellError::InvalidInput(
            "picker returned control delimiters or multiple paths".into(),
        ));
    }
    let path = PathBuf::from(text);
    if !path.is_absolute() {
        return Err(ShellError::InvalidInput(
            "picker returned a relative path".into(),
        ));
    }
    Ok(Some(path))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn picker_rejects_ambiguous_and_unbounded_results() {
        for bytes in [b"relative".as_slice(), b"/one\n/two", b"/one\0", &[255]] {
            assert!(parse_selection(bytes).is_err());
        }
        assert!(parse_selection(&vec![b'a'; MAX_SELECTION_BYTES + 1]).is_err());
        assert!(parse_selection(b"").unwrap().is_none());
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn linux_picker_requires_rust_portal_and_rejects_retired_backends() {
        assert_eq!(
            parse_linux_picker_backend(None).unwrap(),
            LinuxPickerBackend::Portal
        );
        assert_eq!(
            parse_linux_picker_backend(Some(OsStr::new("portal"))).unwrap(),
            LinuxPickerBackend::Portal
        );
        assert!(parse_linux_picker_backend(Some(OsStr::new("zenity"))).is_err());
        assert!(parse_linux_picker_backend(Some(OsStr::new("auto"))).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn picker_preserves_spaces_and_reaps_fixture_process() {
        assert_eq!(
            parse_selection(b"/tmp/ input \n").unwrap(),
            Some(PathBuf::from("/tmp/ input "))
        );
        let mut command = Command::new("/bin/sh");
        command.args(["-c", "printf '/tmp/selected\\n'"]);
        assert_eq!(
            run_dialog(command, None, Duration::from_secs(2)).unwrap(),
            Some(PathBuf::from("/tmp/selected"))
        );
        let mut command = Command::new("/bin/sh");
        command.args(["-c", "exit 1"]);
        assert!(
            run_dialog(command, Some(1), Duration::from_secs(2))
                .unwrap()
                .is_none()
        );
    }

    #[cfg(unix)]
    #[test]
    fn picker_subprocess_environment_is_allowlisted() {
        let command =
            crate::native_platform::command(crate::native_platform::Helper::Picker).unwrap();
        assert!(command.get_program().to_string_lossy().starts_with('/'));
        assert!(command.get_envs().all(|(key, _)| {
            [
                "PATH",
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
                "HEPTA_NATIVE_HELPER_NONCE",
                "SystemRoot",
                "WINDIR",
                "TEMP",
                "TMP",
                "USERPROFILE",
                "LOCALAPPDATA",
            ]
            .iter()
            .any(|allowed| key == *allowed)
        }));
    }
}
