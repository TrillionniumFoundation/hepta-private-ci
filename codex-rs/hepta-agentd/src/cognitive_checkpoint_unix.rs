//! Exclusive asynchronous lane to the independently operated root checkpoint
//! owner. This client has no signer, recovery genesis or reconnect operation.

use std::fs::File;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_memory::COGNITIVE_CHECKPOINT_FRAME_LIMIT;
use codex_hepta_memory::CheckpointDiagnostics;
use codex_hepta_memory::CheckpointFailureCause as Cause;
use codex_hepta_memory::CheckpointStage as Stage;
use codex_hepta_memory::CognitiveCheckpointRequest;
use codex_hepta_memory::CognitiveCheckpointResponse;
use codex_hepta_memory::CognitiveCheckpointTransport;
use codex_hepta_memory::ObjectiveSenderCheckpointError;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::unix::AsyncFd;

/// Exact root process identity established by the trusted launcher before
/// descriptor transfer. A numeric PID discovered from the connection is not
/// sufficient; the launcher must also retain and transfer its original pidfd.
pub struct AgentdCognitiveCheckpointPeer {
    pub pid: u32,
    pub boot_id: String,
    pub process_start_ticks: u64,
}

/// One original protected-host stream. Cancellation drops its exclusive stream
/// while the slot is empty, permanently invalidating the lane. No later call
/// can consume a late reply or obtain another connection. All Future polls use
/// nonblocking I/O, including observation of the original root process lifetime.
pub struct AgentdUnixCognitiveCheckpointTransport {
    stream: Mutex<Option<tokio::net::UnixStream>>,
    root: AsyncFd<OwnedFd>,
    timeout: Duration,
    end: Instant,
}

impl AgentdUnixCognitiveCheckpointTransport {
    /// Bootstrap inside the existing I/O-enabled runtime context, with sole
    /// ownership of an already connected stream and a pre-held root pidfd.
    /// Configuration checks read bounded procfs metadata only during bootstrap.
    pub fn from_stream(
        stream: UnixStream,
        peer: AgentdCognitiveCheckpointPeer,
        root_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, ObjectiveSenderCheckpointError> {
        Self::from_stream_for_uid(stream, peer, root_pidfd, timeout, lifetime, 0)
    }

    fn from_stream_for_uid(
        stream: UnixStream,
        peer: AgentdCognitiveCheckpointPeer,
        root_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
        uid: u32,
    ) -> Result<Self, ObjectiveSenderCheckpointError> {
        if peer.pid == 0
            || peer.pid > i32::MAX as u32
            || peer.process_start_ticks == 0
            || timeout.is_zero()
            || timeout > Duration::from_secs(5)
            || lifetime.is_zero()
            || lifetime > Duration::from_secs(300)
        {
            return Err(ObjectiveSenderCheckpointError::Refused);
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
            return Err(ObjectiveSenderCheckpointError::Refused);
        }
        let stat = bounded_text(&format!("/proc/{}/stat", peer.pid), 8192)?;
        let start = stat
            .rsplit_once(") ")
            .and_then(|(_, fields)| fields.split_whitespace().nth(19))
            .and_then(|value| value.parse::<u64>().ok());
        if start != Some(peer.process_start_ticks) {
            return Err(ObjectiveSenderCheckpointError::Refused);
        }
        check_lifetime(&root_pidfd)?;
        stream.set_nonblocking(true).map_err(unavailable)?;
        let stream = tokio::net::UnixStream::from_std(stream).map_err(unavailable)?;
        let actual = stream.peer_cred().map_err(unavailable)?;
        if actual.uid() != uid
            || actual.pid().and_then(|pid| u32::try_from(pid).ok()) != Some(peer.pid)
        {
            return Err(ObjectiveSenderCheckpointError::Refused);
        }
        // Tokio 1.52 registration exclusively owns this OwnedFd. Its number and open
        // file description remain unchanged until AsyncFd drops it; no raw fd
        // ownership or mutable access escapes this client.
        let root = AsyncFd::with_interest(root_pidfd, tokio::io::Interest::READABLE)
            .map_err(|_| ObjectiveSenderCheckpointError::Unavailable)?;
        check_lifetime(root.get_ref())?;
        Ok(Self {
            stream: Mutex::new(Some(stream)),
            root,
            timeout,
            end: Instant::now() + lifetime,
        })
    }
}

impl CognitiveCheckpointTransport for AgentdUnixCognitiveCheckpointTransport {
    async fn exchange(
        &self,
        request_json: &[u8],
    ) -> Result<Vec<u8>, ObjectiveSenderCheckpointError> {
        self.exchange_with_diagnostics(request_json, &CheckpointDiagnostics::default())
            .await
    }
    async fn exchange_diagnosed(
        &self,
        request_json: &[u8],
        diagnostics: &CheckpointDiagnostics,
    ) -> Result<Vec<u8>, ObjectiveSenderCheckpointError> {
        self.exchange_with_diagnostics(request_json, diagnostics)
            .await
    }
}
impl AgentdUnixCognitiveCheckpointTransport {
    async fn exchange_with_diagnostics(
        &self,
        request_json: &[u8],
        diagnostics: &CheckpointDiagnostics,
    ) -> Result<Vec<u8>, ObjectiveSenderCheckpointError> {
        if request_json.is_empty() || request_json.len() > COGNITIVE_CHECKPOINT_FRAME_LIMIT {
            diagnostics.fail(Cause::Size);
            return Err(ObjectiveSenderCheckpointError::Refused);
        }
        let request: CognitiveCheckpointRequest =
            serde_json::from_slice(request_json).map_err(|_| {
                diagnostics.fail(Cause::Decode);
                ObjectiveSenderCheckpointError::Refused
            })?;
        diagnostics.request(&request);
        diagnostics.stage(Stage::ReserveStream);
        let mut stream = {
            let mut slot = self.stream.try_lock().map_err(|_| {
                diagnostics.fail(Cause::SlotBusy);
                ObjectiveSenderCheckpointError::Unavailable
            })?;
            slot.take().ok_or_else(|| {
                diagnostics.fail(Cause::SlotEmpty);
                ObjectiveSenderCheckpointError::Unavailable
            })?
        };
        let mut attempt = CheckpointExchangeAttempt {
            diagnostics,
            complete: false,
        };
        // From this point cancellation or every uncertain error leaves None.
        check_lifetime(self.root.get_ref())
            .inspect_err(|_| diagnostics.fail(Cause::PeerUnavailable))?;
        let deadline = (Instant::now() + self.timeout).min(self.end);
        if deadline <= Instant::now() {
            diagnostics.fail(Cause::Deadline);
            return Err(ObjectiveSenderCheckpointError::Unavailable);
        }
        let response = tokio::select! {
            biased;
            _ = self.root.readable() => {
                diagnostics.fail(Cause::PeerUnavailable);
                return Err(ObjectiveSenderCheckpointError::Unavailable);
            },
            _ = tokio::time::sleep_until(tokio::time::Instant::from_std(deadline)) => {
                diagnostics.fail(Cause::Timeout);
                return Err(ObjectiveSenderCheckpointError::Unavailable);
            }
            response = framed_exchange(&mut stream, request_json, diagnostics) => response?,
        };
        check_lifetime(self.root.get_ref())
            .inspect_err(|_| diagnostics.fail(Cause::PeerUnavailable))?;
        diagnostics.stage(Stage::ValidateResponse);
        let parsed: CognitiveCheckpointResponse =
            serde_json::from_slice(&response).map_err(|_| {
                diagnostics.fail(Cause::Decode);
                ObjectiveSenderCheckpointError::Unavailable
            })?;
        if Instant::now() >= deadline {
            diagnostics.fail(Cause::Late);
            return Err(ObjectiveSenderCheckpointError::Unavailable);
        }
        if parsed.schema_version != 1 || parsed.request_id != request.request_id {
            diagnostics.fail(Cause::Identity);
            return Err(ObjectiveSenderCheckpointError::Unavailable);
        }
        {
            let mut slot = self.stream.try_lock().map_err(|_| {
                diagnostics.fail(Cause::SlotBusy);
                ObjectiveSenderCheckpointError::Unavailable
            })?;
            if slot.is_some() {
                diagnostics.fail(Cause::SlotBusy);
                return Err(ObjectiveSenderCheckpointError::Unavailable);
            }
            *slot = Some(stream);
        }
        attempt.complete = true;
        Ok(response)
    }
}

struct CheckpointExchangeAttempt<'a> {
    diagnostics: &'a CheckpointDiagnostics,
    complete: bool,
}
impl Drop for CheckpointExchangeAttempt<'_> {
    fn drop(&mut self) {
        if !self.complete {
            self.diagnostics.fail(Cause::Cancelled);
        }
    }
}

async fn framed_exchange(
    stream: &mut tokio::net::UnixStream,
    request: &[u8],
    diagnostics: &CheckpointDiagnostics,
) -> Result<Vec<u8>, ObjectiveSenderCheckpointError> {
    diagnostics.stage(Stage::WritePrefix);
    stream
        .write_all(&(request.len() as u32).to_be_bytes())
        .await
        .map_err(|error| diagnosed_io(error, diagnostics))?;
    diagnostics.stage(Stage::WriteBody);
    stream
        .write_all(request)
        .await
        .map_err(|error| diagnosed_io(error, diagnostics))?;
    let mut prefix = [0; 4];
    diagnostics.stage(Stage::ReadPrefix);
    stream
        .read_exact(&mut prefix)
        .await
        .map_err(|error| diagnosed_io(error, diagnostics))?;
    let length = u32::from_be_bytes(prefix) as usize;
    if length == 0 || length > COGNITIVE_CHECKPOINT_FRAME_LIMIT {
        diagnostics.fail(Cause::Size);
        return Err(ObjectiveSenderCheckpointError::Unavailable);
    }
    let mut response = vec![0; length];
    diagnostics.stage(Stage::ReadBody);
    stream
        .read_exact(&mut response)
        .await
        .map_err(|error| diagnosed_io(error, diagnostics))?;
    Ok(response)
}

fn diagnosed_io(
    error: std::io::Error,
    diagnostics: &CheckpointDiagnostics,
) -> ObjectiveSenderCheckpointError {
    diagnostics.fail(Cause::Io(error.raw_os_error()));
    unavailable(error)
}

fn bounded_text(path: &str, limit: u64) -> Result<String, ObjectiveSenderCheckpointError> {
    let mut text = String::new();
    File::open(path)
        .map_err(unavailable)?
        .take(limit + 1)
        .read_to_string(&mut text)
        .map_err(unavailable)?;
    if text.len() as u64 > limit {
        return Err(ObjectiveSenderCheckpointError::Refused);
    }
    Ok(text)
}

fn check_lifetime(pidfd: &OwnedFd) -> Result<(), ObjectiveSenderCheckpointError> {
    let mut descriptor = libc::pollfd {
        fd: pidfd.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };
    loop {
        // SAFETY: one live descriptor and a correctly sized writable pollfd.
        // The zero timeout only samples readiness and never waits in a poll.
        let result = unsafe { libc::poll(&mut descriptor, 1, 0) };
        if result == 0 && descriptor.revents == 0 {
            return Ok(());
        }
        if result < 0 && std::io::Error::last_os_error().kind() == std::io::ErrorKind::Interrupted {
            continue;
        }
        return Err(ObjectiveSenderCheckpointError::Unavailable);
    }
}

fn unavailable(_: std::io::Error) -> ObjectiveSenderCheckpointError {
    ObjectiveSenderCheckpointError::Unavailable
}

#[cfg(test)]
#[path = "cognitive_checkpoint_unix_tests.rs"]
mod tests;
