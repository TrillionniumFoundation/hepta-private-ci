//! Route learning stages to separately supplied original owners.
//!
//! This is wiring, not a trainer, signer, source of authority, or evidence that
//! original product owners are installed. The Root capability and checkpoint
//! remain under their existing host. A lost owner fails closed on recovery.

use std::sync::Arc;

use codex_hepta_learning_artifacts::LearningIterationOwnersV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

use crate::LearningIterationOwnerFutureV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::LearningIterationStageOwnerPortsV1;
use crate::PreparedLearningIterationProposalV1;

/// Named ports prevent positional swaps when the original host composes its
/// independent Experience/Dataset/Trainer/Evaluator/Proposal/Selection/NextUse
/// facilities. Each port MUST authenticate its own original durable owner.
/// A separate Arc does not by itself prove an independent process or evaluator.
pub struct LearningIterationOriginalStagePortsV1 {
    pub experience: Arc<dyn LearningIterationStageOwnerPortsV1>,
    pub dataset: Arc<dyn LearningIterationStageOwnerPortsV1>,
    pub trainer: Arc<dyn LearningIterationStageOwnerPortsV1>,
    pub evaluator: Arc<dyn LearningIterationStageOwnerPortsV1>,
    pub proposal: Arc<dyn LearningIterationStageOwnerPortsV1>,
    pub selector: Arc<dyn LearningIterationStageOwnerPortsV1>,
    pub next_use_observer: Arc<dyn LearningIterationStageOwnerPortsV1>,
}

impl LearningIterationOriginalStagePortsV1 {
    fn for_stage(&self, stage: LearningIterationStageV1) -> &Arc<dyn LearningIterationStageOwnerPortsV1> {
        match stage {
            LearningIterationStageV1::Experience => &self.experience,
            LearningIterationStageV1::Dataset => &self.dataset,
            LearningIterationStageV1::Training => &self.trainer,
            LearningIterationStageV1::Evaluation => &self.evaluator,
            LearningIterationStageV1::Proposal => &self.proposal,
            LearningIterationStageV1::Selection => &self.selector,
            LearningIterationStageV1::NextUse => &self.next_use_observer,
        }
    }
}

/// Exact owner identities are pinned at construction, not selected from a
/// recovered snapshot, model response, task payload, or local JSON descriptor.
/// The ordinary iteration worker remains responsible for signed receipt
/// validation, independent trust, checkpoint CAS and actual publication.
pub struct LearningIterationStageRouterV1 {
    owners: LearningIterationOwnersV1,
    ports: LearningIterationOriginalStagePortsV1,
}

impl LearningIterationStageRouterV1 {
    pub fn new(owners: LearningIterationOwnersV1, ports: LearningIterationOriginalStagePortsV1) -> Self {
        Self { owners, ports }
    }

    fn require_scope(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(), LearningIterationRuntimeErrorV1> {
        if snapshot.owners != self.owners {
            return Err(LearningIterationRuntimeErrorV1::WrongScope);
        }
        Ok(())
    }

    fn require_receipt_owner(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        receipt: &LearningIterationReceiptV1,
    ) -> Result<(), LearningIterationRuntimeErrorV1> {
        let stage = receipt.observation.stage();
        if receipt.operation_id != snapshot.request.operation_id
            || receipt.actor_id != *self.owners.owner(stage)
        {
            return Err(LearningIterationRuntimeErrorV1::WrongScope);
        }
        Ok(())
    }
}

impl LearningIterationStageOwnerPortsV1 for LearningIterationStageRouterV1 {
    fn validate_recovery<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, ()> {
        Box::pin(async move {
            self.require_scope(snapshot)?;
            // All original owners must reconcile existing evidence/current
            // withdrawal cuts, even if their stage has not run yet.
            for port in [
                &self.ports.experience,
                &self.ports.dataset,
                &self.ports.trainer,
                &self.ports.evaluator,
                &self.ports.proposal,
                &self.ports.selector,
                &self.ports.next_use_observer,
            ] {
                port.validate_recovery(snapshot).await?;
            }
            Ok(())
        })
    }

    fn execute_stage<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        Box::pin(async move {
            self.require_scope(snapshot)?;
            let receipt = self.ports.for_stage(stage).execute_stage(snapshot, stage).await?;
            self.require_receipt_owner(snapshot, &receipt)?;
            if receipt.observation.stage() != stage || receipt.predecessor != snapshot.head_digest {
                return Err(LearningIterationRuntimeErrorV1::WrongScope);
            }
            Ok(receipt)
        })
    }

    fn prepare_proposal<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        Box::pin(async move {
            self.require_scope(snapshot)?;
            self.ports.proposal.prepare_proposal(snapshot).await
        })
    }

    fn receipt_attestation<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        receipt: &'a LearningIterationReceiptV1,
        now_unix_seconds: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        Box::pin(async move {
            self.require_scope(snapshot)?;
            self.require_receipt_owner(snapshot, receipt)?;
            self.ports
                .for_stage(receipt.observation.stage())
                .receipt_attestation(snapshot, receipt, now_unix_seconds)
                .await
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct UnavailableStage;
    impl LearningIterationStageOwnerPortsV1 for UnavailableStage {
        fn validate_recovery<'a>(
            &'a self,
            _: &'a LearningIterationSnapshotV1,
        ) -> LearningIterationOwnerFutureV1<'a, ()> {
            Box::pin(async { Ok(()) })
        }

        fn execute_stage<'a>(
            &'a self,
            _: &'a LearningIterationSnapshotV1,
            _: LearningIterationStageV1,
        ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
            Box::pin(async { Err(LearningIterationRuntimeErrorV1::Unavailable) })
        }

        fn prepare_proposal<'a>(
            &'a self,
            _: &'a LearningIterationSnapshotV1,
        ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
            Box::pin(async { Err(LearningIterationRuntimeErrorV1::Unavailable) })
        }

        fn receipt_attestation<'a>(
            &'a self,
            _: &'a LearningIterationSnapshotV1,
            _: &'a LearningIterationReceiptV1,
            _: u64,
        ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
            Box::pin(async { Err(LearningIterationRuntimeErrorV1::Unavailable) })
        }
    }

    #[test]
    fn named_original_ports_route_all_seven_stages_without_aliasing() {
        let make_port = || -> Arc<dyn LearningIterationStageOwnerPortsV1> {
            Arc::new(UnavailableStage)
        };
        let stage_ports = LearningIterationOriginalStagePortsV1 {
            experience: make_port(),
            dataset: make_port(),
            trainer: make_port(),
            evaluator: make_port(),
            proposal: make_port(),
            selector: make_port(),
            next_use_observer: make_port(),
        };
        let stages = [
            (LearningIterationStageV1::Experience, &stage_ports.experience),
            (LearningIterationStageV1::Dataset, &stage_ports.dataset),
            (LearningIterationStageV1::Training, &stage_ports.trainer),
            (LearningIterationStageV1::Evaluation, &stage_ports.evaluator),
            (LearningIterationStageV1::Proposal, &stage_ports.proposal),
            (LearningIterationStageV1::Selection, &stage_ports.selector),
            (LearningIterationStageV1::NextUse, &stage_ports.next_use_observer),
        ];
        for (index, (stage, expected)) in stages.iter().enumerate() {
            assert!(Arc::ptr_eq(stage_ports.for_stage(*stage), expected));
            for (other_index, (_, other)) in stages.iter().enumerate() {
                if index != other_index {
                    assert!(!Arc::ptr_eq(expected, other));
                }
            }
        }
    }
}
