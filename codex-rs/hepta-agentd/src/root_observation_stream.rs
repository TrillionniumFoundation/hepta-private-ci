//! Fixed root observation channel. Bootstrap alone inspects procfs; every
//! exchange is bounded asynchronous I/O on the original held descriptors.

use std::fs::File;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use crate::root_observation_diagnostic::ObservationDiagnostics;
use crate::root_observation_diagnostic::ObservationFailure;
use crate::root_writer_proof::AgentdRootAuthorityError;
use std::sync::Arc;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::unix::AsyncFd;
use tokio::sync::Mutex;

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
    stream: Mutex<Option<tokio::net::UnixStream>>,
    root: Arc<AsyncFd<OwnedFd>>,
    timeout: Duration,
    end: Instant,
    diagnostics: Arc<ObservationDiagnostics>,
}

/// The already verified channel is moved between reactors, never reconnected.
/// The pidfd duplicate refers to the original held open file description.
pub(super) struct RootObservationTransfer {
    stream: UnixStream,
    root: OwnedFd,
    timeout: Duration,
    end: Instant,
    diagnostics: Arc<ObservationDiagnostics>,
}

impl RootObservationTransfer {
    pub(super) fn register(self) -> Result<RootObservationStream, AgentdRootAuthorityError> {
        check_lifetime_diagnosed(&self.root, &self.diagnostics, "stream_transfer_lifetime")?;
        let stream = tokio::net::UnixStream::from_std(self.stream)
            .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
        let root = AsyncFd::with_interest(self.root, tokio::io::Interest::READABLE)
            .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
        Ok(RootObservationStream {
            stream: Mutex::new(Some(stream)),
            root: Arc::new(root),
            timeout: self.timeout,
            end: self.end,
            diagnostics: self.diagnostics,
        })
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
        if peer.pid == 0
            || peer.pid > i32::MAX as u32
            || peer.process_start_ticks == 0
            || timeout.is_zero()
            || timeout > Duration::from_millis(500)
            || lifetime.is_zero()
            || lifetime > Duration::from_secs(300)
        {
            return Err(AgentdRootAuthorityError::Refused);
        }
        let number = root_pidfd.as_raw_fd();
        if std::fs::read_link(format!("/proc/self/fd/{number}"))
            .map_err(|_| AgentdRootAuthorityError::Unavailable)?
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
        stream
            .set_nonblocking(true)
            .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
        let stream = tokio::net::UnixStream::from_std(stream)
            .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
        let actual = stream
            .peer_cred()
            .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
        if actual.uid() != uid
            || actual.pid().and_then(|pid| u32::try_from(pid).ok()) != Some(peer.pid)
        {
            return Err(AgentdRootAuthorityError::Refused);
        }
        // Tokio 1.52 registration exclusively owns this OwnedFd. Its number and open
        // file description remain unchanged until AsyncFd drops it; no raw fd
        // ownership or mutable access escapes this client.
        let root = AsyncFd::with_interest(root_pidfd, tokio::io::Interest::READABLE)
            .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
        check_lifetime(root.get_ref())?;
        Ok(Self {
            stream: Mutex::new(Some(stream)),
            root: Arc::new(root),
            timeout,
            end: Instant::now() + lifetime,
            diagnostics: Arc::new(ObservationDiagnostics::default()),
        })
    }
}

impl RootObservationStream {
    pub(super) fn into_transfer(self) -> Result<RootObservationTransfer, AgentdRootAuthorityError> {
        let stream = self
            .stream
            .into_inner()
            .ok_or(AgentdRootAuthorityError::Unavailable)?
            .into_std()
            .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
        let root = self
            .root
            .get_ref()
            .try_clone()
            .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
        Ok(RootObservationTransfer {
            stream,
            root,
            timeout: self.timeout,
            end: self.end,
            diagnostics: self.diagnostics,
        })
    }

    pub(crate) fn root_lifetime(&self) -> Arc<AsyncFd<OwnedFd>> {
        Arc::clone(&self.root)
    }

    pub(super) fn diagnostics(&self) -> Arc<ObservationDiagnostics> {
        Arc::clone(&self.diagnostics)
    }

    /// Private operation selection: callers cannot forward renderer bytes or
    /// ask this observation lane to issue a grant or modify an owner.
    pub(crate) async fn read<R: serde::de::DeserializeOwned>(
        &self,
        request: &impl serde::Serialize,
    ) -> Result<R, AgentdRootAuthorityError> {
        let mut attempt = ReadAttempt {
            diagnostics: &self.diagnostics,
            started: None,
            complete: false,
        };
        let request = serde_json::to_vec(request).map_err(|_| {
            attempt.record("stream_request_serialize");
            AgentdRootAuthorityError::Refused
        })?;
        if request.is_empty() || request.len() > 16_384 {
            attempt.record("stream_request_length");
            return Err(AgentdRootAuthorityError::Refused);
        }
        let mut slot = self
            .stream
            .try_lock()
            .map_err(|_| attempt.fail("stream_slot_busy"))?;
        let mut stream = slot
            .take()
            .ok_or_else(|| attempt.fail("stream_slot_empty"))?;
        // Cancellation, malformed replies and every uncertain I/O error leave
        // the original slot empty. No reconnect or automatic retry exists.
        check_lifetime_diagnosed(
            self.root.get_ref(),
            &self.diagnostics,
            "stream_read_lifetime_before",
        )?;
        let started = Instant::now();
        attempt.started = Some(started);
        let deadline = (started + self.timeout).min(self.end);
        if deadline <= Instant::now() {
            return Err(attempt.fail("stream_deadline_elapsed_before"));
        }
        let response = tokio::select! {
            biased;
            ready = self.root.readable() => {
                match ready {
                    Ok(_) => return Err(attempt.fail("stream_root_readable")),
                    Err(error) => return Err(attempt.io_failure("stream_root_readable_error", error)),
                }
            },
            _ = tokio::time::sleep_until(tokio::time::Instant::from_std(deadline)) => {
                return Err(attempt.fail("stream_read_timeout"));
            }
            response = framed_exchange(&mut stream, &request, &attempt) => response?,
        };
        check_lifetime_diagnosed(
            self.root.get_ref(),
            &self.diagnostics,
            "stream_read_lifetime_after",
        )?;
        let parsed = serde_json::from_slice(&response)
            .map_err(|_| attempt.fail("stream_response_malformed"))?;
        if Instant::now() >= deadline {
            return Err(attempt.fail("stream_response_late"));
        }
        *slot = Some(stream);
        attempt.complete = true;
        Ok(parsed)
    }
}

/// An externally cancelled exchange has no error return to annotate. Keep its
/// first failure without restoring the consumed stream or changing cancellation.
struct ReadAttempt<'a> {
    diagnostics: &'a ObservationDiagnostics,
    started: Option<Instant>,
    complete: bool,
}

impl ReadAttempt<'_> {
    fn failure(&self, stage: &'static str) -> ObservationFailure {
        ObservationFailure {
            stage,
            duration_ns: self
                .started
                .and_then(|started| u64::try_from(started.elapsed().as_nanos()).ok()),
            ..Default::default()
        }
    }

    fn record(&self, stage: &'static str) {
        self.diagnostics.record(self.failure(stage));
    }

    fn fail(&self, stage: &'static str) -> AgentdRootAuthorityError {
        self.record(stage);
        AgentdRootAuthorityError::Unavailable
    }

    fn io_failure(&self, stage: &'static str, error: std::io::Error) -> AgentdRootAuthorityError {
        self.diagnostics.record(ObservationFailure {
            os_error: error.raw_os_error(),
            io_error_kind: Some(error.kind()),
            ..self.failure(stage)
        });
        AgentdRootAuthorityError::Unavailable
    }
}

impl Drop for ReadAttempt<'_> {
    fn drop(&mut self) {
        if !self.complete {
            self.record("stream_read_cancelled");
        }
    }
}

async fn framed_exchange(
    stream: &mut tokio::net::UnixStream,
    request: &[u8],
    attempt: &ReadAttempt<'_>,
) -> Result<Vec<u8>, AgentdRootAuthorityError> {
    stream
        .write_all(&(request.len() as u32).to_be_bytes())
        .await
        .map_err(|error| attempt.io_failure("stream_request_prefix_write", error))?;
    stream
        .write_all(request)
        .await
        .map_err(|error| attempt.io_failure("stream_request_body_write", error))?;
    let mut prefix = [0; 4];
    stream
        .read_exact(&mut prefix)
        .await
        .map_err(|error| attempt.io_failure("stream_response_prefix_read", error))?;
    let length = u32::from_be_bytes(prefix) as usize;
    if length == 0 || length > 16_384 {
        return Err(attempt.fail("stream_response_length"));
    }
    let mut response = vec![0; length];
    stream
        .read_exact(&mut response)
        .await
        .map_err(|error| attempt.io_failure("stream_response_body_read", error))?;
    Ok(response)
}

fn bounded_text(path: &str, limit: u64) -> Result<String, AgentdRootAuthorityError> {
    let mut text = String::new();
    File::open(path)
        .map_err(|_| AgentdRootAuthorityError::Unavailable)?
        .take(limit + 1)
        .read_to_string(&mut text)
        .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
    if text.len() as u64 > limit {
        return Err(AgentdRootAuthorityError::Refused);
    }
    Ok(text)
}

pub(crate) fn check_lifetime(pidfd: &OwnedFd) -> Result<(), AgentdRootAuthorityError> {
    sample_lifetime(pidfd).map_err(|_| AgentdRootAuthorityError::Unavailable)
}

pub(super) fn check_lifetime_diagnosed(
    pidfd: &OwnedFd,
    diagnostics: &ObservationDiagnostics,
    stage: &'static str,
) -> Result<(), AgentdRootAuthorityError> {
    sample_lifetime(pidfd).map_err(|failure| {
        diagnostics.record(ObservationFailure {
            stage,
            os_error: failure.os_error,
            io_error_kind: failure.io_error_kind,
            poll_result: Some(failure.result),
            poll_revents: Some(failure.revents),
            ..Default::default()
        });
        AgentdRootAuthorityError::Unavailable
    })
}

struct LifetimeSample {
    result: i32,
    revents: i16,
    os_error: Option<i32>,
    io_error_kind: Option<std::io::ErrorKind>,
}

fn sample_lifetime(pidfd: &OwnedFd) -> Result<(), LifetimeSample> {
    let mut descriptor = libc::pollfd {
        fd: pidfd.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };
    for attempt in 0..3 {
        // SAFETY: one live descriptor and a correctly sized writable pollfd.
        // The zero timeout only samples readiness and never waits in a poll.
        let result = unsafe { libc::poll(&mut descriptor, 1, 0) };
        if result == 0 && descriptor.revents == 0 {
            return Ok(());
        }
        let error = (result < 0).then(std::io::Error::last_os_error);
        if attempt < 2
            && error
                .as_ref()
                .is_some_and(|error| error.kind() == std::io::ErrorKind::Interrupted)
        {
            continue;
        }
        return Err(LifetimeSample {
            io_error_kind: error.as_ref().map(std::io::Error::kind),
            os_error: error.and_then(|error| error.raw_os_error()),
            result,
            revents: descriptor.revents,
        });
    }
    unreachable!("the third failed poll returns its original sample")
}

#[cfg(test)]
#[path = "root_observation_stream_tests.rs"]
mod tests;
