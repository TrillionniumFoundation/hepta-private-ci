//! The Model payload retains the same concrete original owner aggregate.
//! Copying a receipt, tag or digest cannot recreate this dispatch capability.

use std::sync::Arc;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use tokio::runtime::Handle;

use super::Q24StageOwners;
use super::Q24StageState;
use super::unavailable;
use crate::CellQ24ModelProposalInputsV1;
use crate::LearningIterationProposalPayloadV1;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::OriginalCellQ24TrainingStageV1;
use crate::PreparedLearningIterationProposalV1;
use codex_hepta_neuron::FileAnchorWitnessStore;

#[derive(Clone)]
pub struct OriginalCellQ24ModelDispatchV1 {
    inner: Arc<Q24StageState>,
    snapshot: LearningIterationSnapshotV1,
}

impl std::fmt::Debug for OriginalCellQ24ModelDispatchV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("OriginalCellQ24ModelDispatchV1")
            .field("operation", &self.snapshot.request.operation_id)
            .field("predecessor", &self.snapshot.head_digest)
            .finish_non_exhaustive()
    }
}

pub(super) fn prepare(
    inner: Arc<Q24StageState>,
    snapshot: &LearningIterationSnapshotV1,
) -> Result<PreparedLearningIterationProposalV1, Error> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
    if coordinator.next_stage() != Some(LearningIterationStageV1::Proposal) {
        return Err(Error::WrongScope);
    }
    let candidate = coordinator.candidate().ok_or(Error::WrongScope)?;
    Ok(PreparedLearningIterationProposalV1 {
        iteration_head: snapshot.head_digest,
        candidate_bundle: candidate.digest().map_err(|_| Error::WrongScope)?,
        evaluation_evidence: snapshot
            .receipts
            .last()
            .ok_or(Error::WrongScope)?
            .evidence_digest,
        payload: LearningIterationProposalPayloadV1::Model(Box::new(
            OriginalCellQ24ModelDispatchV1 {
                inner,
                snapshot: snapshot.clone(),
            },
        )),
    })
}

impl OriginalCellQ24ModelDispatchV1 {
    pub(crate) async fn commit_for(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<LearningIterationReceiptV1, Error> {
        if snapshot != &self.snapshot {
            return Err(Error::WrongScope);
        }
        self.inner.require_snapshot(snapshot)?;
        let inner = Arc::clone(&self.inner);
        let snapshot = snapshot.clone();
        self.inner
            .in_lane(
                move |owners,
                      training: &OriginalCellQ24TrainingStageV1<
                    FileAnchorWitnessStore,
                    FileAnchorWitnessStore,
                >,
                      runtime| {
                    Ok(owners
                        .model_action(&inner, training, runtime, &snapshot, Action::CommitProposal)?
                        .0)
                },
            )
            .await
    }
}

pub(super) enum Action {
    CommitProposal,
    ReadProposal,
    CommitDecision,
    ReadDecision,
}

impl Q24StageOwners {
    pub(super) fn model_action(
        &mut self,
        inner: &Q24StageState,
        training: &OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
        runtime: &Handle,
        snapshot: &LearningIterationSnapshotV1,
        action: Action,
    ) -> Result<(LearningIterationReceiptV1, Option<SignedLearningEvidenceV1>), Error> {
        if self.root_evaluation.is_some() {
            return self.original_root_model_action(inner, training, runtime, snapshot, action);
        }
        let completed = runtime
            .block_on(training.readback(&inner.dataset_cut))
            .map_err(unavailable)?;
        let mut training_cut =
            LearningIterationCoordinatorV1::from_snapshot(inner.dataset_cut.clone())?;
        training_cut.record(
            completed.receipt.clone(),
            completed.receipt.observed_unix_seconds,
        )?;
        if !snapshot
            .receipts
            .starts_with(&training_cut.snapshot().receipts)
        {
            return Err(Error::WrongScope);
        }
        let Self {
            factory,
            local,
            evaluation,
            ..
        } = self;
        let factory: &mut crate::AgentdRootQ24ModelFactoryV1 = factory;
        let local: &mut crate::OriginalCellQ24LocalDecisionOwnerV1<FileAnchorWitnessStore> = local;
        let evaluation: &mut crate::OriginalCellQ24EvaluationStageV1 = evaluation
            .as_mut()
            .ok_or(Error::OwnerUnavailable("original B handoff"))?;
        evaluation.require_training(training_cut.snapshot(), inner.prepared.scope())?;
        let before = runtime.block_on(evaluation.complete(snapshot, /*read_only*/ true))?;
        if snapshot
            .receipts
            .get(training_cut.snapshot().receipts.len())
            != Some(&before.0)
        {
            return Err(Error::WrongScope);
        }
        let execution = evaluation.read_execution()?;
        let request = evaluation.qualification_request()?;
        let inputs = CellQ24ModelProposalInputsV1 {
            training_cut: training_cut.snapshot(),
            training_attestation: &completed.attestation,
            runner: &evaluation.runner,
            evaluation: &execution,
            qualification: &evaluation.qualification,
            request: &request,
        };
        let result = training.with_original_trainer(
            &inner.dataset_cut,
            |trainer: &mut crate::CellQ24TrainingOwnerV1<FileAnchorWitnessStore>| match action {
                Action::CommitProposal => runtime
                    .block_on(factory.commit_or_readback(trainer, &inner.dataset_cut, &inputs))
                    .map(|value| (value.learning_receipt().clone(), None))
                    .map_err(unavailable),
                Action::ReadProposal => runtime
                    .block_on(factory.readback(trainer, &inner.dataset_cut, &inputs))
                    .map(|value| (value.learning_receipt().clone(), None))
                    .map_err(unavailable),
                Action::CommitDecision => runtime
                    .block_on(local.attest_original_decision(
                        factory,
                        trainer,
                        &inner.dataset_cut,
                        &inputs,
                        snapshot,
                    ))
                    .map(|(receipt, signed)| (receipt, Some(signed)))
                    .map_err(unavailable),
                Action::ReadDecision => runtime
                    .block_on(local.readback(
                        factory,
                        trainer,
                        &inner.dataset_cut,
                        &inputs,
                        snapshot,
                    ))
                    .map(|(receipt, signed)| (receipt, Some(signed)))
                    .map_err(unavailable),
            },
        )?;
        if runtime.block_on(evaluation.complete(snapshot, /*read_only*/ true))? != before {
            return Err(Error::CommitUncertain);
        }
        Ok(result)
    }
}
