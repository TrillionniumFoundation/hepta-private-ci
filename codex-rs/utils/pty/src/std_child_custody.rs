use std::io;
use std::process::Child;
use std::process::Command;
use std::process::ExitStatus;

#[cfg(unix)]
use std::os::unix::process::CommandExt;
#[cfg(windows)]
use crate::JobObject;

/// Owns a synchronous child and the process group or non-breakaway job created for it.
///
/// Completion requests termination of remaining group/job members before releasing the child identity.
/// On Unix the leader remains unreaped until the group has been signalled, so a recycled PID
/// cannot become the target of cleanup. This does not contain a Unix descendant that explicitly
/// escapes its process group; callers must not use it as a sandbox boundary. Returning a direct
/// child status is not a separate observation that every descendant has reached its terminal state.
pub struct StdChildCustody {
    child: Child,
    status: Option<ExitStatus>,
    #[cfg(unix)]
    leader_owned: bool,
    #[cfg(windows)]
    job: JobObject,
}

impl StdChildCustody {
    /// Spawns the command only after arranging a new process group or contained Windows job.
    /// A failure to establish Windows containment never falls back to an uncontained child.
    pub fn spawn(command: &mut Command) -> io::Result<Self> {
        #[cfg(unix)]
        let child = command.process_group(/*pgroup*/ 0).spawn()?;
        #[cfg(windows)]
        let (child, job) = {
            let job = JobObject::create_without_breakaway()?;
            let child = job.spawn_contained_std(command)?;
            (child, job)
        };
        Ok(Self {
            child,
            status: None,
            #[cfg(unix)]
            leader_owned: true,
            #[cfg(windows)]
            job,
        })
    }

    /// Checks for child exit and, on completion, requests termination of its owned group/job.
    /// Repeated calls return the same terminal status without signalling another process group.
    pub fn try_wait(&mut self) -> io::Result<Option<ExitStatus>> {
        if let Some(status) = self.status {
            return Ok(Some(status));
        }
        #[cfg(unix)]
        {
            if !self.peek_exit()? {
                return Ok(None);
            }
            self.terminate_group()?;
            let status = self.child.wait()?;
            self.leader_owned = false;
            self.status = Some(status);
            Ok(Some(status))
        }
        #[cfg(windows)]
        {
            let Some(status) = self.child.try_wait()? else {
                return Ok(None);
            };
            self.job.terminate()?;
            self.status = Some(status);
            Ok(Some(status))
        }
    }

    /// Requests termination of the owned group/job and reaps the direct child.
    /// Errors remain errors: they are not evidence that the process tree was cleaned up.
    pub fn kill_and_wait(&mut self) -> io::Result<ExitStatus> {
        if let Some(status) = self.status {
            return Ok(status);
        }
        #[cfg(unix)]
        {
            // WNOWAIT checks the actual child relationship even when the leader has exited.
            // ECHILD revokes numeric-group signalling authority rather than guessing ownership.
            let exited = self.peek_exit()?;
            self.terminate_group()?;
            if !exited {
                // The actual, still-unreaped child may have moved out of its original process
                // group. Group ESRCH does not prove it exited. Kill only this retained Child;
                // never obtain a replacement process handle by numeric PID.
                self.child.kill()?;
            }
        }
        #[cfg(windows)]
        self.job.terminate()?;
        let status = self.child.wait()?;
        #[cfg(unix)]
        {
            self.leader_owned = false;
        }
        self.status = Some(status);
        Ok(status)
    }

    #[cfg(unix)]
    fn peek_exit(&mut self) -> io::Result<bool> {
        if !self.leader_owned {
            return Err(io::Error::other("synchronous child custody was lost"));
        }
        loop {
            let mut info: libc::siginfo_t = unsafe { std::mem::zeroed() };
            let result = unsafe {
                libc::waitid(
                    libc::P_PID,
                    self.child.id() as libc::id_t,
                    &mut info,
                    libc::WEXITED | libc::WNOHANG | libc::WNOWAIT,
                )
            };
            if result == -1 {
                let error = io::Error::last_os_error();
                if error.kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                if error.raw_os_error() == Some(libc::ECHILD) {
                    self.leader_owned = false;
                }
                return Err(error);
            }
            let observed_pid = unsafe { info.si_pid() };
            if observed_pid == 0 {
                return Ok(false);
            }
            if observed_pid != self.child.id() as libc::pid_t {
                self.leader_owned = false;
                return Err(io::Error::other("waitid returned an unrelated child"));
            }
            return Ok(true);
        }
    }

    #[cfg(unix)]
    fn terminate_group(&self) -> io::Result<()> {
        if !self.leader_owned {
            return Err(io::Error::other("synchronous child custody was lost"));
        }
        let result = unsafe { libc::killpg(self.child.id() as libc::pid_t, libc::SIGKILL) };
        if result == -1 {
            let error = io::Error::last_os_error();
            if error.raw_os_error() != Some(libc::ESRCH) {
                return Err(error);
            }
        }
        Ok(())
    }
}

impl Drop for StdChildCustody {
    fn drop(&mut self) {
        let _ = self.kill_and_wait();
    }
}

#[cfg(test)]
#[path = "std_child_custody_tests.rs"]
mod tests;
