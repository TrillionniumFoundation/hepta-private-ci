//! Fixed Root-pinned framing. Bootstrap alone inspects procfs; every
//! exchange is bounded asynchronous I/O on the original held descriptors.
//! Private clients select their own purpose-bound protocol; a learning client
//! uses a separately transferred socket, never the original observation lane.

use std::fs::File;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use crate::root_writer_proof::AgentdRootAuthorityError;
use std::sync::Arc;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::unix::AsyncFd;

/// Exact root process identity established by the trusted launcher before
/// descriptor transfer. A numeric PID discovered from the connection is not
/// sufficient; the launcher must also retain and transfer its original pidfd.
pub struct AgentdRootAuthorityPeer {
    pub pid: u32,
    pub boot_id: String,
    pub process_start_ticks: u64,
}

/// One original protected-host observation stream. Cancellation drops its exclusive stream
/// while the slot is empty, permanently invalidating the lane. No later call
/// can consume a late reply or obtain another connection. All Future polls use
/// nonblocking I/O, including observation of the original root process lifetime.
pub(crate) struct RootObservationStream {
    exchange: tokio::sync::Semaphore,
    stream: Mutex<Option<tokio::net::UnixStream>>,
    root: Arc<AsyncFd<OwnedFd>>,
    timeout: Duration,
    end: Instant,
}

enum ObservationFrameExit {
    Unfinished,
    Failed(AgentdRootAuthorityError),
    Restored,
}

// This guard outlives the nested frame future below. An error or unfinished
// future drops its taken stream before this diagnostic runs. A successful
// frame restores that same stream before marking Restored. No payload or
// authority is retained in this record, and it controls no I/O or admission.
struct ObservationFrameDiagnostic {
    phase: &'static str,
    exit: ObservationFrameExit,
    stream_taken: bool,
    error_kind: Option<std::io::ErrorKind>,
    raw_os_error: Option<i32>,
}

impl Drop for ObservationFrameDiagnostic {
    fn drop(&mut self) {
        let (exit, error) = match &self.exit {
            ObservationFrameExit::Restored => return,
            ObservationFrameExit::Failed(error) => ("failed", Some(error)),
            // Cancellation and unwinding are both unfinished future drops;
            // this label does not claim which of them caused the drop.
            ObservationFrameExit::Unfinished => ("unfinished-future-drop", None),
        };
        let _ = std::io::Write::write_fmt(
            &mut std::io::stderr(),
            format_args!(
                "ROOT_OBSERVATION_DIAGNOSTIC phase={} exit={} class={:?} io_kind={:?} raw_os_error={:?} stream_taken={} thread={:?}\n",
                self.phase,
                exit,
                error,
                self.error_kind,
                self.raw_os_error,
                self.stream_taken,
                std::thread::current().id(),
            ),
        );
    }
}

impl RootObservationStream {
    /// Bootstrap inside the existing I/O-enabled runtime context, with sole
    /// ownership of an already connected stream and a pre-held root pidfd.
    /// Configuration checks read bounded procfs metadata only during bootstrap.
    pub(crate) fn from_stream(
        stream: UnixStream,
        peer: AgentdRootAuthorityPeer,
        root_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, AgentdRootAuthorityError> {
        Self::from_stream_for_uid(stream, peer, root_pidfd, timeout, lifetime, 0)
    }

    pub(super) fn from_stream_for_uid(
        stream: UnixStream,
        peer: AgentdRootAuthorityPeer,
        root_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
        uid: u32,
    ) -> Result<Self, AgentdRootAuthorityError> {
        if lifetime.is_zero() || lifetime > Duration::from_secs(300) {
            return Err(AgentdRootAuthorityError::Refused);
        }
        Self::from_stream_for_uid_until(
            stream,
            peer,
            root_pidfd,
            timeout,
            Instant::now() + lifetime,
            uid,
        )
    }

    pub(crate) fn from_stream_until(
        stream: UnixStream,
        peer: AgentdRootAuthorityPeer,
        root_pidfd: OwnedFd,
        timeout: Duration,
        end: Instant,
    ) -> Result<Self, AgentdRootAuthorityError> {
        Self::from_stream_for_uid_until(stream, peer, root_pidfd, timeout, end, /*uid*/ 0)
    }

    fn from_stream_for_uid_until(
        stream: UnixStream,
        peer: AgentdRootAuthorityPeer,
        root_pidfd: OwnedFd,
        timeout: Duration,
        end: Instant,
        uid: u32,
    ) -> Result<Self, AgentdRootAuthorityError> {
        let remaining = end
            .checked_duration_since(Instant::now())
            .ok_or(AgentdRootAuthorityError::Refused)?;
        if peer.pid == 0
            || peer.pid > i32::MAX as u32
            || peer.process_start_ticks == 0
            || timeout.is_zero()
            || timeout > Duration::from_millis(500)
            || remaining.is_zero()
            || remaining > Duration::from_secs(300)
        {
            return Err(AgentdRootAuthorityError::Refused);
        }
        let number = root_pidfd.as_raw_fd();
        if std::fs::read_link(format!("/proc/self/fd/{number}")).map_err(unavailable)?
            != Path::new("anon_inode:[pidfd]")
            || bounded_text(&format!("/proc/self/fdinfo/{number}"), 4096)?
                .lines()
                .find_map(|line| line.strip_prefix("Pid:")?.trim().parse::<u32>().ok())
                != Some(peer.pid)
            || bounded_text("/proc/sys/kernel/random/boot_id", 128)?.trim() != peer.boot_id
        {
            return Err(AgentdRootAuthorityError::Refused);
        }
        let stat = bounded_text(&format!("/proc/{}/stat", peer.pid), 8192)?;
        let start = stat
            .rsplit_once(") ")
            .and_then(|(_, fields)| fields.split_whitespace().nth(19))
            .and_then(|value| value.parse::<u64>().ok());
        if start != Some(peer.process_start_ticks) {
            return Err(AgentdRootAuthorityError::Refused);
        }
        check_lifetime(&root_pidfd)?;
        stream.set_nonblocking(true).map_err(unavailable)?;
        let stream = tokio::net::UnixStream::from_std(stream).map_err(unavailable)?;
        let actual = stream.peer_cred().map_err(unavailable)?;
        if actual.uid() != uid
            || actual.pid().and_then(|pid| u32::try_from(pid).ok()) != Some(peer.pid)
        {
            return Err(AgentdRootAuthorityError::Refused);
        }
        // SAFETY: AsyncFd exclusively owns this OwnedFd. Its number and open
        // file description remain unchanged until AsyncFd drops it; no raw fd
        // ownership or mutable access escapes this client.
        let root =
            unsafe { AsyncFd::register_with_interest(root_pidfd, tokio::io::Interest::READABLE) }
                .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
        check_lifetime(root.get_ref())?;
        if Instant::now() >= end {
            return Err(AgentdRootAuthorityError::Refused);
        }
        Ok(Self {
            exchange: tokio::sync::Semaphore::new(1),
            stream: Mutex::new(Some(stream)),
            root: Arc::new(root),
            timeout,
            end,
        })
    }
}

impl RootObservationStream {
    pub(crate) fn root_lifetime(&self) -> Arc<AsyncFd<OwnedFd>> {
        Arc::clone(&self.root)
    }

    /// Private operation selection belongs to the client owning this exact
    /// lane. The observation client remains read-only; learning mutations use
    /// a separately bound Root socket and validate the complete typed reply.
    pub(crate) async fn read<R: serde::de::DeserializeOwned>(
        &self,
        request: &impl serde::Serialize,
    ) -> Result<R, AgentdRootAuthorityError> {
        let request = serde_json::to_vec(request).map_err(|_| AgentdRootAuthorityError::Refused)?;
        if request.is_empty() || request.len() > 16_384 {
            return Err(AgentdRootAuthorityError::Refused);
        }
        // Competing requests fail before touching the slot. This permit has
        // no payload and stays live through complete validation and restore.
        let _exchange = self
            .exchange
            .try_acquire()
            .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
        let mut diagnostic = ObservationFrameDiagnostic {
            phase: "take-stream",
            exit: ObservationFrameExit::Unfinished,
            stream_taken: false,
            error_kind: None,
            raw_os_error: None,
        };
        let result = async {
            let mut stream = {
                let mut slot = self
                    .stream
                    .try_lock()
                    .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
                slot.take().ok_or(AgentdRootAuthorityError::Unavailable)?
            };
            diagnostic.stream_taken = true;
            // Cancellation, malformed replies and every uncertain I/O error leave
            // the original slot empty. No reconnect or automatic retry exists.
            diagnostic.phase = "pre-lifetime";
            check_lifetime(self.root.get_ref())?;
            let deadline = (Instant::now() + self.timeout).min(self.end);
            diagnostic.phase = "pre-exchange-deadline";
            if deadline <= Instant::now() {
                return Err(AgentdRootAuthorityError::Unavailable);
            }
            let response = tokio::select! {
                biased;
                _ = self.root.readable() => {
                    diagnostic.phase = "root-pidfd-select";
                    return Err(AgentdRootAuthorityError::Unavailable);
                }
                _ = tokio::time::sleep_until(tokio::time::Instant::from_std(deadline)) => {
                    diagnostic.phase = "deadline-select";
                    return Err(AgentdRootAuthorityError::Unavailable);
                }
                response = framed_exchange(&mut stream, &request, &mut diagnostic) => response?,
            };
            diagnostic.phase = "post-lifetime";
            check_lifetime(self.root.get_ref())?;
            diagnostic.phase = "response-decode";
            let parsed = serde_json::from_slice(&response)
                .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
            diagnostic.phase = "post-decode-deadline";
            if Instant::now() >= deadline {
                return Err(AgentdRootAuthorityError::Unavailable);
            }
            // The empty slot is the exclusive token for the complete exchange.
            // Its mutex only protects synchronous take/restore, never I/O or an
            // await. The original exchange permit excludes every other slot user,
            // so restoring the same stream requires no synchronous lock wait.
            diagnostic.phase = "restore-stream";
            *self
                .stream
                .try_lock()
                .map_err(|_| AgentdRootAuthorityError::Unavailable)? = Some(stream);
            Ok(parsed)
        }
        .await;
        diagnostic.exit = match &result {
            Ok(_) => ObservationFrameExit::Restored,
            Err(error) => ObservationFrameExit::Failed(*error),
        };
        result
    }
}

async fn framed_exchange(
    stream: &mut tokio::net::UnixStream,
    request: &[u8],
    diagnostic: &mut ObservationFrameDiagnostic,
) -> Result<Vec<u8>, AgentdRootAuthorityError> {
    diagnostic.phase = "request-header-write";
    stream
        .write_all(&(request.len() as u32).to_be_bytes())
        .await
        .map_err(|error| {
            diagnostic.error_kind = Some(error.kind());
            diagnostic.raw_os_error = error.raw_os_error();
            unavailable(error)
        })?;
    diagnostic.phase = "request-body-write";
    stream.write_all(request).await.map_err(|error| {
        diagnostic.error_kind = Some(error.kind());
        diagnostic.raw_os_error = error.raw_os_error();
        unavailable(error)
    })?;
    let mut prefix = [0; 4];
    diagnostic.phase = "response-header-read";
    stream.read_exact(&mut prefix).await.map_err(|error| {
        diagnostic.error_kind = Some(error.kind());
        diagnostic.raw_os_error = error.raw_os_error();
        unavailable(error)
    })?;
    diagnostic.phase = "response-length";
    let length = u32::from_be_bytes(prefix) as usize;
    if length == 0 || length > 16_384 {
        return Err(AgentdRootAuthorityError::Unavailable);
    }
    let mut response = vec![0; length];
    diagnostic.phase = "response-body-read";
    stream.read_exact(&mut response).await.map_err(|error| {
        diagnostic.error_kind = Some(error.kind());
        diagnostic.raw_os_error = error.raw_os_error();
        unavailable(error)
    })?;
    Ok(response)
}

fn bounded_text(path: &str, limit: u64) -> Result<String, AgentdRootAuthorityError> {
    let mut text = String::new();
    File::open(path)
        .map_err(unavailable)?
        .take(limit + 1)
        .read_to_string(&mut text)
        .map_err(unavailable)?;
    if text.len() as u64 > limit {
        return Err(AgentdRootAuthorityError::Refused);
    }
    Ok(text)
}

pub(crate) fn check_lifetime(pidfd: &OwnedFd) -> Result<(), AgentdRootAuthorityError> {
    let mut descriptor = libc::pollfd {
        fd: pidfd.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };
    for _ in 0..3 {
        // SAFETY: one live descriptor and a correctly sized writable pollfd.
        // The zero timeout only samples readiness and never waits in a poll.
        let result = unsafe { libc::poll(&mut descriptor, 1, 0) };
        if result == 0 && descriptor.revents == 0 {
            return Ok(());
        }
        if result < 0 && std::io::Error::last_os_error().kind() == std::io::ErrorKind::Interrupted {
            continue;
        }
        return Err(AgentdRootAuthorityError::Unavailable);
    }
    Err(AgentdRootAuthorityError::Unavailable)
}

fn unavailable(_: std::io::Error) -> AgentdRootAuthorityError {
    AgentdRootAuthorityError::Unavailable
}

#[cfg(test)]
#[path = "root_observation_stream_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "root_observation_stream_absolute_end_tests.rs"]
mod absolute_end_tests;
