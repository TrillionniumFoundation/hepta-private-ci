//! Closed Material-only reader. The only remote constructor is called while
//! consuming the actual Material pair; local Source observers keep their old
//! implementation. A wire value cannot construct a Driver receipt or writer.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_neuron::{AnchorWitnessStore, FileAnchorWitnessStore};
use codex_hepta_types::{Digest32, StableId};

use super::{CircuitTaskSourceReadbackV1, OriginalReadback};
use super::super::{CircuitTaskSourcePublicationV1, Error, codec};
use crate::{AgentdIdentity, AgentdRootAuthorityPeer, OriginalCellQ24MaterialReceiptConfigV1};
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

#[path = "circuit_task_source_material_wire.rs"]
pub(crate) mod wire;

struct Channel {
    original: HostAuthorityPeerChannel,
    next: u64,
}

pub(super) struct Client {
    slot: Mutex<Option<Channel>>,
    config: OriginalCellQ24MaterialReceiptConfigV1,
    identity: AgentdIdentity,
    binding: Digest32,
    nonce: [u8; 16],
    timeout: Duration,
    end: Instant,
}

impl CircuitTaskSourceReadbackV1<FileAnchorWitnessStore> {
    /// Private consuming-pair factory only. FileAnchorWitnessStore remains a
    /// type parameter for the original local branch; no witness/file is made
    /// for this remote branch. The actual witness is read by the Root owner.
    pub(crate) fn from_original_material_root_stream(
        stream: UnixStream,
        root: AgentdRootAuthorityPeer,
        root_pidfd: OwnedFd,
        config: OriginalCellQ24MaterialReceiptConfigV1,
        identity: AgentdIdentity,
        nonce: [u8; 16],
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        if timeout.is_zero() || timeout > wire::TIMEOUT
            || lifetime.is_zero() || lifetime > Duration::from_secs(300)
            || nonce == [0; 16]
        { return Err(Error::InvalidBinding); }
        let end = Instant::now() + lifetime;
        let binding = wire::context(&config)?;
        let original = original_owner_command_channel_v1(stream, root, /*uid*/ 0,
            root_pidfd, timeout, lifetime).map_err(|_| Error::Unavailable)?;
        if wire::context(&config)? != binding { return Err(Error::InvalidBinding); }
        wire::before(end)?;
        Ok(Self { original: OriginalReadback::RootMaterial(Arc::new(Client {
            slot: Mutex::new(Some(Channel { original, next: 1 })), config, identity,
            binding, nonce, timeout, end,
        })) })
    }
}

impl Client {
    pub(super) fn read(&self, identity: &AgentdIdentity, run: &StableId)
        -> Result<CircuitTaskSourcePublicationV1, Error>
    {
        if identity != &self.identity || run != &self.config.initial.request.source_run_id {
            return Err(Error::InvalidBinding);
        }
        let mut channel = self.slot.try_lock().map_err(|_| Error::Unavailable)?
            .take().ok_or(Error::Unavailable)?;
        let deadline = (Instant::now() + self.timeout).min(self.end);
        wire::before(deadline)?;
        if wire::context(&self.config)? != self.binding { return Err(Error::InvalidBinding); }
        let request = wire::request(self.binding, self.nonce, channel.next)?;
        channel.next = channel.next.checked_add(1).ok_or(Error::Unavailable)?;
        let response = channel.original.request(&request).map_err(|_| Error::CommitUncertain)?;
        wire::before(deadline)?;
        let payload = wire::read_response(&request, &response)?;
        // Only this successful fixed Root exchange reaches the private decoder.
        // No public/raw-result overload manufactures an original publication.
        let observed = decode_current_root_payload(payload)?;
        crate::cell_q24_dataset::require_source(identity, &observed, &self.config.initial.request)
            .map_err(|_| Error::InvalidBinding)?;
        channel.original.check_peer_lifetime().map_err(|_| Error::Unavailable)?;
        if wire::context(&self.config)? != self.binding { return Err(Error::InvalidBinding); }
        let mut slot = self.slot.try_lock().map_err(|_| Error::Unavailable)?;
        wire::before(deadline)?;
        *slot = Some(channel);
        Ok(observed)
    }
}

pub(super) fn decode_current_root_payload(payload: &[u8]) -> Result<CircuitTaskSourcePublicationV1, Error> {
    let mut reader = wire::Reader::new(payload, b"HCMATPUB1")?;
    let binding = reader.digest()?;
    if binding.is_zero() { return Err(Error::InvalidBinding); }
    let request = reader.bytes()?;
    let saved = reader.bytes()?;
    let result = reader.bytes()?;
    reader.end()?;
    let record = codec::original_record(request)?;
    let input = codec::decode_input(saved)?;
    let (history_digest, output) = codec::publication(result, saved)?;
    let (bundle_digest, checkpoint_digest) = codec::decision_metadata(result)?;
    Ok(CircuitTaskSourcePublicationV1 {
        record, input, output, history_digest, bundle_digest, checkpoint_digest,
        publication_digest: Digest32::of_parts(&[
            b"hepta.circuit.original-source-publication.v1\0", binding.as_array(),
            request, saved, result,
        ]),
        result_bytes: result.to_vec(),
    })
}

impl<W: AnchorWitnessStore> CircuitTaskSourceReadbackV1<W> {
    /// Root serializes only data just read through the actual local owner.
    /// Another remote reader cannot be used as a Root source for this loan.
    pub(crate) fn encode_original_material_publication(
        &self, identity: &AgentdIdentity, expected: &CircuitTaskSourcePublicationV1,
    ) -> Result<Vec<u8>, Error> {
        let OriginalReadback::Local(original) = &self.original else {
            return Err(Error::InvalidBinding);
        };
        if original.read_publication(identity, expected.original_record())? != *expected {
            return Err(Error::InvalidBinding);
        }
        let mut owner = original.0.try_lock().map_err(|_| Error::Unavailable)?;
        let request = owner.request(identity, expected.original_record())?;
        let request_bytes = codec::request(&request, expected.original_record())?;
        owner.require_bytes("request", &request.start.run_id, &request_bytes)?;
        let saved = owner.read("input", &request.start.run_id)?;
        let result = owner.read("result", &request.start.run_id)?;
        if codec::decode_input(&saved)? != *expected.input() || result != expected.result_bytes() {
            return Err(Error::InvalidBinding);
        }
        let mut out = wire::Writer::new(b"HCMATPUB1");
        out.digest(owner.binding)?;
        out.bytes(&request_bytes)?;
        out.bytes(&saved)?;
        out.bytes(&result)?;
        owner.require_active(&request.start.run_id)?;
        owner.require_current()?;
        let payload = out.finish();
        wire::bounded(&payload)?;
        Ok(payload)
    }
}

#[cfg(test)]
#[path = "circuit_task_source_material_tests.rs"]
mod tests;
