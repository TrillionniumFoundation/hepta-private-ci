//! One inherited Root checkpoint lane, without a Current admission constructor.

use std::fs::File;
use std::io::Read;
use std::mem::size_of;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_memory::COGNITIVE_CHECKPOINT_FRAME_LIMIT;
use codex_hepta_memory::CognitiveCheckpointRequest;
use codex_hepta_memory::ObjectiveSenderCheckpointError as Error;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::unix::AsyncFd;

/// Root identity pinned by the trusted launcher before descriptor transfer.
/// These values must not be learned from an untrusted response or socket path.
pub struct AgentdRootCheckpointPeer {
    pub pid: u32,
    pub boot_id: String,
    pub process_start_ticks: u64,
}

/// Synchronous custody, suitable for the original single-thread preflight.
/// This owns the exact connected stream and original pidfd; it starts no task
/// or runtime, opens no replacement channel, and performs no credential change.
pub struct AgentdRootCheckpointBootstrap {
    stream: UnixStream,
    root: OwnedFd,
    timeout: Duration,
    end: Instant,
}

/// Exclusive asynchronous transport, not a recovery or FinalUse capability.
/// A caller must still verify Current, live authority, the exact cut and legal
/// predecessor/successor before admission. There is no arbitrary Receipt to
/// Current conversion here, and this channel never creates a signer or issuer.
pub struct AgentdRootCheckpointChannel {
    stream: Option<tokio::net::UnixStream>,
    root: AsyncFd<OwnedFd>,
    timeout: Duration,
    end: Instant,
}

impl AgentdRootCheckpointBootstrap {
    /// Consume descriptors supplied by the trusted launcher in its host PID/user
    /// namespace. Only the pinned UID 0 peer is accepted. Both descriptors regain
    /// CLOEXEC before returning; duplicate descriptors remain the caller's duty.
    /// The credential and proc observations are namespace-relative; they do not
    /// authenticate the launcher's host-namespace or authority provenance.
    /// The relative lifetime bounds transport use; it never establishes a lease
    /// expiry or makes process liveness atomic with a later database admission.
    pub fn from_inherited(
        stream: UnixStream,
        root: OwnedFd,
        peer: AgentdRootCheckpointPeer,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::from_peer(stream, root, peer, timeout, lifetime, /*uid*/ 0)
    }

    fn from_peer(
        stream: UnixStream,
        root: OwnedFd,
        peer: AgentdRootCheckpointPeer,
        timeout: Duration,
        lifetime: Duration,
        uid: u32,
    ) -> Result<Self, Error> {
        let created = Instant::now();
        if peer.pid == 0 || peer.pid > i32::MAX as u32 || peer.process_start_ticks == 0
            || timeout.is_zero() || timeout > Duration::from_secs(5)
            || lifetime.is_zero() || lifetime > Duration::from_secs(300)
        {
            return Err(Error::Refused);
        }
        for fd in [stream.as_raw_fd(), root.as_raw_fd()] {
            // SAFETY: each descriptor is owned and live throughout both calls;
            // descriptor flags are preserved and no raw ownership is transferred.
            let result = unsafe {
                let flags = libc::fcntl(fd, libc::F_GETFD);
                if flags < 0 { -1 } else { libc::fcntl(fd, libc::F_SETFD, flags | libc::FD_CLOEXEC) }
            };
            if result < 0 {
                return Err(Error::Unavailable);
            }
        }
        let mut actual = libc::ucred { pid: 0, uid: 0, gid: 0 };
        let mut length = size_of::<libc::ucred>() as libc::socklen_t;
        // SAFETY: the live socket and initialized output have the declared size.
        let result = unsafe {
            libc::getsockopt(stream.as_raw_fd(), libc::SOL_SOCKET, libc::SO_PEERCRED,
                (&mut actual as *mut libc::ucred).cast(), &mut length)
        };
        if result != 0 || length as usize != size_of::<libc::ucred>()
            || actual.uid != uid || actual.pid != peer.pid as i32
        {
            return Err(Error::Refused);
        }
        let number = root.as_raw_fd();
        if std::fs::read_link(format!("/proc/self/fd/{number}")).map_err(unavailable)?
            != Path::new("anon_inode:[pidfd]")
            || bounded_text(&format!("/proc/self/fdinfo/{number}"), /*limit*/ 4096)?.lines()
                .find_map(|line| line.strip_prefix("Pid:")?.trim().parse::<u32>().ok()) != Some(peer.pid)
            || bounded_text("/proc/sys/kernel/random/boot_id", /*limit*/ 128)?.trim() != peer.boot_id
        {
            return Err(Error::Refused);
        }
        let stat = bounded_text(&format!("/proc/{}/stat", peer.pid), /*limit*/ 8192)?;
        if stat.rsplit_once(") ").and_then(|(_, fields)| fields.split_whitespace().nth(19))
            .and_then(|value| value.parse::<u64>().ok()) != Some(peer.process_start_ticks)
        {
            return Err(Error::Refused);
        }
        root_alive(&root)?;
        let end = created + lifetime;
        if Instant::now() >= end {
            return Err(Error::Unavailable);
        }
        Ok(Self { stream, root, timeout, end })
    }

    /// Register only after entering the normal I/O-enabled Tokio runtime.
    /// O_NONBLOCK changes this stream's shared open-file-description: the
    /// launcher must not retain aliases that expect blocking I/O on it.
    pub fn into_runtime(self) -> Result<AgentdRootCheckpointChannel, Error> {
        root_alive(&self.root)?;
        if Instant::now() >= self.end {
            return Err(Error::Unavailable);
        }
        self.stream.set_nonblocking(true).map_err(unavailable)?;
        let stream = tokio::net::UnixStream::from_std(self.stream).map_err(unavailable)?;
        // SAFETY: AsyncFd owns this OwnedFd exclusively. No raw descriptor or
        // mutable access escapes; it remains the same live descriptor until drop.
        let root = unsafe { AsyncFd::register_with_interest(self.root, tokio::io::Interest::READABLE) }
            .map_err(|_| Error::Unavailable)?;
        root_alive(root.get_ref())?;
        Ok(AgentdRootCheckpointChannel { stream: Some(stream), root, timeout: self.timeout, end: self.end })
    }
}

impl AgentdRootCheckpointChannel {
    /// Send the exact codec bytes once. An in-flight cancellation, any invalid
    /// response, timeout or Root exit consumes the channel permanently. A complete
    /// ACK returns its original bytes for the caller's full successor validation.
    pub async fn exchange(&mut self, request: &CognitiveCheckpointRequest) -> Result<Vec<u8>, Error> {
        let bytes = request.encode()?;
        let mut stream = self.stream.take().ok_or(Error::Unavailable)?;
        root_alive(self.root.get_ref())?;
        let deadline = (Instant::now() + self.timeout).min(self.end);
        if Instant::now() >= deadline {
            return Err(Error::Unavailable);
        }
        let response = tokio::select! {
            biased;
            _ = self.root.readable() => return Err(Error::Unavailable),
            _ = tokio::time::sleep_until(tokio::time::Instant::from_std(deadline)) => return Err(Error::Unavailable),
            response = async {
                stream.write_all(&(bytes.len() as u32).to_be_bytes()).await.map_err(unavailable)?;
                stream.write_all(&bytes).await.map_err(unavailable)?;
                let mut prefix = [0; 4];
                stream.read_exact(&mut prefix).await.map_err(unavailable)?;
                let length = u32::from_be_bytes(prefix) as usize;
                if length == 0 || length > COGNITIVE_CHECKPOINT_FRAME_LIMIT {
                    return Err(Error::Unavailable);
                }
                let mut response = vec![0; length];
                stream.read_exact(&mut response).await.map_err(unavailable)?;
                Ok::<_, Error>(response)
            } => response?,
        };
        request.decode_ack(&response)?;
        root_alive(self.root.get_ref())?;
        if Instant::now() >= deadline {
            return Err(Error::Unavailable);
        }
        self.stream = Some(stream);
        Ok(response)
    }
}

fn bounded_text(path: &str, limit: u64) -> Result<String, Error> {
    let mut text = String::new();
    File::open(path).map_err(unavailable)?.take(limit + 1)
        .read_to_string(&mut text).map_err(unavailable)?;
    if text.len() as u64 > limit {
        return Err(Error::Refused);
    }
    Ok(text)
}

fn root_alive(root: &OwnedFd) -> Result<(), Error> {
    let mut descriptor = libc::pollfd { fd: root.as_raw_fd(), events: libc::POLLIN, revents: 0 };
    // SAFETY: one owned live descriptor and one writable pollfd; this never waits.
    let result = unsafe { libc::poll(&mut descriptor, /*nfds*/ 1, /*timeout*/ 0) };
    if result == 0 && descriptor.revents == 0 {
        Ok(())
    } else {
        Err(Error::Unavailable)
    }
}

fn unavailable(_: std::io::Error) -> Error {
    Error::Unavailable
}

#[cfg(test)]
#[path = "root_checkpoint_transport_tests.rs"]
mod tests;
