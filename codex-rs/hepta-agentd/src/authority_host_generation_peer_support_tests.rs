//! Actual non-Root process identity for host registration. The process holds
//! stdin until EOF; it produces no owner protocol, task result or success proof.

use std::os::fd::FromRawFd as _;
use std::os::fd::OwnedFd;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use crate::authority_host_config::HostAuthorityRegisteredIdentity;
use crate::authority_host_config::HostAuthorityRegistration;

pub(super) struct OriginalRegistrationPeer {
    child: Option<Child>,
    pidfd: OwnedFd,
    pub(super) registration: HostAuthorityRegistration,
}

impl OriginalRegistrationPeer {
    pub(super) fn start(identity: HostAuthorityRegisteredIdentity) -> anyhow::Result<Self> {
        let boot_id = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim().to_owned();
        let mut child = Command::new("/usr/bin/setpriv")
            .args([
                "--reuid=60001", "--regid=60001", "--clear-groups", "--no-new-privs",
                "--inh-caps=-all", "--ambient-caps=-all", "--bounding-set=-all",
                "/usr/bin/cat",
            ])
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()?;
        // SAFETY: pidfd_open takes the actual child PID and no memory pointers.
        let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, child.id(), 0) };
        if raw < 0 {
            let error = std::io::Error::last_os_error();
            let _ = child.kill();
            let end = Instant::now() + Duration::from_secs(5);
            while Instant::now() < end && child.try_wait().ok().flatten().is_none() {
                std::thread::sleep(Duration::from_millis(5));
            }
            return Err(error.into());
        }
        // SAFETY: pidfd_open returned this one fresh descriptor.
        let pidfd = unsafe { OwnedFd::from_raw_fd(raw as i32) };
        let registration = HostAuthorityRegistration {
            schema_version: 1,
            peer_pid: child.id(),
            boot_id,
            process_start_ticks: 0,
            checkpoint_owner_agent_id: identity.agent_id.clone(),
            registered_identity: identity,
            publisher_epoch: 1,
        };
        let mut owner = Self { child: Some(child), pidfd, registration };
        let end = Instant::now() + Duration::from_secs(5);
        loop {
            let pid = owner.registration.peer_pid;
            let status = std::fs::read_to_string(format!("/proc/{pid}/status"))?;
            if status.contains("Uid:\t60001\t60001\t60001\t60001")
                && status.contains("NoNewPrivs:\t1")
            {
                break;
            }
            anyhow::ensure!(Instant::now() < end, "actual non-Root process did not become ready");
            anyhow::ensure!(owner.child.as_mut().unwrap().try_wait()?.is_none(), "actual peer exited");
            std::thread::sleep(Duration::from_millis(5));
        }
        let stat = std::fs::read_to_string(format!("/proc/{}/stat", owner.registration.peer_pid))?;
        owner.registration.process_start_ticks = stat.rsplit_once(") ")
            .ok_or_else(|| anyhow::anyhow!("actual process stat is malformed"))?.1
            .split_whitespace().nth(19)
            .ok_or_else(|| anyhow::anyhow!("actual process stat has no start time"))?.parse()?;
        Ok(owner)
    }

    pub(super) fn pidfd(&self) -> anyhow::Result<OwnedFd> {
        Ok(self.pidfd.try_clone()?)
    }

    pub(super) fn finish(mut self) -> anyhow::Result<()> {
        let child = self.child.as_mut().ok_or_else(|| anyhow::anyhow!("peer already reaped"))?;
        drop(child.stdin.take());
        let end = Instant::now() + Duration::from_secs(5);
        loop {
            if let Some(status) = child.try_wait()? {
                anyhow::ensure!(status.success(), "original process returned {status}");
                self.child.take();
                return Ok(());
            }
            anyhow::ensure!(Instant::now() < end, "original process EOF termination is unknown");
            std::thread::sleep(Duration::from_millis(5));
        }
    }
}

impl Drop for OriginalRegistrationPeer {
    fn drop(&mut self) {
        let Some(child) = self.child.as_mut() else { return };
        drop(child.stdin.take());
        if child.try_wait().ok().flatten().is_some() {
            return;
        }
        let _ = child.kill();
        let end = Instant::now() + Duration::from_secs(5);
        while Instant::now() < end {
            if child.try_wait().ok().flatten().is_some() {
                return;
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        // This bounded error cleanup does not claim a wait/reap succeeded.
    }
}
