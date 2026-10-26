//! One served Root session retained solely for a read-only predecessor capture.
use super::*;
use crate::HostNotesRecoveryPredecessor;
use std::os::fd::AsRawFd;

/// All original lane workers have finished. This object cannot serve again or
/// expose its old service. A lane error is retained separately and never proves
/// that the actual publisher retired or that its original lease expired.
pub struct StoppedHostNotesSession {
    session: Option<PreparedHostAuthoritySession>,
    serve_result: io::Result<()>,
}

impl PreparedHostAuthoritySession {
    /// Serve the original five lanes once, retaining these same owners after
    /// every started scoped worker has joined. Preflight errors do not start a
    /// service. Runtime errors remain observable on the stopped result; they
    /// are not converted to successful serving or recovery authorization.
    pub fn serve_retained_notes(self) -> io::Result<StoppedHostNotesSession> {
        self.service
            .require_notes_capture(&self.config, &self.registration)?;
        let serve_result = self.serve_selected(/*text_ui*/ None);
        Ok(StoppedHostNotesSession {
            session: Some(self),
            serve_result,
        })
    }
}

impl StoppedHostNotesSession {
    /// The unchanged original serving outcome, including timeout or peer error.
    pub fn serve_result(&self) -> Result<(), &io::Error> {
        self.serve_result.as_ref().map(|()| ())
    }

    /// Capture only this stopped service's exact original predecessor. There
    /// are no caller-selected proof, target or checkpoint inputs. Failure keeps
    /// this stopped object for a later read-only attempt; success drops the old
    /// service and cannot be repeated. The successor still requires the public
    /// recovery opener's independent original live authorization and exact cut.
    pub fn try_capture_predecessor(&mut self) -> io::Result<HostNotesRecoveryPredecessor> {
        let session = self
            .session
            .as_ref()
            .ok_or_else(|| io::Error::other("Notes predecessor already captured"))?;
        require_publisher_exit(&session.owner_pidfd)?;
        let previous = session
            .service
            .capture_notes_predecessor(&session.config, &session.registration)?;
        require_publisher_exit(&session.owner_pidfd)?;
        drop(self.session.take());
        Ok(previous)
    }
}

fn require_publisher_exit(pidfd: &OwnedFd) -> io::Result<()> {
    let mut poll = libc::pollfd {
        fd: pidfd.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };
    // SAFETY: one initialized pollfd borrows the originally verified descriptor.
    let count = unsafe { libc::poll(&mut poll, 1, 0) };
    if count < 0 || poll.revents & (libc::POLLERR | libc::POLLNVAL) != 0 {
        return Err(io::Error::other(
            "original publisher retirement unavailable",
        ));
    }
    if count == 0 || poll.revents & libc::POLLIN == 0 {
        return Err(io::Error::other("original publisher has not exited"));
    }
    Ok(())
}
