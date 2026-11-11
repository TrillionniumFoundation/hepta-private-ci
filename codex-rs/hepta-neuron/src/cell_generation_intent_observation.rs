//! One healthy owner cut for an exact original intent. In particular, receipt
//! cost is copied from that receipt, never inferred from task ledger deltas.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::CellGenerationJournalV2;
use crate::AnchorWitnessStore;
use crate::CellGenerationErrorV2;
use crate::CellGenerationIntentV2;
use crate::CellGenerationReceiptV2;
use crate::CellGenerationRequestV2;
use crate::CellGenerationScopeV2;
use crate::CellOutputChunkV2;

#[derive(Clone, Debug, Eq, PartialEq)]
enum IntentState {
    Missing,
    Pending(CellGenerationRequestV2),
    Committed {
        receipt: CellGenerationReceiptV2,
        pending_output: Option<CellOutputChunkV2>,
    },
}

/// Facts sampled by the exclusive journal owner. Private fields and no
/// deserializer prevent callers from minting or combining separate receipt,
/// cost and output samples. This observation grants no execution authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellGenerationIntentObservationV1 {
    owner_checkpoint: Digest32,
    scope: CellGenerationScopeV2,
    manifest_digest: [u8; 32],
    intent: CellGenerationIntentV2,
    state: IntentState,
}

impl CellGenerationIntentObservationV1 {
    pub fn owner_checkpoint(&self) -> Digest32 {
        self.owner_checkpoint
    }

    pub fn scope(&self) -> &CellGenerationScopeV2 {
        &self.scope
    }

    pub fn manifest_digest(&self) -> [u8; 32] {
        self.manifest_digest
    }

    pub fn intent(&self) -> &CellGenerationIntentV2 {
        &self.intent
    }

    /// Absence stays uncertain. It is not a no-contact proof, an execution
    /// admission, a refundable reservation or a terminal completion.
    pub fn is_missing(&self) -> bool {
        matches!(self.state, IntentState::Missing)
    }

    pub fn pending_request(&self) -> Option<&CellGenerationRequestV2> {
        match &self.state {
            IntentState::Pending(request) => Some(request),
            IntentState::Missing | IntentState::Committed { .. } => None,
        }
    }

    /// The immutable original receipt, including its original cost entries.
    /// Later preparation, recovery or delivery costs belong to the task ledger
    /// and cannot be silently attributed to this particular computation.
    pub fn receipt(&self) -> Option<&CellGenerationReceiptV2> {
        match &self.state {
            IntentState::Committed { receipt, .. } => Some(receipt),
            IntentState::Missing | IntentState::Pending(_) => None,
        }
    }

    /// Only this receipt's currently unacknowledged output. None does not prove
    /// that the computation produced no bytes: an earlier ACK may have removed
    /// its outbox. A delivery bridge must retain its original transfer first.
    pub fn pending_output(&self) -> Option<&CellOutputChunkV2> {
        match &self.state {
            IntentState::Committed { pending_output, .. } => pending_output.as_ref(),
            IntentState::Missing | IntentState::Pending(_) => None,
        }
    }
}

impl<W: AnchorWitnessStore> CellGenerationJournalV2<W> {
    /// Read only the exact original intent at one healthy owner cut. This does
    /// not read the worker, move clocks, append costs, ACK output or settle work.
    pub fn observe_intent(
        &self,
        intent: &CellGenerationIntentV2,
    ) -> Result<CellGenerationIntentObservationV1, CellGenerationErrorV2> {
        StableId::new(&intent.operation_id).map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        if [
            intent.task_digest,
            intent.source_frontier,
            intent.predecessor_digest,
            intent.input_digest,
        ]
        .contains(&[0; 32])
            || intent.deadline_micros == 0
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let receipt = self.receipt_for_intent(intent)?;
        let pending = self
            .pending_request()?
            .filter(|pending| pending.operation_id == intent.operation_id);
        if let Some(pending) = pending
            && &pending.intent()? != intent
        {
            return Err(CellGenerationErrorV2::Conflict);
        }
        let output = self
            .pending_output()?
            .filter(|chunk| chunk.operation_id == intent.operation_id);
        if output.is_some_and(|chunk| {
            receipt
                .as_ref()
                .is_none_or(|receipt| chunk.request_digest != receipt.request_digest)
        }) || (receipt.is_some() && pending.is_some())
        {
            return Err(CellGenerationErrorV2::Corrupt);
        }
        let state = match (receipt, pending) {
            (Some(receipt), None) => IntentState::Committed {
                receipt,
                pending_output: output.cloned(),
            },
            (None, Some(request)) => IntentState::Pending(request.clone()),
            (None, None) => IntentState::Missing,
            (Some(_), Some(_)) => return Err(CellGenerationErrorV2::Corrupt),
        };
        let snapshot = self.snapshot()?;
        Ok(CellGenerationIntentObservationV1 {
            owner_checkpoint: self.continuity_checkpoint()?,
            scope: snapshot.scope.clone(),
            manifest_digest: snapshot.manifest_digest,
            intent: intent.clone(),
            state,
        })
    }
}
