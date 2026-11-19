use super::LockedHandoffFile;

use pretty_assertions::assert_eq;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::time::Duration;
use std::time::Instant;
use tempfile::TempDir;

#[derive(Clone, Copy, Debug)]
enum ChildObservation {
    Owned,
    Reaped(i32),
    Lost,
}

struct ForkChild {
    pid: libc::pid_t,
    observation: ChildObservation,
    deadline: Instant,
    termination_requested: bool,
}

impl ForkChild {
    fn observe(&mut self) -> io::Result<Option<i32>> {
        match self.observation {
            ChildObservation::Reaped(status) => return Ok(Some(status)),
            ChildObservation::Lost => {
                return Err(io::Error::other("fork child observation was lost"));
            }
            ChildObservation::Owned => {}
        }
        let mut status = 0;
        // This fixture is the sole waiter for its unreaped child. Never use a
        // wildcard PID or query this PID after reaping or losing observation.
        let actual = unsafe { libc::waitpid(self.pid, &mut status, libc::WNOHANG) };
        if actual == self.pid {
            self.observation = ChildObservation::Reaped(status);
            return Ok(Some(status));
        }
        if actual == 0 {
            return Ok(None);
        }
        let error = if actual == -1 {
            io::Error::last_os_error()
        } else {
            io::Error::other("waitpid returned a different child identity")
        };
        if error.kind() != io::ErrorKind::Interrupted {
            self.observation = ChildObservation::Lost;
        }
        Err(error)
    }

    fn remaining(&self) -> io::Result<Duration> {
        self.deadline
            .checked_duration_since(Instant::now())
            .filter(|remaining| !remaining.is_zero())
            .ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::TimedOut,
                    "fork child deadline expired; cleanup is not confirmed",
                )
            })
    }

    fn wait_until_deadline(&mut self) -> io::Result<i32> {
        loop {
            self.remaining()?;
            match self.observe() {
                Ok(Some(status)) => {
                    // A late observation cannot turn the expired test into PASS.
                    self.remaining()?;
                    return Ok(status);
                }
                Ok(None) => {}
                Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
                Err(error) => return Err(error),
            }
            std::thread::sleep(self.remaining()?.min(Duration::from_millis(1)));
        }
    }

    fn terminate_and_reap_until_deadline(&mut self) -> io::Result<i32> {
        self.remaining()?;
        if let Some(status) = self.observe()? {
            return Ok(status);
        }
        self.remaining()?;
        if !self.termination_requested {
            self.termination_requested = true;
            // Only the original, still-unreaped fixture child is eligible.
            // SIGKILL success is a request result, never terminal evidence.
            if unsafe { libc::kill(self.pid, libc::SIGKILL) } != 0 {
                return Err(io::Error::last_os_error());
            }
        }
        self.wait_until_deadline()
    }
}

impl Drop for ForkChild {
    fn drop(&mut self) {
        if matches!(self.observation, ChildObservation::Owned) {
            // No blocking wait and no additional grace. Any missing terminal
            // observation remains a failed/unknown fixture, not a clean exit.
            let _ = self.terminate_and_reap_until_deadline();
        }
    }
}

#[test]
fn fork_copy_drop_does_not_unlock_original_handoff_owner() -> anyhow::Result<()> {
    let root = TempDir::new()?;
    let path = root.path().join("handoff");
    let original = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&path)?;
    let owner = LockedHandoffFile::acquire(original)?;
    // This new fixture has one stricter observation/cleanup window. It does not
    // add time to the existing journal cases or to the test runner's deadline.
    let deadline = Instant::now() + Duration::from_secs(2);
    // The child branch drops only this File + numeric-PID guard. It never
    // unwinds the Rust test stack, logs, allocates, or drops the TempDir.
    let pid = unsafe { libc::fork() };
    if pid == 0 {
        drop(owner);
        unsafe { libc::_exit(0) };
    }
    if pid == -1 {
        return Err(io::Error::last_os_error().into());
    }
    let mut child = ForkChild {
        pid,
        observation: ChildObservation::Owned,
        deadline,
        termination_requested: false,
    };
    let status = match child.wait_until_deadline() {
        Ok(status) => status,
        Err(error) => {
            let cleanup = child.terminate_and_reap_until_deadline();
            anyhow::bail!(
                "forked guard child wait failed: {error}; cleanup observation: {cleanup:?}"
            );
        }
    };
    assert!(libc::WIFEXITED(status));
    assert_eq!(libc::WEXITSTATUS(status), 0);
    let contender = OpenOptions::new().read(true).write(true).open(&path)?;
    assert!(matches!(
        contender.try_lock(),
        Err(TryLockError::WouldBlock)
    ));
    drop(owner);
    contender.try_lock()?;
    contender.unlock()?;
    Ok(())
}
