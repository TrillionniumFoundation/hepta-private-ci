//! Private inherited-channel handshake, not a new final-use authority source.
//! Same-UID code with arbitrary process/FD access is outside this isolation boundary.
use std::io::Read as _;
use std::io::Write as _;
use std::process::Command;
use std::process::Stdio;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::error::ShellError;

const NONCE_ENV: &str = "HEPTA_NATIVE_HELPER_NONCE";
const MAX_TICKET_BYTES: u64 = 1024;

#[derive(serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct Ticket {
    schema: u32,
    mode: String,
    parent: u32,
    created_ms: u64,
    nonce: String,
}

fn denied() -> ShellError {
    ShellError::Security("native helper requires its parent's private inherited channel".into())
}
fn now_ms() -> Result<u64, ShellError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| denied())?
        .as_millis()
        .try_into()
        .map_err(|_| denied())
}

pub(super) fn attach(command: &mut Command, mode: &str) -> Result<(), ShellError> {
    let mut random = [0_u8; 32];
    getrandom::fill(&mut random).map_err(|_| denied())?;
    let nonce = random
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let bytes = serde_json::to_vec(&Ticket {
        schema: 1,
        mode: mode.into(),
        parent: std::process::id(),
        created_ms: now_ms()?,
        nonce: nonce.clone(),
    })
    .map_err(|_| denied())?;
    let (reader, mut writer) = std::io::pipe().map_err(|_| denied())?;
    writer.write_all(&bytes).map_err(|_| denied())?;
    drop(writer);
    // stderr is deliberately a read-only inherited pipe for this internal mode.
    // No user-supplied filename or command-line ticket is accepted.
    command.env(NONCE_ENV, nonce).stderr(Stdio::from(reader));
    Ok(())
}

pub(super) fn verify(mode: &str) -> Result<(), ShellError> {
    let nonce = std::env::var(NONCE_ENV).map_err(|_| denied())?;
    if nonce.len() != 64
        || !nonce
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(denied());
    }
    let parent = Some(verify_parent_image()?);
    #[cfg(unix)]
    let channel = {
        use std::os::fd::AsFd as _;
        use std::os::unix::fs::FileTypeExt as _;
        let channel = std::fs::File::from(
            std::io::stderr()
                .as_fd()
                .try_clone_to_owned()
                .map_err(|_| denied())?,
        );
        if !channel
            .metadata()
            .map_err(|_| denied())?
            .file_type()
            .is_fifo()
        {
            return Err(denied());
        }
        channel
    };
    #[cfg(windows)]
    let channel = {
        use std::os::windows::io::AsHandle as _;
        std::fs::File::from(
            std::io::stderr()
                .as_handle()
                .try_clone_to_owned()
                .map_err(|_| denied())?,
        )
    };
    #[cfg(not(any(unix, windows)))]
    return Err(denied());
    #[cfg(any(unix, windows))]
    {
        let mut bytes = Vec::new();
        channel
            .take(MAX_TICKET_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| denied())?;
        validate(&bytes, mode, &nonce, parent, now_ms()?)
    }
}

#[cfg(target_os = "linux")]
fn verify_parent_image() -> Result<u32, ShellError> {
    use std::os::unix::fs::MetadataExt as _;
    let parent = rustix::process::getppid()
        .ok_or_else(denied)?
        .as_raw_nonzero()
        .get() as u32;
    let owner = std::fs::metadata(format!("/proc/{parent}/exe")).map_err(|_| denied())?;
    let child = std::fs::metadata("/proc/self/exe").map_err(|_| denied())?;
    if (owner.dev(), owner.ino()) != (child.dev(), child.ino()) {
        return Err(denied());
    }
    Ok(parent)
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
fn verify_parent_image() -> Result<u32, ShellError> {
    use sysinfo::{ProcessRefreshKind, ProcessesToUpdate, System, UpdateKind};
    let pid = sysinfo::get_current_pid().map_err(|_| denied())?;
    let mut system = System::new();
    system.refresh_processes_specifics(
        ProcessesToUpdate::Some(&[pid]),
        true,
        ProcessRefreshKind::nothing().without_tasks(),
    );
    let parent = system
        .process(pid)
        .and_then(|process| process.parent())
        .ok_or_else(denied)?;
    system.refresh_processes_specifics(
        ProcessesToUpdate::Some(&[parent]),
        true,
        ProcessRefreshKind::nothing()
            .without_tasks()
            .with_exe(UpdateKind::Always),
    );
    let image = system
        .process(parent)
        .and_then(|process| process.exe())
        .ok_or_else(denied)?;
    if !same_file::is_same_file(image, std::env::current_exe().map_err(|_| denied())?)
        .map_err(|_| denied())?
    {
        return Err(denied());
    }
    Ok(parent.as_u32())
}

#[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
fn verify_parent_image() -> Result<u32, ShellError> {
    Err(denied())
}

fn validate(
    bytes: &[u8],
    mode: &str,
    nonce: &str,
    parent: Option<u32>,
    now: u64,
) -> Result<(), ShellError> {
    if bytes.len() > MAX_TICKET_BYTES as usize {
        return Err(denied());
    }
    let ticket: Ticket = serde_json::from_slice(bytes).map_err(|_| denied())?;
    if ticket.schema != 1
        || ticket.mode != mode
        || ticket.parent == 0
        || parent.is_some_and(|parent| parent != ticket.parent)
        || ticket.created_ms > now
        || now - ticket.created_ms > 10_000
        || !hepta_control_ui::canonical::constant_time_equal(&ticket.nonce, nonce)
    {
        return Err(denied());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn inherited_ticket_rejects_wrong_mode_parent_nonce_age_and_unknown_fields() {
        let nonce = "a".repeat(64);
        let ticket = Ticket {
            schema: 1,
            mode: "notification".into(),
            parent: 123,
            created_ms: 1000,
            nonce: nonce.clone(),
        };
        let bytes = serde_json::to_vec(&ticket).unwrap();
        assert!(validate(&bytes, "notification", &nonce, Some(123), 1001).is_ok());
        for (mode, token, parent, now) in [
            ("picker", nonce.clone(), Some(123), 1001),
            ("notification", "b".repeat(64), Some(123), 1001),
            ("notification", nonce.clone(), Some(124), 1001),
            ("notification", nonce.clone(), Some(123), 999),
            ("notification", nonce.clone(), Some(123), 11001),
        ] {
            assert!(validate(&bytes, mode, &token, parent, now).is_err());
        }
        let mut object = serde_json::to_value(&ticket).unwrap();
        object["grant"] = serde_json::json!(true);
        assert!(
            validate(
                &serde_json::to_vec(&object).unwrap(),
                "notification",
                &nonce,
                Some(123),
                1001
            )
            .is_err()
        );
        assert!(validate(&vec![b'a'; 1025], "notification", &nonce, Some(123), 1001).is_err());
    }
}
