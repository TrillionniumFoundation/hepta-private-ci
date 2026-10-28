//! Bounded, independently inherited X11 input and observation streams.
use std::io::Read;
use std::io::Write;
use std::io::{self};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_memory::DesktopCapture;
use codex_hepta_memory::DesktopObservationChannel;
use codex_hepta_memory::DesktopPrivateChannel;
use codex_hepta_memory::DesktopReceipt;

pub(crate) struct PrivateStream {
    stream: Mutex<Option<UnixStream>>,
}
impl PrivateStream {
    pub(crate) fn new(stream: UnixStream) -> io::Result<Self> {
        if !stream.local_addr()?.is_unnamed() || !stream.peer_addr()?.is_unnamed() {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "desktop requires an inherited unnamed socketpair",
            ));
        }
        stream.set_nonblocking(false)?;
        Ok(Self {
            stream: Mutex::new(Some(stream)),
        })
    }
    fn exchange(&self, request: &[u8], max_response: usize) -> Result<Vec<u8>, String> {
        if request.is_empty() || request.len() > 8192 {
            return Err("desktop request bound".into());
        }
        let mut slot = self
            .stream
            .try_lock()
            .map_err(|_| "desktop channel busy or poisoned")?;
        let mut stream = slot.take().ok_or("desktop channel closed")?;
        let result = exchange(&mut stream, request, max_response);
        match result {
            Ok(bytes) => {
                *slot = Some(stream);
                Ok(bytes)
            }
            Err(_) => {
                let _ = stream.shutdown(Shutdown::Both);
                Err("ambiguous desktop exchange; channel permanently closed".into())
            }
        }
    }
    fn invalidate(&self) {
        if let Ok(mut slot) = self.stream.lock()
            && let Some(stream) = slot.take()
        {
            let _ = stream.shutdown(Shutdown::Both);
        }
    }
}

/// Effect-only handle. Observation consumers never retain this capability.
pub struct AgentdDesktopEffectChannel(pub(crate) PrivateStream);
impl DesktopPrivateChannel for AgentdDesktopEffectChannel {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        self.0.exchange(request, 2048)
    }
    fn invalidate(&self) {
        self.0.invalidate();
    }
}

/// Narrow observation handle with no effect stream and no reconnect path.
pub struct AgentdDesktopObservationChannel(pub(crate) PrivateStream);
impl DesktopObservationChannel for AgentdDesktopObservationChannel {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        let query: codex_hepta_memory::DesktopObservationRequest =
            codex_hepta_memory::DesktopObservationRequest::parse_exact(request)?;
        let (target, operation_id, request_id, payload) = match &query {
            codex_hepta_memory::DesktopObservationRequest::Observe {
                schema_version: 1,
                target,
                operation_id,
                payload_sha256,
            } => (target, Some(operation_id), None, Some(payload_sha256)),
            codex_hepta_memory::DesktopObservationRequest::Capture {
                schema_version: 1,
                target,
                request_id,
            } => (target, None, Some(request_id), None),
            _ => return Err("desktop observation schema".into()),
        };
        target.validate()?;
        let bytes = self.0.exchange(
            request,
            if request_id.is_some() {
                8 * 1024 * 1024
            } else {
                2048
            },
        )?;
        let valid = if let Some(request_id) = request_id {
            DesktopCapture::parse_exact(&bytes)
                .is_ok_and(|reply| reply.target == *target && reply.request_id == *request_id)
        } else {
            DesktopReceipt::parse_exact(&bytes).is_ok_and(|reply| {
                reply.target == *target
                    && Some(&reply.operation_id) == operation_id
                    && Some(&reply.payload_sha256) == payload
            })
        };
        if !valid {
            self.0.invalidate();
            return Err("desktop observation correlation or schema".into());
        }
        Ok(bytes)
    }
}

fn exchange(stream: &mut UnixStream, request: &[u8], max_response: usize) -> io::Result<Vec<u8>> {
    let deadline = Instant::now() + Duration::from_secs(2);
    let length = (request.len() as u32).to_be_bytes();
    for bytes in [&length[..], request] {
        let mut offset = 0;
        while offset < bytes.len() {
            stream.set_write_timeout(Some(remaining(deadline)?))?;
            let sent = stream.write(&bytes[offset..])?;
            if sent == 0 {
                return Err(io::ErrorKind::WriteZero.into());
            }
            offset += sent;
        }
    }
    let mut size = [0; 4];
    read(stream, &mut size, deadline)?;
    let size = u32::from_be_bytes(size) as usize;
    if size == 0 || size > max_response {
        return Err(io::ErrorKind::InvalidData.into());
    }
    let mut bytes = vec![0; size];
    read(stream, &mut bytes, deadline)?;
    remaining(deadline)?;
    Ok(bytes)
}
fn read(stream: &mut UnixStream, bytes: &mut [u8], deadline: Instant) -> io::Result<()> {
    let mut offset = 0;
    while offset < bytes.len() {
        stream.set_read_timeout(Some(remaining(deadline)?))?;
        let got = stream.read(&mut bytes[offset..])?;
        if got == 0 {
            return Err(io::ErrorKind::UnexpectedEof.into());
        }
        offset += got;
    }
    Ok(())
}
pub(crate) fn remaining(deadline: Instant) -> io::Result<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|v| !v.is_zero())
        .ok_or_else(|| io::ErrorKind::TimedOut.into())
}
