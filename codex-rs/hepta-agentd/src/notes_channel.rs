//! Private Notes transport supplied by explicit production-host bootstrap.

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
use std::time::Instant;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_memory::NOTES_REQUEST_MAX_BYTES;
use codex_hepta_memory::NOTES_RESPONSE_MAX_BYTES;
use codex_hepta_memory::NotesPrivateChannel;
use codex_hepta_memory::NotesTargetIdentity;
use codex_hepta_memory::ProductionNotesTarget;

use crate::AgentdError;
use crate::AgentdFinalUseGrantProvider;
use crate::AgentdProductionWriterHost;

/// One end of a Session-created unnamed socketpair. The trusted bootstrap is
/// responsible for giving only its peer to the selected Notes process. Peer
/// credentials on a pre-fork socketpair identify its creator, not that child.
/// Concurrent entry fails closed and may invalidate the in-flight exchange;
/// it is never interpreted as destination proof of non-application.
pub struct AgentdNotesChannel {
    stream: Mutex<UnixStream>,
    disabled: AtomicBool,
    recovery: Option<Mutex<UnixDatagram>>,
}

impl AgentdNotesChannel {
    pub fn from_private_channel(stream: UnixStream) -> io::Result<Self> {
        if !stream.local_addr()?.is_unnamed() || !stream.peer_addr()?.is_unnamed() {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "Notes requires an inherited unnamed socketpair",
            ));
        }
        stream.set_nonblocking(false)?;
        Ok(Self {
            stream: Mutex::new(stream),
            disabled: AtomicBool::new(false),
            recovery: None,
        })
    }
    pub fn from_private_channels(effect: UnixStream, recovery: UnixDatagram) -> io::Result<Self> {
        if !recovery.local_addr()?.is_unnamed() || !recovery.peer_addr()?.is_unnamed() {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "Notes recovery requires an inherited unnamed datagram pair",
            ));
        }
        recovery.set_nonblocking(false)?;
        let mut channel = Self::from_private_channel(effect)?;
        channel.recovery = Some(Mutex::new(recovery));
        Ok(channel)
    }
}

impl NotesPrivateChannel for AgentdNotesChannel {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        if request.is_empty() || request.len() > NOTES_REQUEST_MAX_BYTES {
            return Err("invalid Notes request bound".to_string());
        }
        let mut stream = self
            .stream
            .try_lock()
            .map_err(|_| "Notes channel busy or poisoned")?;
        if self.disabled.load(Ordering::Acquire) {
            return Err("Notes channel is unavailable".to_string());
        }
        let result = exchange(&mut stream, request);
        if result.is_err() || self.disabled.load(Ordering::Acquire) {
            self.disabled.store(true, Ordering::Release);
            let _ = stream.shutdown(Shutdown::Both);
            return Err("Notes exchange is ambiguous; channel permanently closed".to_string());
        }
        result.map_err(|error| error.to_string())
    }

    fn recovery_exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        if request.is_empty() || request.len() > NOTES_REQUEST_MAX_BYTES {
            return Err("invalid Notes recovery bound".to_string());
        }
        let expected: serde_json::Value =
            serde_json::from_slice(request).map_err(|_| "invalid Notes recovery request")?;
        let action = expected["action"]
            .as_str()
            .ok_or("missing Notes recovery action")?;
        if !matches!(action, "observe" | "acknowledge_terminal") {
            return Err("Notes recovery cannot carry effects".to_string());
        }
        let channel = self
            .recovery
            .as_ref()
            .ok_or("Notes recovery endpoint was not supplied")?
            .try_lock()
            .map_err(|_| "Notes recovery busy or poisoned")?;
        let deadline = Instant::now() + Duration::from_secs(2);
        channel
            .set_write_timeout(Some(
                remaining(deadline).map_err(|error| error.to_string())?,
            ))
            .map_err(|error| error.to_string())?;
        if channel.send(request).map_err(|error| error.to_string())? != request.len() {
            return Err("partial Notes recovery datagram".to_string());
        }
        let mut buffer = [0_u8; NOTES_RESPONSE_MAX_BYTES + 1];
        // Late replies are correlated by the entire immutable target/K/payload
        // tuple and action shape. A timeout never closes this independent lane.
        for _ in 0..16 {
            channel
                .set_read_timeout(Some(
                    remaining(deadline).map_err(|error| error.to_string())?,
                ))
                .map_err(|error| error.to_string())?;
            let length = channel
                .recv(&mut buffer)
                .map_err(|error| error.to_string())?;
            if length == 0 || length > NOTES_RESPONSE_MAX_BYTES {
                continue;
            }
            let Ok(reply) = serde_json::from_slice::<serde_json::Value>(&buffer[..length]) else {
                continue;
            };
            if reply["schema_version"] != expected["schema_version"]
                || reply["target"] != expected["target"]
                || reply["operation_id"] != expected["operation_id"]
                || reply["payload_sha256"] != expected["payload_sha256"]
            {
                continue;
            }
            if action == "observe" && reply.get("result").is_some()
                || action == "acknowledge_terminal"
                    && reply["receipt_sha256"] == expected["receipt_sha256"]
                    && reply.get("status").is_some()
            {
                return Ok(buffer[..length].to_vec());
            }
        }
        Err("too many unrelated Notes recovery responses".to_string())
    }

    fn invalidate(&self) {
        self.disabled.store(true, Ordering::Release);
        if let Ok(stream) = self.stream.try_lock() {
            let _ = stream.shutdown(Shutdown::Both);
        }
    }
}

impl AgentdProductionWriterHost {
    /// Attach Notes to an independently recovered, live-verified writer. Every
    /// authority input and the private channel is mandatory; no issuer, store,
    /// signer or runtime is created here. An existing primary destination is
    /// not replaced. Additional destinations use the original host API.
    pub async fn attach_notes_target(
        self,
        identity: NotesTargetIdentity,
        stream: UnixStream,
        final_use: FinalUseAuthority,
        grants: Arc<dyn AgentdFinalUseGrantProvider>,
    ) -> Result<Self, AgentdError> {
        let target = self.notes_target(identity, stream).await?;
        self.attach_target(final_use, Arc::new(target), grants)
    }

    /// Add one fixed Notes destination while retaining the original host's
    /// existing external provider. There is no replacement or fallback issuer.
    pub async fn attach_additional_notes_target(
        self,
        identity: NotesTargetIdentity,
        stream: UnixStream,
        final_use: FinalUseAuthority,
    ) -> Result<Self, AgentdError> {
        if !self.has_target() {
            return Err(AgentdError::Invalid(
                "additional Notes destination requires the original grant provider".to_string(),
            ));
        }
        let target = self.notes_target(identity, stream).await?;
        self.attach_additional_target(final_use, Arc::new(target))
    }

    pub async fn attach_notes_recoverable_target(
        self,
        identity: NotesTargetIdentity,
        effect: UnixStream,
        recovery: UnixDatagram,
        final_use: FinalUseAuthority,
        grants: Arc<dyn AgentdFinalUseGrantProvider>,
    ) -> Result<Self, AgentdError> {
        let target = self
            .notes_recoverable_target(identity, effect, recovery)
            .await?;
        self.attach_target(final_use, Arc::new(target), grants)
    }

    pub async fn attach_additional_notes_recoverable_target(
        self,
        identity: NotesTargetIdentity,
        effect: UnixStream,
        recovery: UnixDatagram,
        final_use: FinalUseAuthority,
    ) -> Result<Self, AgentdError> {
        if !self.has_target() {
            return Err(AgentdError::Invalid(
                "additional Notes destination requires the original grant provider".to_string(),
            ));
        }
        let target = self
            .notes_recoverable_target(identity, effect, recovery)
            .await?;
        self.attach_additional_target(final_use, Arc::new(target))
    }

    async fn notes_recoverable_target(
        &self,
        identity: NotesTargetIdentity,
        effect: UnixStream,
        recovery: UnixDatagram,
    ) -> Result<ProductionNotesTarget, AgentdError> {
        if self.production_mutation().is_none() {
            return Err(AgentdError::Invalid(
                "Notes requires the independently recovered production writer".to_string(),
            ));
        }
        self.writer().verify_current_authority().await?;
        let channel = AgentdNotesChannel::from_private_channels(effect, recovery)?;
        ProductionNotesTarget::new(identity, Arc::new(channel)).map_err(AgentdError::Invalid)
    }

    async fn notes_target(
        &self,
        identity: NotesTargetIdentity,
        stream: UnixStream,
    ) -> Result<ProductionNotesTarget, AgentdError> {
        if self.production_mutation().is_none() {
            return Err(AgentdError::Invalid(
                "Notes requires the independently recovered production writer".to_string(),
            ));
        }
        self.writer().verify_current_authority().await?;
        identity.validate().map_err(AgentdError::Invalid)?;
        let channel = AgentdNotesChannel::from_private_channel(stream)?;
        ProductionNotesTarget::new(identity, Arc::new(channel)).map_err(AgentdError::Invalid)
    }
}

fn exchange(stream: &mut UnixStream, request: &[u8]) -> io::Result<Vec<u8>> {
    let deadline = Instant::now() + Duration::from_secs(2);
    write_before(stream, &(request.len() as u32).to_be_bytes(), deadline)?;
    write_before(stream, request, deadline)?;
    let mut prefix = [0; 4];
    read_before(stream, &mut prefix, deadline)?;
    let length = u32::from_be_bytes(prefix) as usize;
    if length == 0 || length > NOTES_RESPONSE_MAX_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "Notes response bound",
        ));
    }
    let mut response = vec![0; length];
    read_before(stream, &mut response, deadline)?;
    Ok(response)
}

fn remaining(deadline: Instant) -> io::Result<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|left| !left.is_zero())
        .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "Notes total deadline"))
}

fn write_before(stream: &mut UnixStream, mut bytes: &[u8], deadline: Instant) -> io::Result<()> {
    while !bytes.is_empty() {
        stream.set_write_timeout(Some(remaining(deadline)?))?;
        match stream.write(bytes) {
            Ok(0) => return Err(io::Error::new(io::ErrorKind::WriteZero, "Notes write")),
            Ok(count) => bytes = &bytes[count..],
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    }
    Ok(())
}

fn read_before(stream: &mut UnixStream, mut bytes: &mut [u8], deadline: Instant) -> io::Result<()> {
    while !bytes.is_empty() {
        stream.set_read_timeout(Some(remaining(deadline)?))?;
        match stream.read(bytes) {
            Ok(0) => return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "Notes read")),
            Ok(count) => bytes = &mut bytes[count..],
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "notes_channel_tests.rs"]
mod tests;
