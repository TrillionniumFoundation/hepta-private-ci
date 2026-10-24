//! Fixed acceptance failures kill the actual original child; they do not
//! replace an owner API result, registry state, Current or process exit value.

use super::*;
use std::os::fd::AsRawFd;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum FailurePoint {
    AfterProof,
    AfterMaterial,
}

impl PendingActivation {
    pub(crate) fn fail_at(
        &mut self,
        point: FailurePoint,
        retained: &crate::RetainedCheckpointPublisher,
        deadline: u64,
    ) -> io::Result<()> {
        if self.fault != Some(point) {
            return Ok(());
        }
        if self.spec.generation <= 1
            || self.peer != *retained.lifetime()
            || peer(self.peer.pid, self.peer.uid)? != self.peer
        {
            return Err(invalid(
                "fixed activation fault lacks an actual successor publisher",
            ));
        }
        let held = pidfd(self.peer.pid)?;
        retained.check_alive_for_root().map_err(error)?;
        self.fault = None;
        if unsafe {
            libc::syscall(
                libc::SYS_pidfd_send_signal,
                held.as_raw_fd(),
                libc::SIGKILL,
                std::ptr::null::<libc::siginfo_t>(),
                0,
            )
        } < 0
        {
            return Err(io::Error::last_os_error());
        }
        let (revents, signal) = recovery::observe_child_exit(self.peer.pid, &held, deadline)?;
        self.fault_observation = Some(serde_json::json!({
            "point":match point { FailurePoint::AfterProof => "after_proof", FailurePoint::AfterMaterial => "after_material" },
            "peer":self.peer,"spawn_generation":self.spec.generation,
            "pidfd_revents":revents,"wait_kind":"signaled","wait_value":signal,
            "observed_boottime_ns":now()?,
        }));
        // Return to the original implementation. Its real retained-pidfd,
        // checkpoint or sealed launch operation supplies the actual failure;
        // the driver still exclusively owns waitpid/reaping and Failed.
        Ok(())
    }
}
