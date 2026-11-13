//! Test-only actual dedicated-UID processes. Control datagrams carry fixture
//! metadata, never role receipts, signatures, typed authority, or fake replies.
//! Mount under the existing Linux Root test module; this file adds no test case.

use std::fs::File;
use std::io;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::fd::RawFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::process::Child;
use std::process::ChildStderr;
use std::process::ChildStdout;
use std::process::Command;
use std::process::ExitStatus;
use std::process::Stdio;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use crate::AgentdRootAuthorityPeer;

pub(super) const TRAINER_MODEL_UID: u32 = 60001;
pub(super) const OTHER_OWNER_UID: u32 = 60002;
const IO_WINDOW: Duration = Duration::from_secs(5);
const CLEANUP_WINDOW: Duration = Duration::from_secs(5);
const CONTROL_LIMIT: usize = 64 * 1024;
const CAPTURE_LIMIT: usize = 1024 * 1024;
const CONTROL_ENV: &str = "HEPTA_RESIDENT_PAIR_CONTROL_FD";
const EXECUTABLE_ENV: &str = "HEPTA_RESIDENT_PAIR_EXECUTABLE_FD";
const UID_ENV: &str = "HEPTA_RESIDENT_PAIR_UID";
const PARENT_ENV: &str = "HEPTA_RESIDENT_PAIR_PARENT_PID";
const READY: &[u8] = b"HEPTA_RESIDENT_PAIR_READY_V1";
static CHILD_CONTROL_TAKEN: AtomicBool = AtomicBool::new(false);

fn allowed_uid(uid: u32) -> anyhow::Result<()> {
    anyhow::ensure!(matches!(uid, TRAINER_MODEL_UID | OTHER_OWNER_UID), "exact two dedicated fixture UIDs");
    Ok(())
}

fn observed_process(pid: u32) -> anyhow::Result<AgentdRootAuthorityPeer> {
    anyhow::ensure!(pid > 0 && pid <= i32::MAX as u32, "actual process ID");
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    let process_start_ticks = stat.rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .ok_or_else(|| anyhow::anyhow!("actual process start field"))?.parse::<u64>()?;
    anyhow::ensure!(process_start_ticks > 0, "nonzero actual process start");
    let boot_id = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim().to_string();
    anyhow::ensure!(!boot_id.is_empty(), "actual boot identity");
    Ok(AgentdRootAuthorityPeer { pid, boot_id, process_start_ticks })
}

fn pin(pid: u32) -> anyhow::Result<OwnedFd> {
    // SAFETY: pidfd_open returns a new descriptor for this actual child PID.
    let number = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    anyhow::ensure!(number >= 0, "{}", io::Error::last_os_error());
    // SAFETY: the successful syscall transferred exactly one new descriptor.
    Ok(unsafe { OwnedFd::from_raw_fd(i32::try_from(number)?) })
}

fn set_nonblocking(descriptor: RawFd) -> io::Result<()> {
    // SAFETY: fcntl borrows a live descriptor and changes only its status flags.
    let flags = unsafe { libc::fcntl(descriptor, libc::F_GETFL) };
    if flags < 0 || unsafe { libc::fcntl(descriptor, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

fn set_cloexec(descriptor: RawFd) -> io::Result<()> {
    // SAFETY: fcntl borrows the one already validated inherited descriptor.
    let flags = unsafe { libc::fcntl(descriptor, libc::F_GETFD) };
    if flags < 0 || unsafe { libc::fcntl(descriptor, libc::F_SETFD, flags | libc::FD_CLOEXEC) } < 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

fn poll_until(descriptors: &mut [libc::pollfd], end: Instant) -> anyhow::Result<()> {
    let remaining = end.checked_duration_since(Instant::now())
        .ok_or_else(|| anyhow::anyhow!("bounded fixture observation expired"))?;
    let milliseconds = i32::try_from(remaining.as_millis().clamp(1, 20))?;
    // SAFETY: poll borrows this initialized contiguous array for the call only.
    let ready = unsafe { libc::poll(descriptors.as_mut_ptr(), descriptors.len() as libc::nfds_t, milliseconds) };
    if ready < 0 {
        let error = io::Error::last_os_error();
        if error.kind() != io::ErrorKind::Interrupted { return Err(error.into()); }
    }
    anyhow::ensure!(!descriptors.iter().any(|entry| entry.revents & libc::POLLNVAL != 0), "invalid owned descriptor");
    Ok(())
}

fn within_window(end: Instant) -> anyhow::Result<()> {
    anyhow::ensure!(Instant::now() < end, "bounded fixture observation expired");
    Ok(())
}

fn receive_datagram(control: &UnixDatagram) -> io::Result<Vec<u8>> {
    let mut payload = vec![0_u8; CONTROL_LIMIT + 1];
    // SAFETY: recv writes at most payload.len() bytes to this initialized buffer.
    // MSG_TRUNC reports the original datagram length on Linux, so oversized data
    // cannot be mistaken for a valid truncated metadata packet.
    let count = unsafe { libc::recv(control.as_raw_fd(), payload.as_mut_ptr().cast(), payload.len(), libc::MSG_TRUNC) };
    if count < 0 { return Err(io::Error::last_os_error()); }
    let count = usize::try_from(count).map_err(io::Error::other)?;
    if count > CONTROL_LIMIT { return Err(io::Error::other("fixture control datagram exceeds 64 KiB")); }
    payload.truncate(count);
    Ok(payload)
}

fn ready_message(uid: u32, pid: u32) -> Vec<u8> {
    let mut bytes = READY.to_vec();
    bytes.extend_from_slice(&uid.to_be_bytes());
    bytes.extend_from_slice(&pid.to_be_bytes());
    bytes
}

fn credentials(stream: RawFd) -> anyhow::Result<libc::ucred> {
    let mut observed = libc::ucred { pid: 0, uid: u32::MAX, gid: u32::MAX };
    let mut size = std::mem::size_of_val(&observed) as libc::socklen_t;
    // SAFETY: getsockopt writes into the initialized ucred buffer of the stated size.
    let status = unsafe { libc::getsockopt(stream, libc::SOL_SOCKET, libc::SO_PEERCRED,
        (&mut observed as *mut libc::ucred).cast(), &mut size) };
    anyhow::ensure!(status == 0, "{}", io::Error::last_os_error());
    anyhow::ensure!(size as usize == std::mem::size_of::<libc::ucred>(), "complete actual peer credentials");
    Ok(observed)
}

fn drain_pipe<R: Read + AsRawFd>(
    pipe: &mut Option<R>, bytes: &mut Vec<u8>, complete: &mut bool, overflow: &mut bool,
) -> io::Result<()> {
    // Drop may run before start() has configured both pipes. Never perform a
    // potentially blocking read on that partial-construction failure path.
    if let Some(reader) = pipe.as_ref() {
        if let Err(error) = set_nonblocking(reader.as_raw_fd()) {
            pipe.take();
            return Err(error);
        }
    }
    let mut buffer = [0_u8; 8192];
    // Bound each drain pass even if a failing child writes continuously.
    for _ in 0..16 {
        let Some(reader) = pipe.as_mut() else { return Ok(()); };
        match reader.read(&mut buffer) {
            Ok(0) => { *complete = true; pipe.take(); return Ok(()); }
            Ok(count) => {
                let retained = count.min(CAPTURE_LIMIT.saturating_sub(bytes.len()));
                bytes.extend_from_slice(&buffer[..retained]);
                if retained != count {
                    *overflow = true;
                    pipe.take();
                    return Err(io::Error::other("fixture child output exceeds retained 1 MiB prefix"));
                }
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => return Ok(()),
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => { pipe.take(); return Err(error); }
        }
    }
    Ok(())
}

/// Actual subprocess output. A missing status or either incomplete stream is
/// an observation failure, never a successful role/test result.
#[derive(Debug, Default)]
pub(super) struct PeerOutput {
    pub(super) status: Option<ExitStatus>,
    pub(super) stdout: Vec<u8>,
    pub(super) stderr: Vec<u8>,
    pub(super) stdout_complete: bool,
    pub(super) stderr_complete: bool,
    pub(super) stdout_overflow: bool,
    pub(super) stderr_overflow: bool,
    pub(super) errors: Vec<String>,
}

/// One actual non-Root exec child, never a fabricated owner or a transferred
/// in-process Arc. Owners and their original handshakes are supplied elsewhere.
pub(super) struct PeerProcess {
    child: Option<Child>,
    control: Option<UnixDatagram>,
    stdout: Option<ChildStdout>,
    stderr: Option<ChildStderr>,
    owner: Option<OwnedFd>,
    uid: u32,
    credentials_ready: bool,
    finished: bool,
    output: PeerOutput,
    pub(super) peer: AgentdRootAuthorityPeer,
}

impl PeerProcess {
    pub(super) fn start(child_fqn: &'static str, uid: u32) -> anyhow::Result<Self> {
        allowed_uid(uid)?;
        anyhow::ensure!(!child_fqn.is_empty() && child_fqn.contains("::")
            && child_fqn.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b':'),
            "one exact test child FQN, never a command line");
        // SAFETY: these calls only observe the explicit Root parent's credentials.
        anyhow::ensure!(unsafe { (libc::getuid(), libc::geteuid()) } == (0, 0), "explicit Root parent required");
        let (control, inherited_control) = UnixDatagram::pair()?;
        control.set_nonblocking(true)?;
        let executable = File::open(std::env::current_exe()?)?;
        let inherited = [inherited_control.as_raw_fd(), executable.as_raw_fd()];
        let mut command = Command::new("/usr/bin/setpriv");
        command.arg(format!("--reuid={uid}")).arg(format!("--regid={uid}"))
            .args(["--clear-groups", "--no-new-privs", "--inh-caps=-all", "--ambient-caps=-all", "--bounding-set=-all"])
            .arg(format!("/proc/self/fd/{}", executable.as_raw_fd()))
            .args(["--exact", child_fqn, "--ignored", "--nocapture", "--test-threads=1"])
            .env_clear().env("PATH", "/usr/bin:/bin")
            .env(CONTROL_ENV, inherited_control.as_raw_fd().to_string())
            .env(EXECUTABLE_ENV, executable.as_raw_fd().to_string())
            .env(UID_ENV, uid.to_string()).env(PARENT_ENV, std::process::id().to_string())
            .current_dir("/").stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
        // SAFETY: after fork, this closure only applies fcntl to the two original
        // live FDs. setpriv performs the actual credential drop during exec.
        unsafe {
            command.pre_exec(move || {
                for descriptor in inherited {
                    let flags = libc::fcntl(descriptor, libc::F_GETFD);
                    if flags < 0 || libc::fcntl(descriptor, libc::F_SETFD, flags & !libc::FD_CLOEXEC) < 0 {
                        return Err(io::Error::last_os_error());
                    }
                }
                Ok(())
            });
        }
        let child = command.spawn()?;
        let pid = child.id();
        drop(inherited_control);
        drop(executable);
        // Immediately own the child under Drop, before any fallible /proc/fd
        // observation. The temporary empty identity is never returned to callers.
        let mut observed = Self {
            child: Some(child), control: Some(control), stdout: None, stderr: None, owner: None,
            uid, credentials_ready: false, finished: false, output: PeerOutput::default(),
            peer: AgentdRootAuthorityPeer { pid, boot_id: String::new(), process_start_ticks: 0 },
        };
        let original_child = observed.child.as_mut().ok_or_else(|| anyhow::anyhow!("owned child"))?;
        observed.stdout = original_child.stdout.take();
        observed.stderr = original_child.stderr.take();
        set_nonblocking(observed.stdout.as_ref().ok_or_else(|| anyhow::anyhow!("original stdout pipe"))?.as_raw_fd())?;
        set_nonblocking(observed.stderr.as_ref().ok_or_else(|| anyhow::anyhow!("original stderr pipe"))?.as_raw_fd())?;
        observed.peer = observed_process(pid)?;
        observed.owner = Some(pin(pid)?);
        let actual_ready = observed.recv_control()?;
        anyhow::ensure!(actual_ready == ready_message(uid, pid), "actual child credential readiness, not a role result");
        crate::authority_host_runtime::verify_process_credentials(pid, uid, uid)?;
        observed.credentials_ready = true;
        observed.ensure_live()?;
        Ok(observed)
    }

    pub(super) fn uid(&self) -> u32 { self.uid }

    pub(super) fn pidfd(&self) -> anyhow::Result<OwnedFd> {
        self.ensure_live()?;
        Ok(self.owner.as_ref().ok_or_else(|| anyhow::anyhow!("actual child pidfd"))?.try_clone()?)
    }

    fn ensure_live(&self) -> anyhow::Result<()> {
        let owner = self.owner.as_ref().ok_or_else(|| anyhow::anyhow!("actual child pidfd"))?;
        crate::authority_host_runtime::owner_alive(owner, Instant::now() + IO_WINDOW)?;
        let current = observed_process(self.peer.pid)?;
        anyhow::ensure!(current.boot_id == self.peer.boot_id && current.process_start_ticks == self.peer.process_start_ticks,
            "same original exec child lifetime");
        if self.credentials_ready {
            crate::authority_host_runtime::verify_process_credentials(self.peer.pid, self.uid, self.uid)?;
        }
        crate::authority_host_runtime::owner_alive(owner, Instant::now() + IO_WINDOW)?;
        Ok(())
    }

    fn drain_output(&mut self) -> anyhow::Result<()> {
        let out = drain_pipe(&mut self.stdout, &mut self.output.stdout,
            &mut self.output.stdout_complete, &mut self.output.stdout_overflow);
        let err = drain_pipe(&mut self.stderr, &mut self.output.stderr,
            &mut self.output.stderr_complete, &mut self.output.stderr_overflow);
        let mut failed = false;
        for (name, result) in [("stdout", out), ("stderr", err)] {
            if let Err(error) = result { self.output.errors.push(format!("{name}: {error}")); failed = true; }
        }
        anyhow::ensure!(!failed, "actual child output capture error: {:?}", self.output.errors);
        Ok(())
    }

    fn observe_exit(&mut self) -> anyhow::Result<bool> {
        if self.output.status.is_none() {
            self.output.status = self.child.as_mut().ok_or_else(|| anyhow::anyhow!("owned child"))?.try_wait()?;
        }
        Ok(self.output.status.is_some())
    }

    fn wait_activity(&self, events: i16, end: Instant) -> anyhow::Result<()> {
        let mut descriptors = [
            libc::pollfd { fd: self.control.as_ref().map_or(-1, AsRawFd::as_raw_fd), events, revents: 0 },
            libc::pollfd { fd: self.stdout.as_ref().map_or(-1, AsRawFd::as_raw_fd), events: libc::POLLIN, revents: 0 },
            libc::pollfd { fd: self.stderr.as_ref().map_or(-1, AsRawFd::as_raw_fd), events: libc::POLLIN, revents: 0 },
        ];
        poll_until(&mut descriptors, end)
    }

    pub(super) fn send_control(&mut self, payload: &[u8]) -> anyhow::Result<()> {
        anyhow::ensure!(payload.len() <= CONTROL_LIMIT, "fixture metadata at most 64 KiB");
        let end = Instant::now() + IO_WINDOW;
        loop {
            within_window(end)?;
            self.drain_output()?;
            anyhow::ensure!(!self.observe_exit()?, "actual child exited before control send");
            let control = self.control.as_ref().ok_or_else(|| anyhow::anyhow!("original control channel"))?;
            match control.send(payload) {
                Ok(count) => { anyhow::ensure!(count == payload.len(), "complete datagram send"); return Ok(()); }
                Err(error) if matches!(error.kind(), io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted) => {}
                Err(error) => return Err(error.into()),
            }
            self.wait_activity(libc::POLLOUT, end)?;
        }
    }

    pub(super) fn recv_control(&mut self) -> anyhow::Result<Vec<u8>> {
        let end = Instant::now() + IO_WINDOW;
        loop {
            within_window(end)?;
            self.drain_output()?;
            let control = self.control.as_ref().ok_or_else(|| anyhow::anyhow!("original control channel"))?;
            match receive_datagram(control) {
                Ok(payload) => return Ok(payload),
                Err(error) if matches!(error.kind(), io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted) => {}
                Err(error) => return Err(error.into()),
            }
            anyhow::ensure!(!self.observe_exit()?, "actual child exited without expected control metadata");
            self.wait_activity(libc::POLLIN, end)?;
        }
    }

    /// Connect a real socket and independently check its actual peer. Control
    /// metadata, listener path text and inherited socketpair credentials cannot
    /// substitute for this check or for the original role protocol handshake.
    pub(super) fn connect_original(&mut self, path: &Path) -> anyhow::Result<UnixStream> {
        self.ensure_live()?;
        let bytes = path.as_os_str().as_bytes();
        anyhow::ensure!(path.is_absolute() && !bytes.contains(&0), "absolute original socket path");
        // SAFETY: sockaddr_un is a plain initialized C socket address.
        let mut address: libc::sockaddr_un = unsafe { std::mem::zeroed() };
        anyhow::ensure!(bytes.len() < address.sun_path.len(), "bounded original Unix socket path");
        address.sun_family = libc::AF_UNIX as libc::sa_family_t;
        for (destination, byte) in address.sun_path.iter_mut().zip(bytes) { *destination = *byte as libc::c_char; }
        // SAFETY: socket creates one new nonblocking, close-on-exec stream FD.
        let number = unsafe { libc::socket(libc::AF_UNIX, libc::SOCK_STREAM | libc::SOCK_NONBLOCK | libc::SOCK_CLOEXEC, 0) };
        anyhow::ensure!(number >= 0, "{}", io::Error::last_os_error());
        // SAFETY: successful socket() transferred exactly one owned stream FD.
        let stream = unsafe { UnixStream::from_raw_fd(number) };
        let length = std::mem::offset_of!(libc::sockaddr_un, sun_path) + bytes.len() + 1;
        // SAFETY: the C address includes the original path plus its final NUL.
        let connected = unsafe { libc::connect(stream.as_raw_fd(), (&address as *const libc::sockaddr_un).cast(),
            libc::socklen_t::try_from(length)?) };
        if connected != 0 {
            let error = io::Error::last_os_error();
            anyhow::ensure!(error.raw_os_error() == Some(libc::EINPROGRESS), "original connect failed: {error}");
            let end = Instant::now() + IO_WINDOW;
            loop {
                within_window(end)?;
                self.drain_output()?;
                self.ensure_live()?;
                let mut descriptor = [libc::pollfd { fd: stream.as_raw_fd(), events: libc::POLLOUT, revents: 0 }];
                poll_until(&mut descriptor, end)?;
                if descriptor[0].revents == 0 { continue; }
                let mut socket_error: libc::c_int = 0;
                let mut size = std::mem::size_of_val(&socket_error) as libc::socklen_t;
                // SAFETY: getsockopt borrows an initialized integer buffer.
                let status = unsafe { libc::getsockopt(stream.as_raw_fd(), libc::SOL_SOCKET, libc::SO_ERROR,
                    (&mut socket_error as *mut libc::c_int).cast(), &mut size) };
                anyhow::ensure!(status == 0 && size as usize == std::mem::size_of::<libc::c_int>(), "actual connect status");
                if socket_error != 0 { return Err(io::Error::from_raw_os_error(socket_error).into()); }
                break;
            }
        }
        let peer = credentials(stream.as_raw_fd())?;
        anyhow::ensure!((peer.uid, peer.gid, peer.pid) == (self.uid, self.uid, i32::try_from(self.peer.pid)?),
            "original protocol socket must belong to the designated actual dedicated child");
        self.ensure_live()?;
        stream.set_nonblocking(false)?;
        Ok(stream)
    }

    /// Invoke the actual process signal path used by the original running app.
    /// Success here means signal delivery only; finish() still requires actual
    /// normal child exit and complete captured output.
    pub(super) fn request_sigterm(&mut self) -> anyhow::Result<()> {
        self.ensure_live()?;
        let owner = self.owner.as_ref().ok_or_else(|| anyhow::anyhow!("actual child pidfd"))?;
        // SAFETY: signal only this retained actual child pidfd, without a payload.
        let status = unsafe { libc::syscall(libc::SYS_pidfd_send_signal, owner.as_raw_fd(), libc::SIGTERM,
            std::ptr::null::<libc::siginfo_t>(), 0) };
        anyhow::ensure!(status == 0, "{}", io::Error::last_os_error());
        Ok(())
    }

    fn collect_until(&mut self, end: Instant) -> anyhow::Result<()> {
        loop {
            within_window(end)?;
            self.drain_output()?;
            if self.observe_exit()? && self.stdout.is_none() && self.stderr.is_none() { return Ok(()); }
            self.wait_activity(0, end)?;
        }
    }

    fn kill_owned_and_collect(&mut self) {
        self.control.take();
        let already_exited = self.observe_exit();
        if !matches!(already_exited, Ok(true)) {
            if let Some(child) = self.child.as_mut() {
                if let Err(error) = child.kill() { self.output.errors.push(format!("owned child kill: {error}")); }
            }
        }
        let end = Instant::now() + CLEANUP_WINDOW;
        loop {
            // Even output overflow must not prevent reaping our own child.
            let _ = self.drain_output();
            let exited = match self.observe_exit() {
                Ok(value) => value,
                Err(error) => { self.output.errors.push(format!("owned child wait: {error}")); false }
            };
            if exited && self.stdout.is_none() && self.stderr.is_none() { break; }
            if Instant::now() >= end {
                self.output.errors.push("bounded owned-child/output cleanup expired; any missing terminal remains unknown".into());
                break;
            }
            if let Err(error) = self.wait_activity(0, end) {
                self.output.errors.push(format!("cleanup poll: {error}"));
                break;
            }
        }
    }

    pub(super) fn finish(mut self) -> anyhow::Result<PeerOutput> {
        self.control.take();
        let joined = self.collect_until(Instant::now() + IO_WINDOW);
        if let Err(error) = joined {
            self.output.errors.push(format!("original child join: {error}"));
            self.kill_owned_and_collect();
        }
        self.finished = true;
        self.child.take();
        let output = std::mem::take(&mut self.output);
        anyhow::ensure!(output.errors.is_empty() && output.status.is_some_and(|status| status.success())
            && output.stdout_complete && output.stderr_complete
            && !output.stdout_overflow && !output.stderr_overflow,
            "actual dedicated peer did not finish normally; retained raw output: {output:?}");
        Ok(output)
    }
}

impl Drop for PeerProcess {
    fn drop(&mut self) {
        if !self.finished && self.child.is_some() {
            self.kill_owned_and_collect();
            // Emit the retained raw byte arrays to the original test's stderr
            // on early errors/panics; the enclosing recorder keeps its own
            // unchanged output limit and reports any truncation separately.
            eprintln!("RESIDENT_PAIR_UNFINISHED pid={} uid={} retained={:?}", self.peer.pid, self.uid, self.output);
        }
    }
}

/// Child-side one-time ownership of the inherited metadata channel. This is
/// deliberately not a protocol source, signer, trust loader or role adapter.
pub(super) struct ChildControl {
    control: UnixDatagram,
}

impl ChildControl {
    pub(super) fn from_inherited_control(expected_uid: u32) -> anyhow::Result<Self> {
        allowed_uid(expected_uid)?;
        let actual_uid: u32 = std::env::var(UID_ENV)?.parse()?;
        anyhow::ensure!(actual_uid == expected_uid, "expected actual child role UID");
        crate::authority_host_runtime::verify_process_credentials(std::process::id(), expected_uid, expected_uid)?;
        let number: i32 = std::env::var(CONTROL_ENV)?.parse()?;
        let executable: i32 = std::env::var(EXECUTABLE_ENV)?.parse()?;
        let parent: u32 = std::env::var(PARENT_ENV)?.parse()?;
        anyhow::ensure!(number >= 3 && executable >= 3 && number != executable && parent > 0, "two original distinct inherited FDs");
        // SAFETY: getppid only observes the actual kernel parent process.
        anyhow::ensure!(unsafe { libc::getppid() } == i32::try_from(parent)?, "original Root subprocess parent");
        anyhow::ensure!(CHILD_CONTROL_TAKEN.compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst).is_ok(),
            "inherited metadata descriptor may be consumed only once");
        // SAFETY: this exact exec path transfers the two distinct descriptor
        // owners once; the atomic guard rejects another adoption in this process.
        let control = unsafe { UnixDatagram::from_raw_fd(number) };
        // SAFETY: the second distinct inherited FD is the original read-only ELF.
        let executable = unsafe { File::from_raw_fd(executable) };
        anyhow::ensure!(executable.metadata()?.is_file(), "original executable descriptor");
        drop(executable);
        let mut socket_kind: libc::c_int = 0;
        let mut size = std::mem::size_of_val(&socket_kind) as libc::socklen_t;
        // SAFETY: getsockopt borrows the initialized integer buffer.
        let status = unsafe { libc::getsockopt(control.as_raw_fd(), libc::SOL_SOCKET, libc::SO_TYPE,
            (&mut socket_kind as *mut libc::c_int).cast(), &mut size) };
        anyhow::ensure!(status == 0 && socket_kind == libc::SOCK_DGRAM
            && size as usize == std::mem::size_of::<libc::c_int>(), "original inherited datagram control");
        let creator = credentials(control.as_raw_fd())?;
        anyhow::ensure!((creator.uid, creator.gid, creator.pid) == (0, 0, i32::try_from(parent)?),
            "control socketpair was created by the actual Root parent; this is not child SO_PEERCRED");
        set_cloexec(control.as_raw_fd())?;
        control.set_nonblocking(true)?;
        let observed = Self { control };
        observed.send(&ready_message(expected_uid, std::process::id()))?;
        Ok(observed)
    }

    pub(super) fn send(&self, payload: &[u8]) -> anyhow::Result<()> {
        anyhow::ensure!(payload.len() <= CONTROL_LIMIT, "fixture metadata at most 64 KiB");
        let end = Instant::now() + IO_WINDOW;
        loop {
            within_window(end)?;
            match self.control.send(payload) {
                Ok(count) => { anyhow::ensure!(count == payload.len(), "complete metadata datagram"); return Ok(()); }
                Err(error) if matches!(error.kind(), io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted) => {}
                Err(error) => return Err(error.into()),
            }
            poll_until(&mut [libc::pollfd { fd: self.control.as_raw_fd(), events: libc::POLLOUT, revents: 0 }], end)?;
        }
    }

    pub(super) fn recv(&self) -> anyhow::Result<Vec<u8>> {
        let end = Instant::now() + IO_WINDOW;
        loop {
            within_window(end)?;
            match receive_datagram(&self.control) {
                Ok(payload) => return Ok(payload),
                Err(error) if matches!(error.kind(), io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted) => {}
                Err(error) => return Err(error.into()),
            }
            poll_until(&mut [libc::pollfd { fd: self.control.as_raw_fd(), events: libc::POLLIN, revents: 0 }], end)?;
        }
    }
}
