//! Metadata-only activation of the actual two-application Session reservation.
use crate::AgentdError;
use crate::calculator_deadline::Deadline;
use codex_hepta_memory::CalculatorTargetIdentity;
use codex_hepta_memory::NotesTargetIdentity;
use std::io;
use std::mem;
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixDatagram;
use std::time::Duration;

/// Root copies the actual private reservation into its sealed deployment after
/// validating Session credentials and lifetime. This metadata is not a grant.
#[derive(serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdDesktopStartupRelease {
    pub notes: NotesTargetIdentity,
    pub calculator: CalculatorTargetIdentity,
    pub nonce: String,
}
impl AgentdDesktopStartupRelease {
    pub(crate) fn validate(&self) -> Result<(), AgentdError> {
        self.notes.validate().map_err(AgentdError::Invalid)?;
        self.calculator.validate().map_err(AgentdError::Invalid)?;
        if self.notes.task_id != 1
            || self.calculator.task_id != 2
            || self.notes.session_instance != self.calculator.session_instance
            || self.notes.incarnation == self.calculator.incarnation
            || self.nonce.len() != 32
            || !self
                .nonce
                .bytes()
                .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
            || !self.nonce.bytes().any(|byte| byte != b'0')
        {
            return Err(AgentdError::Invalid(
                "Desktop activation differs from the notes_calculator_v1 reservation".into(),
            ));
        }
        Ok(())
    }
}

pub(crate) fn activate_before(
    channel: &UnixDatagram,
    release: &AgentdDesktopStartupRelease,
    end: Deadline,
) -> Result<(), AgentdError> {
    let end = end.capped(Duration::from_millis(500))?;
    release.validate()?;
    crate::notes_bootstrap::require_socket(channel.as_raw_fd(), libc::SOCK_DGRAM)?;
    if !channel.local_addr()?.is_unnamed() || !channel.peer_addr()?.is_unnamed() {
        return Err(AgentdError::Invalid(
            "Desktop activation requires the inherited original pair".into(),
        ));
    }
    let mut passcred: libc::c_int = 0;
    let mut length = mem::size_of_val(&passcred) as libc::socklen_t;
    // SAFETY: the descriptor and correctly sized initialized output stay live.
    let result = unsafe {
        libc::getsockopt(
            channel.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PASSCRED,
            std::ptr::from_mut(&mut passcred).cast(),
            &mut length,
        )
    };
    if result != 0 {
        return Err(io::Error::last_os_error().into());
    }
    if length as usize != mem::size_of_val(&passcred) || passcred != 0 {
        return Err(AgentdError::Invalid(
            "Root must retire reservation credential mode before Desktop handoff".into(),
        ));
    }
    let bytes = serde_json::to_vec(&serde_json::json!({
        "schema_version":1,"action":"activate_desktop_bootstrap","profile":"notes_calculator_v1",
        "notes":release.notes,"calculator":release.calculator,"nonce":release.nonce
    }))?;
    if bytes.is_empty() || bytes.len() > 1024 {
        return Err(AgentdError::Invalid(
            "Desktop activation frame bound".into(),
        ));
    }
    channel.set_nonblocking(false)?;
    loop {
        let left = end.remaining()?;
        channel.set_write_timeout(Some(left))?;
        match channel.send(&bytes) {
            Ok(length) if length == bytes.len() => {
                end.remaining()?;
                return Ok(());
            }
            Ok(_) => {
                return Err(AgentdError::Protocol(
                    "Desktop activation was incomplete or late".into(),
                ));
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error.into()),
        }
    }
}
