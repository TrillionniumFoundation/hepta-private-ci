//! Owned child and byte-preserving file observations for the Root publication component.

use super::*;
use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::process::CommandExt;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;

pub(super) fn write_json(path: &Path, value: &impl serde::Serialize) -> anyhow::Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(&serde_json::to_vec(value)?)?;
    file.sync_all()?;
    File::open(
        path.parent()
            .ok_or_else(|| anyhow::anyhow!("protected parent required"))?,
    )?
    .sync_all()?;
    Ok(())
}

pub(super) fn pidfd(pid: u32) -> anyhow::Result<OwnedFd> {
    // SAFETY: pidfd_open creates one new owned pin for the retained parent or child.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    anyhow::ensure!(fd >= 0, "{}", io::Error::last_os_error());
    // SAFETY: the successful syscall transfers exactly this one descriptor.
    Ok(unsafe { OwnedFd::from_raw_fd(fd as i32) })
}

pub(super) fn start_ticks(pid: u32) -> anyhow::Result<u64> {
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    Ok(stat
        .rsplit_once(") ")
        .and_then(|(_, rest)| rest.split_whitespace().nth(19))
        .ok_or_else(|| anyhow::anyhow!("original process start required"))?
        .parse()?)
}

#[derive(Debug, Eq, PartialEq)]
pub(super) struct ProtectedFile {
    device: u64,
    inode: u64,
    owner: u32,
    mode: u32,
    bytes: Vec<u8>,
}

pub(super) fn protected_files(path: &Path) -> anyhow::Result<BTreeMap<PathBuf, ProtectedFile>> {
    std::fs::read_dir(path)?
        .map(|entry| {
            let path = entry?.path();
            let mut file = File::open(&path)?;
            let metadata = file.metadata()?;
            let mut bytes = Vec::new();
            file.read_to_end(&mut bytes)?;
            Ok((
                path,
                ProtectedFile {
                    device: metadata.dev(),
                    inode: metadata.ino(),
                    owner: metadata.uid(),
                    mode: metadata.mode(),
                    bytes,
                },
            ))
        })
        .collect()
}

pub(super) struct ChildOwner {
    child: Option<Child>,
    deadline: Instant,
}

impl ChildOwner {
    pub(super) fn spawn(receive: UnixDatagram, state: &Path) -> anyhow::Result<Self> {
        let executable = File::open(std::env::current_exe()?)?;
        let inherited = [receive.as_raw_fd(), executable.as_raw_fd()];
        let mut command = Command::new("/usr/bin/setpriv");
        command
            .args([
                "--reuid=60001",
                "--regid=60001",
                "--clear-groups",
                "--no-new-privs",
                "--inh-caps=-all",
                "--ambient-caps=-all",
                "--bounding-set=-all",
            ])
            .arg(format!("/proc/self/fd/{}", executable.as_raw_fd()))
            .args([
                "--exact",
                CHILD_TEST,
                "--ignored",
                "--nocapture",
                "--test-threads=1",
            ])
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env(
                "HEPTA_LEARNING_SERVICE_CHILD_FD",
                receive.as_raw_fd().to_string(),
            )
            .env(
                "HEPTA_LEARNING_SERVICE_ROOT_PID",
                std::process::id().to_string(),
            )
            .env("HEPTA_LEARNING_SERVICE_STATE", state)
            .current_dir("/")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        // SAFETY: after fork only async-signal-safe fcntl touches the two retained
        // descriptors. setpriv performs the real credential/capability transition.
        unsafe {
            command.pre_exec(move || {
                for fd in inherited {
                    let flags = libc::fcntl(fd, libc::F_GETFD);
                    if flags < 0 || libc::fcntl(fd, libc::F_SETFD, flags & !libc::FD_CLOEXEC) < 0 {
                        return Err(io::Error::last_os_error());
                    }
                }
                Ok(())
            });
        }
        let deadline = Instant::now() + Duration::from_secs(60);
        let child = command.spawn()?;
        drop(receive);
        Ok(Self {
            child: Some(child),
            deadline,
        })
    }

    pub(super) fn pid(&self) -> anyhow::Result<u32> {
        self.child
            .as_ref()
            .map(Child::id)
            .ok_or_else(|| anyhow::anyhow!("retained original child required"))
    }

    pub(super) fn release(&mut self) -> anyhow::Result<()> {
        self.child
            .as_mut()
            .and_then(|child| child.stdin.as_mut())
            .ok_or_else(|| anyhow::anyhow!("original child stdin required"))?
            .write_all(&[1])?;
        Ok(())
    }

    pub(super) fn finish(mut self) -> anyhow::Result<String> {
        loop {
            if self
                .child
                .as_mut()
                .ok_or_else(|| anyhow::anyhow!("retained original child required"))?
                .try_wait()?
                .is_some()
            {
                break;
            }
            anyhow::ensure!(
                Instant::now() < self.deadline,
                "dedicated child sixty-second deadline"
            );
            std::thread::sleep(Duration::from_millis(5));
        }
        let output = self
            .child
            .take()
            .ok_or_else(|| anyhow::anyhow!("finished original child required"))?
            .wait_with_output()?;
        anyhow::ensure!(
            output.status.success(),
            "dedicated child failed: {}{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        Ok(String::from_utf8(output.stdout)?)
    }
}

impl Drop for ChildOwner {
    fn drop(&mut self) {
        if let Some(child) = &mut self.child {
            if !matches!(child.try_wait(), Ok(Some(_))) {
                let _ = child.kill();
            }
            let _ = child.wait();
        }
    }
}

