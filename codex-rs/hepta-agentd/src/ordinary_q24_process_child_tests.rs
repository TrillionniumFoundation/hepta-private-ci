//! Actual child lifetimes for the ordinary daemon/Root tests. This module
//! proves process facts only; successful exit is never a learning receipt.

use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::fd::RawFd;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::process::Child;
use std::process::Command;
use std::process::ExitStatus;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct OriginalProcessLifetime {
    pub(crate) pid: u32,
    pub(crate) start_ticks: u64,
    pub(crate) boot_id: String,
}

/// All inherited descriptors are originals supplied to this child. A Root
/// service additionally replaces its reserved descriptor with its own kernel
/// pidfd before exec; it never receives its parent's pidfd as its identity.
#[derive(Default)]
pub(crate) struct OriginalChildDescriptors {
    pub(crate) inherited: Vec<RawFd>,
    pub(crate) own_pidfd_slot: Option<RawFd>,
}

pub(crate) struct OriginalChild {
    child: Option<Child>,
    lifetime: OriginalProcessLifetime,
    pidfd: Option<OwnedFd>,
    stdout: File,
    stderr: File,
}

/// Nonserializable, nonconstructible outside this module. Both actual wait
/// success and the original kernel pidfd's exit observation are required.
pub(crate) struct ExitedOriginalProcess {
    lifetime: OriginalProcessLifetime,
    pidfd: OwnedFd,
    status: ExitStatus,
    stdout: File,
    stderr: File,
}

impl OriginalChild {
    pub(crate) fn spawn(
        command: &mut Command,
        descriptors: OriginalChildDescriptors,
    ) -> anyhow::Result<Self> {
        let mut inherited = descriptors.inherited;
        if let Some(fd) = descriptors.own_pidfd_slot {
            inherited.push(fd);
        }
        inherited.sort_unstable();
        anyhow::ensure!(
            inherited.iter().all(|fd| *fd >= 3)
                && inherited.windows(2).all(|pair| pair[0] != pair[1]),
            "original inherited descriptors must be distinct and nonstandard"
        );
        let stdout = tempfile::tempfile()?;
        let stderr = tempfile::tempfile()?;
        command
            .stdout(stdout.try_clone()?)
            .stderr(stderr.try_clone()?);
        // SAFETY: the child-only closure performs only async-signal-safe kernel
        // calls on already allocated descriptor data. No credential, signer,
        // authority record or test result is synthesized in this boundary.
        unsafe {
            command.pre_exec(move || {
                if let Some(slot) = descriptors.own_pidfd_slot {
                    let fd = libc::syscall(libc::SYS_pidfd_open, libc::getpid(), 0) as i32;
                    if fd < 0 {
                        return Err(io::Error::last_os_error());
                    }
                    if fd != slot {
                        let result = libc::dup2(fd, slot);
                        let error = io::Error::last_os_error();
                        libc::close(fd);
                        if result < 0 {
                            return Err(error);
                        }
                    }
                }
                for fd in &inherited {
                    let flags = libc::fcntl(*fd, libc::F_GETFD);
                    if flags < 0 || libc::fcntl(*fd, libc::F_SETFD, flags & !libc::FD_CLOEXEC) < 0 {
                        return Err(io::Error::last_os_error());
                    }
                }
                Ok(())
            });
        }
        let mut child = command.spawn()?;
        let captured = capture(&child);
        let (lifetime, pidfd) = match captured {
            Ok(value) => value,
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
        };
        Ok(Self {
            child: Some(child),
            lifetime,
            pidfd: Some(pidfd),
            stdout,
            stderr,
        })
    }

    pub(crate) fn lifetime(&self) -> &OriginalProcessLifetime {
        &self.lifetime
    }

    pub(crate) fn original_pidfd(&self) -> anyhow::Result<OwnedFd> {
        self.require_live()?;
        Ok(self
            .pidfd
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("original child pidfd consumed"))?
            .try_clone()?)
    }

    pub(crate) fn require_live(&self) -> anyhow::Result<()> {
        let pin = self
            .pidfd
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("original child pidfd consumed"))?;
        anyhow::ensure!(
            !exited(pin)? && lifetime(self.lifetime.pid)? == self.lifetime,
            "original child lifetime is no longer live"
        );
        Ok(())
    }

    pub(crate) fn request_original_shutdown(&self) -> anyhow::Result<()> {
        self.require_live()?;
        let pin = self
            .pidfd
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("original child pidfd consumed"))?;
        // SAFETY: the signal is sent to the retained actual kernel lifetime,
        // never to a numeric PID that could have been reused. Production owns
        // the SIGTERM handler and must perform its normal supervised drain.
        anyhow::ensure!(
            unsafe {
                libc::syscall(
                    libc::SYS_pidfd_send_signal,
                    pin.as_raw_fd(),
                    libc::SIGTERM,
                    std::ptr::null::<libc::siginfo_t>(),
                    0,
                )
            } == 0,
            "{}",
            io::Error::last_os_error()
        );
        Ok(())
    }

    pub(crate) fn wait_success_until(
        mut self,
        end: Instant,
    ) -> anyhow::Result<ExitedOriginalProcess> {
        loop {
            anyhow::ensure!(Instant::now() < end, "original child exit deadline");
            let child = self
                .child
                .as_mut()
                .ok_or_else(|| anyhow::anyhow!("original child already reaped"))?;
            if let Some(status) = child.try_wait()? {
                self.child.take();
                let pidfd = self
                    .pidfd
                    .take()
                    .ok_or_else(|| anyhow::anyhow!("original child pidfd absent"))?;
                anyhow::ensure!(
                    status.success() && exited(&pidfd)?,
                    "original child {:?} did not complete successfully: {status}; {}",
                    self.lifetime,
                    self.output()?
                );
                anyhow::ensure!(Instant::now() < end, "original child exit observed late");
                return Ok(ExitedOriginalProcess {
                    lifetime: self.lifetime.clone(),
                    pidfd,
                    status,
                    stdout: self.stdout.try_clone()?,
                    stderr: self.stderr.try_clone()?,
                });
            }
            anyhow::ensure!(Instant::now() < end, "original child exit deadline");
            std::thread::sleep(Duration::from_millis(5));
        }
    }

    fn output(&self) -> io::Result<String> {
        let read = |file: &File| -> io::Result<String> {
            let mut file = file.try_clone()?;
            file.rewind()?;
            let mut bytes = Vec::new();
            file.take(32768).read_to_end(&mut bytes)?;
            Ok(String::from_utf8_lossy(&bytes).into_owned())
        };
        Ok(format!(
            "stdout={} stderr={}",
            read(&self.stdout)?,
            read(&self.stderr)?
        ))
    }
}

impl ExitedOriginalProcess {
    pub(crate) fn require_dead(&self) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.status.success() && exited(&self.pidfd)?,
            "original successful child exit is unavailable"
        );
        Ok(())
    }

    pub(crate) fn require_distinct_live(&self, child: &OriginalChild) -> anyhow::Result<()> {
        self.require_dead()?;
        child.require_live()?;
        anyhow::ensure!(
            self.lifetime != *child.lifetime(),
            "recovery reused the original process lifetime"
        );
        Ok(())
    }

    pub(crate) fn lifetime(&self) -> &OriginalProcessLifetime {
        &self.lifetime
    }

    /// Archive both complete original files or refuse their explicit bound.
    /// The short diagnostic printed on errors is not substituted for raw logs.
    pub(crate) fn archive_original_logs(&self, directory: &Path) -> anyhow::Result<()> {
        self.require_dead()?;
        for (name, source) in [("stdout.log", &self.stdout), ("stderr.log", &self.stderr)] {
            let length = source.metadata()?.len();
            anyhow::ensure!(length <= 16 * 1024 * 1024, "original child log bound");
            let mut source = source.try_clone()?;
            source.rewind()?;
            let mut target = OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
                .open(directory.join(name))?;
            anyhow::ensure!(
                io::copy(&mut Read::by_ref(&mut source).take(length + 1), &mut target)? == length
                    && source.metadata()?.len() == length,
                "original child log changed while archiving"
            );
            target.sync_all()?;
        }
        Ok(())
    }
}

impl Drop for OriginalChild {
    fn drop(&mut self) {
        if let Some(mut child) = self.child.take() {
            let _ = child.kill();
            let status = child.wait();
            eprintln!(
                "ORDINARY_Q24_CHILD_CLEANUP lifetime={:?} status={status:?} {}",
                self.lifetime,
                self.output().unwrap_or_else(|error| error.to_string())
            );
        }
    }
}

fn capture(child: &Child) -> anyhow::Result<(OriginalProcessLifetime, OwnedFd)> {
    let before = lifetime(child.id())?;
    // SAFETY: pidfd_open refers to this actual live Child; ownership is taken
    // only after success and remains tied to its full kernel lifetime.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, child.id(), 0) };
    anyhow::ensure!(fd >= 0, "{}", io::Error::last_os_error());
    // SAFETY: this is the fresh, uniquely owned descriptor returned above.
    let pin = unsafe { OwnedFd::from_raw_fd(i32::try_from(fd)?) };
    anyhow::ensure!(
        lifetime(child.id())? == before && !exited(&pin)?,
        "child exited or changed during actual lifetime capture"
    );
    Ok((before, pin))
}

fn lifetime(pid: u32) -> anyhow::Result<OriginalProcessLifetime> {
    let mut stat = String::new();
    File::open(format!("/proc/{pid}/stat"))?
        .take(4097)
        .read_to_string(&mut stat)?;
    anyhow::ensure!(stat.len() <= 4096, "bounded actual process stat required");
    let close = stat
        .rfind(')')
        .ok_or_else(|| anyhow::anyhow!("actual process stat is malformed"))?;
    let start_ticks = stat[close + 1..]
        .split_whitespace()
        .nth(19)
        .ok_or_else(|| anyhow::anyhow!("actual process start ticks absent"))?
        .parse()?;
    let boot_id = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
        .trim()
        .to_owned();
    anyhow::ensure!(boot_id.len() == 36, "actual boot identity absent");
    Ok(OriginalProcessLifetime {
        pid,
        start_ticks,
        boot_id,
    })
}

fn exited(pidfd: &OwnedFd) -> io::Result<bool> {
    let mut descriptor = libc::pollfd {
        fd: pidfd.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };
    // SAFETY: poll reads one live descriptor without blocking or mutation.
    let result = unsafe { libc::poll(&mut descriptor, 1, 0) };
    if result < 0 {
        return Err(io::Error::last_os_error());
    }
    if descriptor.revents & (libc::POLLNVAL | libc::POLLERR) != 0 {
        return Err(io::Error::other("original pidfd unavailable"));
    }
    Ok(result > 0 && descriptor.revents & libc::POLLIN != 0)
}

#[test]
fn ordinary_q24_process_proof_requires_reaped_success_and_distinct_live_lifetime()
-> anyhow::Result<()> {
    let spawn = || {
        OriginalChild::spawn(
            Command::new("/bin/cat").stdin(Stdio::piped()),
            OriginalChildDescriptors::default(),
        )
    };
    let mut first = spawn()?;
    let old = first.lifetime().clone();
    first.require_live()?;
    let _ = first.original_pidfd()?;
    first.child.as_mut().and_then(|child| child.stdin.take());
    let exited = first.wait_success_until(Instant::now() + Duration::from_secs(5))?;
    exited.require_dead()?;
    pretty_assertions::assert_eq!(exited.lifetime(), &old);
    let logs = tempfile::tempdir()?;
    exited.archive_original_logs(logs.path())?;
    pretty_assertions::assert_eq!(std::fs::read(logs.path().join("stdout.log"))?, b"");
    pretty_assertions::assert_eq!(std::fs::read(logs.path().join("stderr.log"))?, b"");
    let mut second = spawn()?;
    exited.require_distinct_live(&second)?;
    second.child.as_mut().and_then(|child| child.stdin.take());
    second
        .wait_success_until(Instant::now() + Duration::from_secs(5))?
        .require_dead()?;
    Ok(())
}

#[test]
fn ordinary_q24_process_failure_cannot_make_successful_exit_proof() -> anyhow::Result<()> {
    let mut command = Command::new("/bin/sh");
    command
        .args(["-c", "read input; exit 7"])
        .stdin(Stdio::piped());
    let mut child = OriginalChild::spawn(&mut command, OriginalChildDescriptors::default())?;
    let stdin = child
        .child
        .as_mut()
        .and_then(|child| child.stdin.as_mut())
        .ok_or_else(|| anyhow::anyhow!("original child stdin absent"))?;
    stdin.write_all(b"finish\n")?;
    assert!(
        child
            .wait_success_until(Instant::now() + Duration::from_secs(5))
            .is_err()
    );
    Ok(())
}

#[test]
fn ordinary_q24_process_exit_observed_after_original_deadline_cannot_make_proof()
-> anyhow::Result<()> {
    let mut child = OriginalChild::spawn(
        Command::new("/bin/cat").stdin(Stdio::piped()),
        OriginalChildDescriptors::default(),
    )?;
    let expired = Instant::now();
    let actual = child
        .child
        .as_mut()
        .ok_or_else(|| anyhow::anyhow!("actual child absent"))?;
    actual.stdin.take();
    anyhow::ensure!(actual.wait()?.success(), "actual child must have exited");
    assert!(child.wait_success_until(expired).is_err());
    Ok(())
}
