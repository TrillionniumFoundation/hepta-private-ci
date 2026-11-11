//! Explicit inherited Calculator transport. The independent observation handle
//! retains no reference to the effect stream or its owner.

use crate::calculator_deadline::Deadline;
use std::io;
use std::io::Read;
use std::io::Write;
use std::net::Shutdown;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_memory::CALCULATOR_REQUEST_MAX_BYTES;
use codex_hepta_memory::CALCULATOR_RESPONSE_MAX_BYTES;
use codex_hepta_memory::CalculatorPrivateChannel;
use codex_hepta_memory::CalculatorRecoveryChannel;

/// A one-shot Session bootstrap supplies both private application endpoints.
/// No pathname, peer scan or public control request can select a replacement.
pub struct AgentdCalculatorChannel {
    effect: Mutex<UnixStream>,
    disabled: AtomicBool,
    recovery: Arc<AgentdCalculatorRecoveryChannel>,
}

impl AgentdCalculatorChannel {
    pub fn from_private_channels(effect: UnixStream, recovery: UnixDatagram) -> io::Result<Self> {
        if !effect.local_addr()?.is_unnamed() || !effect.peer_addr()?.is_unnamed() {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "Calculator requires an inherited unnamed stream pair",
            ));
        }
        effect.set_nonblocking(false)?;
        Ok(Self {
            effect: Mutex::new(effect),
            disabled: AtomicBool::new(false),
            recovery: Arc::new(AgentdCalculatorRecoveryChannel::from_private_channel(
                recovery,
            )?),
        })
    }
}

impl CalculatorPrivateChannel for AgentdCalculatorChannel {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        if request.is_empty() || request.len() > CALCULATOR_REQUEST_MAX_BYTES {
            return Err("invalid Calculator effect request bound".into());
        }
        let mut stream = self
            .effect
            .try_lock()
            .map_err(|_| "Calculator effect lane busy")?;
        if self.disabled.load(Ordering::Acquire) {
            return Err("Calculator effect lane is permanently unavailable".into());
        }
        let response = exchange(&mut stream, request);
        if response.is_err() || self.disabled.load(Ordering::Acquire) {
            self.disabled.store(true, Ordering::Release);
            let _ = stream.shutdown(Shutdown::Both);
            return Err("ambiguous Calculator exchange permanently closed the effect lane".into());
        }
        response.map_err(|error| error.to_string())
    }

    fn invalidate(&self) {
        self.disabled.store(true, Ordering::Release);
        if let Ok(stream) = self.effect.try_lock() {
            let _ = stream.shutdown(Shutdown::Both);
        }
    }

    fn recovery_handle(&self) -> Arc<dyn CalculatorRecoveryChannel> {
        self.recovery.clone()
    }
}

/// Readback and receipt acknowledgement only; this type has no effect FD.
pub struct AgentdCalculatorRecoveryChannel {
    endpoint: Mutex<UnixDatagram>,
}

impl AgentdCalculatorRecoveryChannel {
    pub fn from_private_channel(endpoint: UnixDatagram) -> io::Result<Self> {
        if !endpoint.local_addr()?.is_unnamed() || !endpoint.peer_addr()?.is_unnamed() {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "Calculator recovery requires an inherited unnamed datagram pair",
            ));
        }
        endpoint.set_nonblocking(false)?;
        Ok(Self {
            endpoint: Mutex::new(endpoint),
        })
    }
}

impl CalculatorRecoveryChannel for AgentdCalculatorRecoveryChannel {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        if request.is_empty() || request.len() > CALCULATOR_REQUEST_MAX_BYTES {
            return Err("invalid Calculator recovery request bound".into());
        }
        let expected: serde_json::Value =
            serde_json::from_slice(request).map_err(|_| "invalid Calculator recovery request")?;
        let action = expected["action"]
            .as_str()
            .ok_or("missing Calculator recovery action")?;
        if !matches!(action, "read_calculator" | "observe" | "acknowledge") {
            return Err("Calculator recovery cannot carry effects".into());
        }
        let endpoint = self
            .endpoint
            .try_lock()
            .map_err(|_| "Calculator recovery lane busy")?;
        let end = Deadline::after(Duration::from_secs(2)).map_err(|error| error.to_string())?;
        endpoint
            .set_write_timeout(Some(remaining(end).map_err(|error| error.to_string())?))
            .map_err(|error| error.to_string())?;
        if endpoint.send(request).map_err(|error| error.to_string())? != request.len() {
            return Err("partial Calculator recovery datagram".into());
        }
        remaining(end).map_err(|error| error.to_string())?;
        let mut bytes = [0_u8; CALCULATOR_RESPONSE_MAX_BYTES + 1];
        for _ in 0..16 {
            endpoint
                .set_read_timeout(Some(remaining(end).map_err(|error| error.to_string())?))
                .map_err(|error| error.to_string())?;
            let length = endpoint
                .recv(&mut bytes)
                .map_err(|error| error.to_string())?;
            remaining(end).map_err(|error| error.to_string())?;
            if length == 0 || length > CALCULATOR_RESPONSE_MAX_BYTES {
                continue;
            }
            let Ok(reply) = serde_json::from_slice::<serde_json::Value>(&bytes[..length]) else {
                continue;
            };
            if reply["schema_version"] != expected["schema_version"]
                || reply["target"] != expected["target"]
            {
                continue;
            }
            if action == "read_calculator" {
                if reply["action"] == "calculator_state"
                    && reply["observation_id"] == expected["observation_id"]
                {
                    remaining(end).map_err(|error| error.to_string())?;
                    return Ok(bytes[..length].to_vec());
                }
                continue;
            }
            if reply["operation_id"] != expected["operation_id"]
                || reply["payload_sha256"] != expected["payload_sha256"]
            {
                continue;
            }
            if action == "observe" && reply.get("result").is_some()
                || action == "acknowledge"
                    && reply["action"] == "acknowledged"
                    && reply["receipt_sha256"] == expected["receipt_sha256"]
                    && reply.get("status").is_some()
            {
                remaining(end).map_err(|error| error.to_string())?;
                return Ok(bytes[..length].to_vec());
            }
        }
        Err("too many unrelated Calculator recovery replies".into())
    }
}

fn exchange(stream: &mut UnixStream, request: &[u8]) -> io::Result<Vec<u8>> {
    let end = Deadline::after(Duration::from_secs(2))?;
    write_before(stream, &(request.len() as u32).to_be_bytes(), end)?;
    write_before(stream, request, end)?;
    let mut prefix = [0_u8; 4];
    read_before(stream, &mut prefix, end)?;
    let length = u32::from_be_bytes(prefix) as usize;
    if length == 0 || length > CALCULATOR_RESPONSE_MAX_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "Calculator response bound",
        ));
    }
    let mut response = vec![0_u8; length];
    read_before(stream, &mut response, end)?;
    remaining(end)?;
    Ok(response)
}

fn remaining(end: Deadline) -> io::Result<Duration> {
    end.remaining()
}

fn write_before(stream: &mut UnixStream, mut bytes: &[u8], end: Deadline) -> io::Result<()> {
    while !bytes.is_empty() {
        stream.set_write_timeout(Some(remaining(end)?))?;
        match stream.write(bytes) {
            Ok(0) => return Err(io::Error::new(io::ErrorKind::WriteZero, "Calculator write")),
            Ok(count) => bytes = &bytes[count..],
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
        remaining(end)?;
    }
    Ok(())
}

fn read_before(stream: &mut UnixStream, mut bytes: &mut [u8], end: Deadline) -> io::Result<()> {
    while !bytes.is_empty() {
        stream.set_read_timeout(Some(remaining(end)?))?;
        match stream.read(bytes) {
            Ok(0) => {
                return Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "Calculator read",
                ));
            }
            Ok(count) => bytes = &mut bytes[count..],
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
        remaining(end)?;
    }
    Ok(())
}

#[cfg(test)]
#[path = "calculator_channel_tests.rs"]
mod tests;
