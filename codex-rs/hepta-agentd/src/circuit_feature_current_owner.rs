//! The original guarded Cell file remains owned once and shared for readback.
//! No raw journal, replacement guard or private writer can be extracted.

use codex_hepta_neuron::CellDecisionReceiptV1;
use codex_hepta_neuron::CellExecutionError;
use codex_hepta_neuron::CellInferenceAdmissionV1;
use codex_hepta_neuron::CellOwnerSnapshotV1;
use codex_hepta_neuron::CellScopeV1;
use codex_hepta_neuron::CellStateOwnerV1;
use codex_hepta_neuron::CellStateProposalV1;

use super::current_read::OriginalPublishedReadCurrent;
use super::*;

/// Read-only Observer view. It deliberately does not implement CellStateOwner:
/// callers cannot pair it with a replacement inference port to commit a result.
pub struct PublishedCircuitCellOwnerV1<W: AnchorWitnessStore> {
    pub(super) original: Arc<Mutex<CellOwnerJournalV1<W>>>,
    pub(super) task: PublishedCircuitFeatureTaskV1,
}

pub(crate) struct PublishedCircuitCellWriterV1<W: AnchorWitnessStore>(
    PublishedCircuitCellOwnerV1<W>,
);

impl<W: AnchorWitnessStore> Clone for PublishedCircuitCellOwnerV1<W> {
    fn clone(&self) -> Self {
        Self {
            original: Arc::clone(&self.original),
            task: self.task.clone(),
        }
    }
}

impl<W: AnchorWitnessStore> PublishedCircuitCellOwnerV1<W> {
    pub(super) fn new(
        original: CellOwnerJournalV1<W>,
        task: PublishedCircuitFeatureTaskV1,
    ) -> Self {
        Self {
            original: Arc::new(Mutex::new(original)),
            task,
        }
    }

    /// Only the actual ordinary Q24 bootstrap receives mutation capability.
    pub(crate) fn writer(&self) -> PublishedCircuitCellWriterV1<W> {
        PublishedCircuitCellWriterV1(self.clone())
    }

    pub fn snapshot(&self, scope: &CellScopeV1) -> Result<CellOwnerSnapshotV1, CellExecutionError> {
        self.scope(scope)?;
        let result = self
            .original
            .lock()
            .map_err(|_| CellExecutionError::OwnerUnavailable)?
            .snapshot(scope)?;
        self.scope(scope)?;
        Ok(result)
    }

    pub fn pending_inference(
        &self,
        scope: &CellScopeV1,
    ) -> Result<Option<CellInferenceAdmissionV1>, CellExecutionError> {
        self.scope(scope)?;
        let result = self
            .original
            .lock()
            .map_err(|_| CellExecutionError::OwnerUnavailable)?
            .pending_inference(scope)?;
        self.scope(scope)?;
        Ok(result)
    }

    pub fn lookup(
        &self,
        scope: &CellScopeV1,
        operation_id: &StableId,
        semantic_request_digest: Digest32,
    ) -> Result<Option<CellDecisionReceiptV1>, CellExecutionError> {
        self.scope(scope)?;
        let result = self
            .original
            .lock()
            .map_err(|_| CellExecutionError::OwnerUnavailable)?
            .lookup(scope, operation_id, semantic_request_digest)?;
        self.scope(scope)?;
        Ok(result)
    }

    fn scope(&self, scope: &CellScopeV1) -> Result<(), CellExecutionError> {
        if scope != &self.task.source().scope {
            return Err(CellExecutionError::ScopeMismatch);
        }
        self.task
            .require_current()
            .map_err(|_| CellExecutionError::OwnerUnavailable)
    }

    pub(super) fn committed(
        &self,
        source: &CircuitTaskSourcePublicationV1,
    ) -> Result<CellDecisionReceiptV1, AgentdError> {
        let mut current = OriginalPublishedReadCurrent::individual(self);
        self.committed_with_current(source, &mut current)
    }

    pub(super) fn committed_with_current(
        &self,
        source: &CircuitTaskSourcePublicationV1,
        current: &mut OriginalPublishedReadCurrent<'_, W>,
    ) -> Result<CellDecisionReceiptV1, AgentdError> {
        OriginalPublishedReadCurrent::require(current, self)?;
        let input = source.input();
        if input != &source_input(self.task.source(), input.operation_id.clone())
            || source.bundle_digest() != self.task.definition().bundle_digest
        {
            return Err(invalid(
                "published source differs from original Feature task",
            ));
        }
        let digest = canonical_cell_step_request_digest_v1(self.task.definition(), input)
            .map_err(invalid)?;
        let owner = self.original.lock().map_err(invalid)?;
        if owner
            .pending_inference(&input.scope)
            .map_err(invalid)?
            .is_some()
        {
            return Err(invalid("ordinary Feature task remains pending"));
        }
        let decision = owner
            .lookup(&input.scope, &input.operation_id, digest)
            .map_err(invalid)?
            .ok_or_else(|| invalid("ordinary Feature step is not committed"))?;
        source.require_decision(&decision).map_err(invalid)?;
        let snapshot = owner.snapshot(&input.scope).map_err(invalid)?;
        if snapshot.revision != 1
            || snapshot.writer_epoch != self.task.0.publication.target().writer_epoch()
            || snapshot
                .checkpoint
                .as_ref()
                .map(codex_hepta_neuron::SparseCheckpoint::digest)
                != Some(decision.checkpoint_after)
            || decision.checkpoint_after != source.checkpoint_digest()
        {
            return Err(invalid(
                "original Feature checkpoint differs from committed source",
            ));
        }
        OriginalPublishedReadCurrent::require(current, self)?;
        Ok(decision)
    }
}

impl<W: AnchorWitnessStore> CellStateOwnerV1 for PublishedCircuitCellWriterV1<W> {
    fn admit_inference(
        &mut self,
        admission: CellInferenceAdmissionV1,
    ) -> Result<(), CellExecutionError> {
        self.0.scope(&admission.snapshot.scope)?;
        self.0
            .task
            .require_active()
            .map_err(|_| CellExecutionError::OwnerUnavailable)?;
        self.0
            .original
            .lock()
            .map_err(|_| CellExecutionError::OwnerUnavailable)?
            .admit_inference(admission)?;
        self.0
            .task
            .require_active()
            .map_err(|_| CellExecutionError::CommitUncertain)
    }
    fn pending_inference(
        &self,
        scope: &CellScopeV1,
    ) -> Result<Option<CellInferenceAdmissionV1>, CellExecutionError> {
        self.0.pending_inference(scope)
    }
    fn record_host_queue_age(
        &mut self,
        scope: &CellScopeV1,
        operation_id: &StableId,
        request_digest: Digest32,
        host_queue_age_micros: u64,
    ) -> Result<(), CellExecutionError> {
        self.0.scope(scope)?;
        self.0
            .original
            .lock()
            .map_err(|_| CellExecutionError::OwnerUnavailable)?
            .record_host_queue_age(scope, operation_id, request_digest, host_queue_age_micros)?;
        self.0
            .scope(scope)
            .map_err(|_| CellExecutionError::CommitUncertain)
    }
    fn lookup(
        &self,
        scope: &CellScopeV1,
        operation_id: &StableId,
        semantic_request_digest: Digest32,
    ) -> Result<Option<CellDecisionReceiptV1>, CellExecutionError> {
        self.0.lookup(scope, operation_id, semantic_request_digest)
    }
    fn snapshot(&self, scope: &CellScopeV1) -> Result<CellOwnerSnapshotV1, CellExecutionError> {
        self.0.snapshot(scope)
    }
    fn commit(
        &mut self,
        proposal: CellStateProposalV1,
        now_micros: u64,
    ) -> Result<CellDecisionReceiptV1, CellExecutionError> {
        self.0.scope(&proposal.receipt().scope)?;
        self.0
            .task
            .require_active()
            .map_err(|_| CellExecutionError::OwnerUnavailable)?;
        let result = self
            .0
            .original
            .lock()
            .map_err(|_| CellExecutionError::OwnerUnavailable)?
            .commit(proposal, now_micros)?;
        self.0
            .task
            .require_active()
            .map_err(|_| CellExecutionError::CommitUncertain)?;
        Ok(result)
    }
    fn reconcile(
        &self,
        scope: &CellScopeV1,
        operation_id: &StableId,
        operation_digest: Digest32,
    ) -> Result<Option<CellDecisionReceiptV1>, CellExecutionError> {
        self.0.scope(scope)?;
        let result = self
            .0
            .original
            .lock()
            .map_err(|_| CellExecutionError::OwnerUnavailable)?
            .reconcile(scope, operation_id, operation_digest)?;
        self.0.scope(scope)?;
        Ok(result)
    }
}
