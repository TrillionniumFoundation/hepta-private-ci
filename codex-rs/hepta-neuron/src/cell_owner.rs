//! Bounded in-memory state owner for qualification and embedded runs.
//! Durable hosts can use CellOwnerJournalV1 or implement the same owner contract.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use codex_hepta_infer_core::neuron_feature_request_digest_v1;
use crate::cell_binding::inference_request_id;
use crate::cell_inference::feature_request;

use crate::cell_types::*;

struct Partition {
    snapshot: CellOwnerSnapshotV1,
    receipts: Vec<CellDecisionReceiptV1>,
    pending: Option<CellInferenceAdmissionV1>,
}

pub struct CellPartitionOwnerV1 {
    partitions: Vec<Partition>,
    max_partitions: usize,
    max_receipts_per_partition: usize,
}

impl CellPartitionOwnerV1 {
    pub fn new(
        max_partitions: usize,
        max_receipts_per_partition: usize,
    ) -> Result<Self, CellExecutionError> {
        if !(1..=1024).contains(&max_partitions) || !(1..=4096).contains(&max_receipts_per_partition) {
            return Err(CellExecutionError::CapacityExceeded);
        }
        Ok(Self {
            partitions: Vec::new(),
            max_partitions,
            max_receipts_per_partition,
        })
    }

    pub fn admit(
        &mut self,
        scope: CellScopeV1,
        definition: &CellDefinitionV1,
        source_frontier: Digest32,
        writer_epoch: u64,
    ) -> Result<(), CellExecutionError> {
        let definition_digest = definition.semantic_digest()?;
        if scope.cell_id != definition.cell_id
            || scope.principal_digest.is_zero()
            || source_frontier.is_zero()
            || writer_epoch == 0
        {
            return Err(CellExecutionError::ScopeMismatch);
        }
        if self.partitions.iter().any(|p| p.snapshot.scope == scope) {
            return Err(CellExecutionError::CommitConflict);
        }
        if self.partitions.len() == self.max_partitions {
            return Err(CellExecutionError::CapacityExceeded);
        }
        self.partitions.push(Partition {
            snapshot: CellOwnerSnapshotV1 {
                scope,
                definition_digest,
                source_frontier,
                writer_epoch,
                revision: 0,
                checkpoint: None,
            },
            receipts: Vec::new(),
            pending: None,
        });
        Ok(())
    }

    pub(crate) fn pending_count(&self) -> usize {
        self.partitions.iter().filter(|p| p.pending.is_some()).count()
    }

    pub(crate) fn check_admission(&self, admission: &CellInferenceAdmissionV1) -> Result<(), CellExecutionError> {
        let partition = self.partitions.iter()
            .find(|p| p.snapshot.scope == admission.snapshot.scope)
            .ok_or(CellExecutionError::ScopeMismatch)?;
        if let Some(receipt) = partition.receipts.iter().find(|r| r.operation_id == admission.operation_id) {
            return if receipt.semantic_request_digest == admission.semantic_request_digest {
                Err(CellExecutionError::OperationAlreadyCommitted)
            } else {
                Err(CellExecutionError::OperationConflict)
            };
        }
        if let Some(pending) = &partition.pending {
            return if pending.operation_id == admission.operation_id
                && pending.semantic_request_digest != admission.semantic_request_digest
            {
                Err(CellExecutionError::OperationConflict)
            } else {
                Err(CellExecutionError::InferencePending)
            };
        }
        if partition.snapshot != admission.snapshot {
            return Err(CellExecutionError::CommitConflict);
        }
        if admission.semantic_request_digest.is_zero()
            || admission.admitted_at_micros == 0
            || admission.admitted_at_micros >= admission.deadline_micros
            || admission.model_request.request_id != inference_request_id(&admission.snapshot.scope, &admission.operation_id)?
        {
            return Err(CellExecutionError::InvalidInput);
        }
        if partition.receipts.len() == self.max_receipts_per_partition || partition.snapshot.revision == u64::MAX {
            return Err(CellExecutionError::CapacityExceeded);
        }
        neuron_feature_request_digest_v1(&feature_request(&admission.model_request))
            .map_err(|_| CellExecutionError::InvalidInput)?;
        Ok(())
    }

    pub(crate) fn check_commit(
        &self,
        proposal: &CellStateProposalV1,
        now_micros: u64,
    ) -> Result<Option<CellDecisionReceiptV1>, CellExecutionError> {
        let partition = self.partitions.iter()
            .find(|p| p.snapshot.scope == proposal.snapshot.scope)
            .ok_or(CellExecutionError::ScopeMismatch)?;
        if let Some(receipt) = partition.receipts.iter()
            .find(|r| r.operation_id == proposal.receipt.operation_id)
        {
            return if receipt == &proposal.receipt {
                Ok(Some(receipt.clone()))
            } else {
                Err(CellExecutionError::OperationConflict)
            };
        }
        if now_micros < proposal.tick.monotonic_micros {
            return Err(CellExecutionError::DeadlineExceeded);
        }
        if partition.snapshot != proposal.snapshot {
            return Err(CellExecutionError::CommitConflict);
        }
        let pending = partition.pending.as_ref().ok_or(CellExecutionError::InferenceNotAdmitted)?;
        if pending.operation_id != proposal.receipt.operation_id
            || pending.semantic_request_digest != proposal.receipt.semantic_request_digest
            || pending.snapshot != proposal.snapshot
            || pending.model_request.input_digest != proposal.receipt.operation_digest
            || pending.model_request.input_digest != proposal.tick.input_digest
            || pending.deadline_micros != proposal.deadline_micros
        {
            return Err(CellExecutionError::OperationConflict);
        }
        if partition.receipts.len() == self.max_receipts_per_partition
            || partition.snapshot.revision == u64::MAX
        {
            return Err(CellExecutionError::CapacityExceeded);
        }
        Ok(None)
    }

    pub(crate) fn check_reset(
        &self,
        scope: &CellScopeV1,
        source_frontier: Digest32,
        writer_epoch: u64,
    ) -> Result<(), CellExecutionError> {
        let partition = self.partitions.iter()
            .find(|p| &p.snapshot.scope == scope)
            .ok_or(CellExecutionError::ScopeMismatch)?;
        if partition.pending.is_some() {
            return Err(CellExecutionError::InferencePending);
        }
        if source_frontier.is_zero() || writer_epoch <= partition.snapshot.writer_epoch {
            return Err(CellExecutionError::CommitConflict);
        }
        if partition.snapshot.revision == u64::MAX {
            return Err(CellExecutionError::CapacityExceeded);
        }
        Ok(())
    }

    /// Fence all prepared work. Source invalidation resets temporal state
    /// explicitly; it never reuses a checkpoint containing deleted input.
    pub fn reset_at_frontier(
        &mut self,
        scope: &CellScopeV1,
        source_frontier: Digest32,
        writer_epoch: u64,
    ) -> Result<(), CellExecutionError> {
        self.check_reset(scope, source_frontier, writer_epoch)?;
        let partition = self.partitions.iter_mut()
            .find(|p| &p.snapshot.scope == scope)
            .ok_or(CellExecutionError::ScopeMismatch)?;
        let revision = partition.snapshot.revision + 1;
        partition.snapshot.source_frontier = source_frontier;
        partition.snapshot.writer_epoch = writer_epoch;
        partition.snapshot.revision = revision;
        partition.snapshot.checkpoint = None;
        Ok(())
    }
}

impl CellStateOwnerV1 for CellPartitionOwnerV1 {
    fn admit_inference(&mut self, admission: CellInferenceAdmissionV1) -> Result<(), CellExecutionError> {
        self.check_admission(&admission)?;
        let partition = self.partitions.iter_mut()
            .find(|p| p.snapshot.scope == admission.snapshot.scope)
            .ok_or(CellExecutionError::ScopeMismatch)?;
        partition.pending = Some(admission);
        Ok(())
    }

    fn pending_inference(&self, scope: &CellScopeV1) -> Result<Option<CellInferenceAdmissionV1>, CellExecutionError> {
        self.partitions.iter().find(|p| &p.snapshot.scope == scope)
            .map(|p| p.pending.clone()).ok_or(CellExecutionError::ScopeMismatch)
    }

    fn lookup(
        &self,
        scope: &CellScopeV1,
        operation_id: &StableId,
        semantic_request_digest: Digest32,
    ) -> Result<Option<CellDecisionReceiptV1>, CellExecutionError> {
        let partition = self.partitions.iter()
            .find(|p| &p.snapshot.scope == scope)
            .ok_or(CellExecutionError::ScopeMismatch)?;
        match partition.receipts.iter().find(|r| &r.operation_id == operation_id) {
            Some(receipt) if receipt.semantic_request_digest == semantic_request_digest => {
                Ok(Some(receipt.clone()))
            }
            Some(_) => Err(CellExecutionError::OperationConflict),
            None => match &partition.pending {
                Some(pending) if &pending.operation_id == operation_id
                    && pending.semantic_request_digest != semantic_request_digest => Err(CellExecutionError::OperationConflict),
                Some(_) => Err(CellExecutionError::InferencePending),
                None => Ok(None),
            },
        }
    }

    fn snapshot(&self, scope: &CellScopeV1) -> Result<CellOwnerSnapshotV1, CellExecutionError> {
        self.partitions.iter()
            .find(|p| &p.snapshot.scope == scope)
            .map(|p| p.snapshot.clone())
            .ok_or(CellExecutionError::ScopeMismatch)
    }

    fn commit(
        &mut self,
        proposal: CellStateProposalV1,
        now_micros: u64,
    ) -> Result<CellDecisionReceiptV1, CellExecutionError> {
        if let Some(receipt) = self.check_commit(&proposal, now_micros)? {
            return Ok(receipt);
        }
        let proposal = proposal.settle_at(now_micros)?;
        let partition = self.partitions.iter_mut()
            .find(|p| p.snapshot.scope == proposal.snapshot.scope)
            .ok_or(CellExecutionError::ScopeMismatch)?;
        let revision = partition.snapshot.revision + 1;
        // No fallible operation follows publication. Exclusive mutable ownership
        // serializes writers; every scope keeps its own checkpoint and receipts.
        partition.snapshot.checkpoint = Some(proposal.checkpoint);
        partition.snapshot.revision = revision;
        partition.receipts.push(proposal.receipt.clone());
        partition.pending = None;
        Ok(proposal.receipt)
    }

    fn reconcile(
        &self,
        scope: &CellScopeV1,
        operation_id: &StableId,
        operation_digest: Digest32,
    ) -> Result<Option<CellDecisionReceiptV1>, CellExecutionError> {
        let partition = self.partitions.iter()
            .find(|p| &p.snapshot.scope == scope)
            .ok_or(CellExecutionError::ScopeMismatch)?;
        match partition.receipts.iter().find(|r| &r.operation_id == operation_id) {
            Some(receipt) if receipt.operation_digest == operation_digest => Ok(Some(receipt.clone())),
            Some(_) => Err(CellExecutionError::OperationConflict),
            None => match &partition.pending {
                Some(pending) if &pending.operation_id == operation_id
                    && pending.model_request.input_digest != operation_digest => Err(CellExecutionError::OperationConflict),
                Some(pending) if &pending.operation_id == operation_id => Err(CellExecutionError::InferencePending),
                Some(_) | None => Ok(None),
            },
        }
    }
}
