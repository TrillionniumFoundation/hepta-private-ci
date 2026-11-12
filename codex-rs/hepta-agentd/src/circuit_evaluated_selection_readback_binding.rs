//! Shared authentication of the one original S evidence purpose. This owns
//! no signing custody, stream, callback or task. Both concrete hosts perform
//! their actual original-owner read between request and response validation.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_types::Digest32;

use super::Error;
use super::now;
use super::wire;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitSelectionReceiptConfigV1;
use crate::OriginalCircuitSelectionReceiptErrorV1;

pub(super) fn original_context(
    config: &OriginalCircuitSelectionReceiptConfigV1,
    selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
) -> Result<(Digest32, Digest32), Error> {
    selection.original_receipt_predecessors(now()?)?;
    let (scope, verifier, training) = selection.original_context().receipt_configuration();
    if config.decision != *selection.original_context().snapshot()
        || config.scope.binding() != scope.binding()
        || config.verifier.trust_digest() != verifier.trust_digest()
        || config.verifier.scope_digest() != verifier.scope_digest()
        || config.verifier.objective_digest() != verifier.objective_digest()
        || config.training_evidence != training
        || config.signer.principal.principal_id != selection.receipt().actor_id
    {
        return Err(Error::Binding(
            "same original evaluated Selector readback context",
        ));
    }
    let initial = LearningIterationCoordinatorV1::new(
        selection.snapshot().request.clone(),
        selection.snapshot().owners.clone(),
    )
    .map_err(OriginalCircuitSelectionReceiptErrorV1::from)?;
    Ok((
        initial.snapshot().head_digest,
        selection.original_receipt_binding(),
    ))
}

pub(super) struct ReadbackBinding<'a> {
    selection: &'a OriginalCircuitEvaluatedSelectionReceiptV1,
    initial_head: Digest32,
    binding: Digest32,
}

impl<'a> ReadbackBinding<'a> {
    pub(super) fn from_original_pins(
        selection: &'a OriginalCircuitEvaluatedSelectionReceiptV1,
        initial_head: Digest32,
        binding: Digest32,
    ) -> Self {
        Self {
            selection,
            initial_head,
            binding,
        }
    }

    pub(super) fn before_read(
        &self,
        bytes: &[u8],
        request_id: u64,
    ) -> Result<(wire::Request, u64), Error> {
        let request: wire::Request = serde_json::from_slice(bytes)?;
        let snapshot_head: Digest32 = request
            .snapshot_head
            .parse()
            .map_err(|_| Error::Binding("original evaluated Selector correlation head"))?;
        if request.schema != 1
            || request.operation != wire::OPERATION
            || request.request_id != request_id
            || !(1..=128).contains(&request_id)
            || request.binding != self.initial_head.to_string()
            || request.operation_id != self.selection.snapshot().request.operation_id.as_str()
            || request.actor_id != self.selection.snapshot().owners.selector.as_str()
            || request.predecessor != self.selection.receipt().predecessor.to_string()
            || request.receipt_digest != self.selection.attestation().payload_digest.to_string()
            || snapshot_head.is_zero()
            || request.snapshot_head != snapshot_head.to_string()
        {
            return Err(Error::Binding(
                "same original evaluated Selector evidence request",
            ));
        }
        let started_at = now()?;
        self.selection.original_receipt_predecessors(started_at)?;
        Ok((request, started_at))
    }

    pub(super) fn after_read(
        &self,
        request: wire::Request,
        started_at: u64,
        original: OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<Vec<u8>, Error> {
        let current = now()?;
        original.original_receipt_predecessors(current)?;
        if current < started_at
            || original.snapshot() != self.selection.snapshot()
            || original.receipt() != self.selection.receipt()
            || original.attestation() != self.selection.attestation()
            || original.original_receipt_binding() != self.binding
        {
            return Err(Error::Binding(
                "unchanged original evaluated Selector result",
            ));
        }
        // A future C head is correlation only. C must validate its full same-
        // prefix history before requesting this original read-only S evidence.
        Ok(serde_json::to_vec(&wire::Response {
            schema: 1,
            operation: request.operation,
            request_id: request.request_id,
            binding: request.binding,
            snapshot_head: request.snapshot_head,
            receipt_digest: request.receipt_digest,
            evidence: wire::Evidence::from_original(original.attestation()),
        })?)
    }
}
