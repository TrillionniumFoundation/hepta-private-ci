//! Actual dedicated-UID peers for admission and idle service lifetime tests.
//! These endpoints never return role evidence. A read on a role socket must be
//! EOF; any dispatched request fails the fixture instead of supplying a receipt.

use std::fs::File;
use std::io;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;
use std::os::unix::process::CommandExt;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use crate::AgentdRootAuthorityPeer;
use pretty_assertions::assert_eq;

pub(super) const PEER_UID: u32 = 60001;
const CHILD: &str = "authority_host_service::resident::authority::tests::provider_transport::process::resident_role_peer_process_child";
const IO_WINDOW: Duration = Duration::from_secs(5);

pub(super) fn process(pid: u32) -> anyhow::Result<AgentdRootAuthorityPeer> {
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    let process_start_ticks = stat
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .ok_or_else(|| anyhow::anyhow!("actual process start field"))?
        .parse()?;
    Ok(AgentdRootAuthorityPeer {
        pid,
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
            .trim()
            .to_string(),
        process_start_ticks,
    })
}

pub(super) fn pin(pid: u32) -> anyhow::Result<OwnedFd> {
    // SAFETY: pidfd_open returns a new descriptor for this observed live pid.
    let number = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    anyhow::ensure!(number >= 0, "{}", io::Error::last_os_error());
    // SAFETY: the successful syscall transferred exactly one new descriptor.
    Ok(unsafe { OwnedFd::from_raw_fd(i32::try_from(number)?) })
}

pub(super) struct PeerProcess {
    child: Option<Child>,
    control: UnixDatagram,
    pub(super) peer: AgentdRootAuthorityPeer,
    streams: Vec<UnixStream>,
}

impl PeerProcess {
    pub(super) fn start() -> anyhow::Result<Self> {
        // SAFETY: observe the explicit Root test parent's actual credentials.
        assert_eq!(unsafe { (libc::getuid(), libc::geteuid()) }, (0, 0));
        let (control, inherited_control) = UnixDatagram::pair()?;
        control.set_read_timeout(Some(IO_WINDOW))?;
        control.set_write_timeout(Some(IO_WINDOW))?;
        let executable = File::open(std::env::current_exe()?)?;
        let inherited = [inherited_control.as_raw_fd(), executable.as_raw_fd()];
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
                CHILD,
                "--ignored",
                "--nocapture",
                "--test-threads=1",
            ])
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env(
                "HEPTA_RESIDENT_ROLE_PEER_FD",
                inherited_control.as_raw_fd().to_string(),
            )
            .current_dir("/")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        // SAFETY: the post-fork closure only applies fcntl to these two live
        // inherited FDs. setpriv performs the actual credential drop at exec.
        unsafe {
            command.pre_exec(move || {
                for descriptor in inherited {
                    let flags = libc::fcntl(descriptor, libc::F_GETFD);
                    if flags < 0
                        || libc::fcntl(descriptor, libc::F_SETFD, flags & !libc::FD_CLOEXEC) < 0
                    {
                        return Err(io::Error::last_os_error());
                    }
                }
                Ok(())
            });
        }
        let mut child = command.spawn()?;
        drop(inherited_control);
        let peer = match process(child.id()) {
            Ok(peer) => peer,
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
        };
        // From this point every error is guarded by Drop: no orphan role peer.
        let mut observed = Self {
            peer,
            child: Some(child),
            control,
            streams: Vec::new(),
        };
        let mut path = [0_u8; 1024];
        let count = observed.control.recv(&mut path)?;
        let path = std::str::from_utf8(&path[..count])?;
        anyhow::ensure!(path.starts_with("/tmp/") && path.ends_with("/roles.sock"));
        for _ in 0..11 {
            let stream = UnixStream::connect(path)?;
            assert_peer(&stream, PEER_UID, observed.peer.pid)?;
            observed.streams.push(stream);
        }
        observed.expect(b"eleven-original-connections")?;
        Ok(observed)
    }

    pub(super) fn take_streams(&mut self) -> anyhow::Result<([UnixStream; 10], UnixStream)> {
        let consumer = self
            .streams
            .pop()
            .ok_or_else(|| anyhow::anyhow!("held A connection"))?;
        let streams = std::mem::take(&mut self.streams)
            .try_into()
            .map_err(|_: Vec<UnixStream>| anyhow::anyhow!("exact ten held role connections"))?;
        Ok((streams, consumer))
    }

    fn expect(&self, expected: &[u8]) -> anyhow::Result<()> {
        let mut response = [0_u8; 128];
        let count = self.control.recv(&mut response)?;
        assert_eq!(&response[..count], expected);
        Ok(())
    }

    pub(super) fn close_a(&self) -> anyhow::Result<()> {
        self.control.send(b"close-original-A")?;
        self.expect(b"original-A-closed")
    }

    pub(super) fn finish(mut self) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.streams.is_empty(),
            "all original parent endpoints consumed"
        );
        self.control.send(b"assert-no-role-dispatch-and-exit")?;
        let end = Instant::now() + IO_WINDOW;
        let finished = loop {
            if self
                .child
                .as_mut()
                .ok_or_else(|| anyhow::anyhow!("original child"))?
                .try_wait()?
                .is_some()
            {
                break true;
            }
            if Instant::now() >= end {
                break false;
            }
            std::thread::sleep(Duration::from_millis(2));
        };
        if !finished {
            anyhow::bail!("bounded original peer join did not finish");
        }
        let child = self
            .child
            .take()
            .ok_or_else(|| anyhow::anyhow!("original child"))?;
        let output = child.wait_with_output()?;
        anyhow::ensure!(
            output.status.success(),
            "{}{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        let stdout = String::from_utf8(output.stdout)?;
        anyhow::ensure!(
            stdout.contains("RESIDENT_IDLE_PEER uid=60001 role_dispatches=0 role_eofs=10"),
            "{stdout}"
        );
        Ok(())
    }
}

impl Drop for PeerProcess {
    fn drop(&mut self) {
        self.streams.clear();
        if let Some(mut child) = self.child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn assert_peer(stream: &UnixStream, uid: u32, pid: u32) -> anyhow::Result<()> {
    let mut credentials = libc::ucred {
        pid: 0,
        uid: u32::MAX,
        gid: u32::MAX,
    };
    let mut size = std::mem::size_of_val(&credentials) as libc::socklen_t;
    // SAFETY: getsockopt writes exactly the initialized ucred buffer.
    anyhow::ensure!(
        unsafe {
            libc::getsockopt(
                stream.as_raw_fd(),
                libc::SOL_SOCKET,
                libc::SO_PEERCRED,
                (&mut credentials as *mut libc::ucred).cast(),
                &mut size,
            )
        } == 0,
        "{}",
        io::Error::last_os_error()
    );
    assert_eq!(size as usize, std::mem::size_of::<libc::ucred>());
    assert_eq!(
        (credentials.uid, credentials.pid),
        (uid, i32::try_from(pid)?)
    );
    Ok(())
}

#[test]
#[ignore = "only the explicit Root provider parent supplies the inherited control descriptor"]
fn resident_role_peer_process_child() -> anyhow::Result<()> {
    crate::authority_host_runtime::verify_process_credentials(
        std::process::id(),
        PEER_UID,
        PEER_UID,
    )?;
    let number: i32 = std::env::var("HEPTA_RESIDENT_ROLE_PEER_FD")?.parse()?;
    anyhow::ensure!(number >= 3);
    // SAFETY: the parent transferred exclusive ownership through exec once.
    let control = unsafe { UnixDatagram::from_raw_fd(number) };
    control.set_read_timeout(Some(IO_WINDOW))?;
    control.set_write_timeout(Some(IO_WINDOW))?;
    let directory = tempfile::tempdir_in("/tmp")?;
    let path = directory.path().join("roles.sock");
    let listener = UnixListener::bind(&path)?;
    listener.set_nonblocking(true)?;
    control.send(path.as_os_str().as_encoded_bytes())?;
    let end = Instant::now() + IO_WINDOW;
    let mut streams = Vec::new();
    while streams.len() < 11 {
        match listener.accept() {
            Ok((stream, _)) => streams.push(stream),
            Err(error) if error.kind() == io::ErrorKind::WouldBlock && Instant::now() < end => {
                std::thread::sleep(Duration::from_millis(1))
            }
            Err(error) => return Err(error.into()),
        }
    }
    let mut consumer = streams.pop();
    control.send(b"eleven-original-connections")?;
    loop {
        let mut request = [0_u8; 128];
        let count = control.recv(&mut request)?;
        match &request[..count] {
            b"close-original-A" => {
                anyhow::ensure!(consumer.take().is_some(), "A close is one-shot");
                control.send(b"original-A-closed")?;
            }
            b"assert-no-role-dispatch-and-exit" => break,
            _ => anyhow::bail!("unregistered idle peer command"),
        }
    }
    drop(consumer);
    let end = Instant::now() + IO_WINDOW;
    for mut stream in streams {
        let remaining = end
            .checked_duration_since(Instant::now())
            .ok_or_else(|| anyhow::anyhow!("bounded role EOF observation"))?;
        stream.set_read_timeout(Some(remaining))?;
        assert_eq!(
            stream.read(&mut [0])?,
            0,
            "idle test must never dispatch a role command"
        );
    }
    println!("RESIDENT_IDLE_PEER uid=60001 role_dispatches=0 role_eofs=10");
    Ok(())
}
