//! Existing Observer evidence purpose only. No execute, attest or write route.
//! Each request rereads the original C Observer and its live task/Trainer peers.

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::super::evidence_wire;
use super::Error;
use super::OriginalCircuitCandidateNextUseCommandOwnerV1;
use super::now;
use super::require_clock;
use super::wire;
use crate::OriginalCircuitNextUseReceiptOwnerV1;
use crate::circuit_next_use_receipt_owner::OriginalCircuitCandidateNextUseRemoteSourcesV1;

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitCandidateNextUseCommandOwnerV1<W> {
    pub(super) fn serve_evidence_channel(
        &self,
        channel: &mut HostAuthorityPeerChannel,
    ) -> Result<u64, Error> {
        for request_id in 1..=128_u64 {
            if !channel.exchange(|bytes| {
                self.evidence_response(bytes, request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)
            })? {
                return Ok(request_id - 1);
            }
        }
        Err(Error::Unavailable)
    }

    fn evidence_response(&self, bytes: &[u8], request_id: u64) -> Result<Vec<u8>, Error> {
        let started_at = now()?;
        if bytes.is_empty() || bytes.len() > 4096 {
            return Err(Error::Binding("bounded positive C evidence request"));
        }
        let request: evidence_wire::Request = serde_json::from_slice(bytes)?;
        let snapshot_head: Digest32 = request
            .snapshot_head
            .parse()
            .map_err(|_| Error::Binding("original C Observer evidence correlation head"))?;
        if request.schema != 1
            || request.operation != evidence_wire::OPERATION
            || request.request_id != request_id
            || !(1..=128).contains(&request_id)
            || request.binding != self.initial_head.to_string()
            || request.operation_id != self.context.selection.request.operation_id.as_str()
            || request.actor_id != self.context.selection.owners.next_use_observer.as_str()
            || request.predecessor != self.context.selection.head_digest.to_string()
            || snapshot_head.is_zero()
            || request.snapshot_head != snapshot_head.to_string()
        {
            return Err(Error::Binding("original C Observer evidence request"));
        }
        self.context.authenticate(started_at)?;
        let (receipt, signed) = {
            let mut owner = self.owner.try_lock().map_err(|_| Error::Busy)?;
            let original: &mut OriginalCircuitNextUseReceiptOwnerV1<W> = &mut owner;
            self.runtime
                .block_on(OriginalCircuitNextUseReceiptOwnerV1::readback_candidate_remote(
                    original,
                    OriginalCircuitCandidateNextUseRemoteSourcesV1 {
                        snapshot: &self.context.selection,
                        live: &self.live,
                        trainer: &self.trainer,
                        selector: &self.selector,
                    },
                ))?
        };
        let current = now()?;
        require_clock(started_at, current)?;
        let original = wire::authenticate_receipt(&self.context, receipt, signed, current)?;
        if request.receipt_digest != original.attestation.payload_digest.to_string() {
            return Err(Error::Binding("exact original C Observer receipt digest"));
        }
        // snapshot_head is correlation only. The server reads its fixed actual
        // original owner, never a caller snapshot or future Selection result.
        let response = evidence_wire::Response {
            schema: 1,
            operation: request.operation,
            request_id: request.request_id,
            binding: request.binding,
            snapshot_head: request.snapshot_head,
            receipt_digest: request.receipt_digest,
            evidence: evidence_wire::Evidence::from_original(&original.attestation),
        };
        Ok(serde_json::to_vec(&response)?)
    }
}
