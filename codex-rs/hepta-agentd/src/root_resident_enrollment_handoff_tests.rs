//! Actual FD framing mechanisms, not a fabricated Root enrollment receipt.

use super::*;
use std::io::{Read, Seek};
use std::os::fd::FromRawFd;

fn root_pin() -> Result<OwnedFd, Box<dyn std::error::Error>> {
    // SAFETY: test opens only its current process, with zero flags.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    if raw < 0 { return Err(io::Error::last_os_error().into()); }
    // SAFETY: exactly the newly returned descriptor is adopted once.
    Ok(unsafe { OwnedFd::from_raw_fd(raw as i32) })
}

fn require_root() -> Result<(), Box<dyn std::error::Error>> {
    // SAFETY: only actual credential reads.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err("this original Root FD mechanism requires UID0".into());
    }
    Ok(())
}

#[test]
#[ignore = "requires actual original Root credentials and Linux pidfd"]
fn exact_v3_framing_preserves_original_sealed_bytes_and_root_pidfd() -> Result<(), Box<dyn std::error::Error>> {
    require_root()?;
    let (sender, receiver) = UnixDatagram::pair()?;
    let bytes = b"framing-only: no profile, owner or successful protocol response";
    let sealed = crate::authority_host_bootstrap_seal::seal_bytes(bytes)?;
    let pidfd = root_pin()?;
    send_original_resident_enrollment(sender, &sealed, &pidfd, Duration::from_millis(100))?;
    let (mut received, pin) = receive_once(receiver.as_raw_fd())?;
    validate_bootstrap(&received)?;
    require_original_resident_process_pin(&pin, std::process::id())?;
    received.rewind()?;
    let mut actual = Vec::new(); received.read_to_end(&mut actual)?;
    assert_eq!(actual, bytes);
    Ok(())
}

#[test]
#[ignore = "requires actual original Root credentials and Linux pidfd"]
fn v1_marker_cannot_enter_the_v3_resident_handoff() -> Result<(), Box<dyn std::error::Error>> {
    require_root()?;
    let (sender, receiver) = UnixDatagram::pair()?;
    let sealed = crate::authority_host_bootstrap_seal::seal_bytes(b"original sealed framing input")?;
    let pidfd = root_pin()?;
    send_packet(&sender, b"HEPTA_ROOT_LEARNING_INPUTS_V1", &[sealed.as_raw_fd(), pidfd.as_raw_fd()], Duration::from_millis(100))?;
    let result = receive_once(receiver.as_raw_fd());
    assert!(matches!(result, Err(AgentdError::Protocol(message)) if message.contains("exact purpose and two rights")));
    Ok(())
}

#[test]
#[ignore = "requires actual original Root credentials and Linux pidfd"]
fn sealed_file_alias_cannot_replace_the_original_root_pidfd() -> Result<(), Box<dyn std::error::Error>> {
    require_root()?;
    let (sender, receiver) = UnixDatagram::pair()?;
    let sealed = crate::authority_host_bootstrap_seal::seal_bytes(b"original sealed framing input")?;
    send_packet(&sender, FRAME_V3, &[sealed.as_raw_fd(), sealed.as_raw_fd()], Duration::from_millis(100))?;
    let (received, not_pidfd) = receive_once(receiver.as_raw_fd())?;
    validate_bootstrap(&received)?;
    let result = require_original_resident_process_pin(&not_pidfd, std::process::id());
    assert!(matches!(result, Err(AgentdError::Protocol(message)) if message.contains("pidfd")));
    Ok(())
}
