//! Activate one actual Session reservation after original host recovery. This
//! sends metadata only; it is neither a grant nor an Attached acknowledgement.

use super::*;
use codex_hepta_memory::NotesTargetIdentity;

/// Copied by the trusted Root producer from the actual private Reserved frame
/// into its sealed deployment. Ordinary UI/control never supplies this value.
pub struct AgentdNotesStartupRelease {
    pub target: NotesTargetIdentity,
    pub nonce: String,
}

impl AgentdNotesStartupRelease {
    pub(crate) fn validate(&self) -> Result<(), AgentdError> {
        self.target.validate().map_err(AgentdError::Invalid)?;
        if self.target.task_id != 1 || self.nonce.len() != 32
            || !self.nonce.bytes().all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
            || !self.nonce.bytes().any(|byte| byte != b'0')
        { return Err(AgentdError::Invalid("Notes activation differs from the original reservation profile".into())); }
        Ok(())
    }
}

pub(crate) fn activate_startup(channel: &UnixDatagram, release: &AgentdNotesStartupRelease) -> Result<(), AgentdError> {
    release.validate()?;
    require_socket(channel.as_raw_fd(), libc::SOCK_DGRAM)?;
    if !channel.local_addr()?.is_unnamed() || !channel.peer_addr()?.is_unnamed() {
        return Err(AgentdError::Invalid("Notes activation requires the original inherited private pair".into()));
    }
    let mut passcred: libc::c_int = 0;
    let mut length = mem::size_of_val(&passcred) as libc::socklen_t;
    // SAFETY: the original channel remains held and the output buffer is sized.
    let result = unsafe { libc::getsockopt(channel.as_raw_fd(), libc::SOL_SOCKET, libc::SO_PASSCRED,
        std::ptr::from_mut(&mut passcred).cast(), &mut length) };
    if result != 0 { return Err(io::Error::last_os_error().into()); }
    if length as usize != mem::size_of_val(&passcred) || passcred != 0 {
        return Err(AgentdError::Invalid("Root reservation receiver must release credential mode before original Notes handoff".into()));
    }
    let raw = serde_json::to_vec(&serde_json::json!({
        "schema_version":1, "action":"activate_notes_bootstrap", "target":release.target,
        "destination_id":release.target.destination_id(), "nonce":release.nonce,
    }))?;
    if raw.is_empty() || raw.len() > MAX_BOOTSTRAP_BYTES {
        return Err(AgentdError::Invalid("Notes activation frame bound".into()));
    }
    let end = Instant::now() + Duration::from_millis(500);
    channel.set_nonblocking(false)?;
    loop {
        channel.set_write_timeout(Some(remaining(end)?))?;
        match channel.send(&raw) {
            Ok(sent) if sent == raw.len() => { remaining(end)?; return Ok(()); }
            Ok(_) => return Err(AgentdError::Invalid("Notes activation was not sent atomically".into())),
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error.into()),
        }
    }
}

#[cfg(test)]
#[path = "notes_startup_tests.rs"]
mod tests;
