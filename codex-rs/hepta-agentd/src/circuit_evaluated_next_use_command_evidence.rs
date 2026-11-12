//! Existing read-only C evidence purpose. Only an actual original C command
//! result supplies pins; every answer rereads the same C/T/B/S/task owners.

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::super::evidence_wire;
use super::super::require_clock;
use super::Error;
use super::OriginalCircuitEvaluatedNextUseCommandOwnerV1;
use super::now;
use super::wire;
use crate::OriginalCircuitEvaluatedNextUseRemoteSourcesV1;
use crate::OriginalCircuitNextUseReceiptOwnerV1;

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitEvaluatedNextUseCommandOwnerV1<W> {
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

    pub(super) fn evidence_response(
        &self,
        bytes: &[u8],
        request_id: u64,
    ) -> Result<Vec<u8>, Error> {
        let saved = self
            .retained
            .try_lock()
            .map_err(|_| Error::Busy)?
            .as_ref()
            .ok_or(Error::Missing)?
            .clone();
        let request: evidence_wire::Request = serde_json::from_slice(bytes)?;
        let snapshot_head: Digest32 = request
            .snapshot_head
            .parse()
            .map_err(|_| Error::Binding("original evaluated C correlation head"))?;
        if request.schema != 1
            || request.operation != evidence_wire::OPERATION
            || request.request_id != request_id
            || !(1..=128).contains(&request_id)
            || request.binding != self.initial_head.to_string()
            || request.operation_id
                != self
                    .context
                    .selection
                    .snapshot()
                    .request
                    .operation_id
                    .as_str()
            || request.actor_id
                != self
                    .context
                    .selection
                    .snapshot()
                    .owners
                    .next_use_observer
                    .as_str()
            || request.predecessor != self.context.selection.snapshot().head_digest.to_string()
            || request.receipt_digest != saved.attestation().payload_digest.to_string()
            || snapshot_head.is_zero()
            || request.snapshot_head != snapshot_head.to_string()
        {
            return Err(Error::Binding("same original evaluated C evidence request"));
        }
        let started_at = now()?;
        let checked = wire::authenticate_completed(
            &self.context,
            saved.snapshot().clone(),
            saved.attestation().clone(),
            started_at,
        )?;
        if !wire::same_original(&saved, &checked) {
            return Err(Error::Binding("same original evaluated C evidence pin"));
        }
        let original = {
            let mut owner = self.owner.try_lock().map_err(|_| Error::Busy)?;
            self.runtime.block_on(
                OriginalCircuitNextUseReceiptOwnerV1::readback_evaluated_remote_completion(
                    &mut owner,
                    OriginalCircuitEvaluatedNextUseRemoteSourcesV1 {
                        snapshot: self.context.selection.snapshot(),
                        live: &self.live,
                        trainer: &self.trainer,
                        evaluator: &self.evaluator,
                        selector: &self.selector,
                    },
                ),
            )?
        };
        let current = now()?;
        require_clock(started_at, current)?;
        let checked = wire::authenticate_completed(
            &self.context,
            original.snapshot().clone(),
            original.attestation().clone(),
            current,
        )?;
        if !wire::same_original(&saved, &original) || !wire::same_original(&original, &checked) {
            return Err(Error::Binding("unchanged original evaluated C evidence"));
        }
        // The caller's snapshot head is correlation, never proof of a future
        // iteration. Root validates its own complete same-prefix checkpoint.
        Ok(serde_json::to_vec(&evidence_wire::Response {
            schema: 1,
            operation: request.operation,
            request_id,
            binding: request.binding,
            snapshot_head: request.snapshot_head,
            receipt_digest: request.receipt_digest,
            evidence: evidence_wire::Evidence::from_original(original.attestation()),
        })?)
    }
}
