//! Bind the original protected checkpoint capability to the ordinary worker.

use std::sync::Arc;

use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use tokio::sync::Semaphore;

use super::LearningIterationCheckpointErrorV1;
use super::LearningIterationCheckpointOwnerV1;
use crate::LearningIterationOwnerFutureV1;
use crate::LearningIterationOwnerPortsV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::LearningIterationStageOwnerPortsV1;
use crate::PreparedLearningIterationProposalV1;

struct CheckpointedIterationPorts {
    checkpoint: Arc<LearningIterationCheckpointOwnerV1>,
    stages: Arc<dyn LearningIterationStageOwnerPortsV1>,
    persistence: Arc<Semaphore>,
}

impl LearningIterationCheckpointOwnerV1 {
    /// Consume the already registered checkpoint capability and combine it with
    /// the host's original stage owners for `learning_iteration_channel_v1`.
    /// No path, owner registration, stage signer or fallback store is created.
    /// Synchronous Root CAS work runs off the async executor in one bounded
    /// lane. A cancelled waiter leaves that lane held until its actual I/O ends;
    /// the next call must read the same owner's CURRENT before progressing.
    pub fn with_stage_owners(
        self,
        stages: Arc<dyn LearningIterationStageOwnerPortsV1>,
    ) -> Arc<dyn LearningIterationOwnerPortsV1> {
        Arc::new(CheckpointedIterationPorts {
            checkpoint: Arc::new(self),
            stages,
            persistence: Arc::new(Semaphore::new(/*permits*/ 1)),
        })
    }
}

impl LearningIterationOwnerPortsV1 for CheckpointedIterationPorts {
    fn restore<'a>(
        &'a self,
        request: &'a LearningIterationRequestV1,
    ) -> LearningIterationOwnerFutureV1<'a, Option<LearningIterationSnapshotV1>> {
        Box::pin(async move {
            let permit = Arc::clone(&self.persistence)
                .try_acquire_owned()
                .map_err(|_| LearningIterationRuntimeErrorV1::CommitUncertain)?;
            let checkpoint = Arc::clone(&self.checkpoint);
            let request = request.clone();
            let restored = tokio::task::spawn_blocking(move || {
                let _permit = permit;
                checkpoint.restore(&request).map_err(checkpoint_error)
            })
            .await
            .map_err(|_| LearningIterationRuntimeErrorV1::CommitUncertain)??;
            if let Some(snapshot) = &restored {
                self.stages.validate_recovery(snapshot).await?;
            }
            Ok(restored)
        })
    }

    fn checkpoint<'a>(
        &'a self,
        expected_head: Digest32,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, Digest32> {
        Box::pin(async move {
            let permit = Arc::clone(&self.persistence)
                .try_acquire_owned()
                .map_err(|_| LearningIterationRuntimeErrorV1::CommitUncertain)?;
            let checkpoint = Arc::clone(&self.checkpoint);
            let snapshot = snapshot.clone();
            tokio::task::spawn_blocking(move || {
                let _permit = permit;
                checkpoint
                    .checkpoint(expected_head, &snapshot)
                    .map_err(checkpoint_error)
            })
            .await
            .map_err(|_| LearningIterationRuntimeErrorV1::CommitUncertain)?
        })
    }

    fn execute_stage<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        self.stages.execute_stage(snapshot, stage)
    }

    fn prepare_proposal<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        self.stages.prepare_proposal(snapshot)
    }

    fn receipt_attestation<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        receipt: &'a LearningIterationReceiptV1,
        now_unix_seconds: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        self.stages
            .receipt_attestation(snapshot, receipt, now_unix_seconds)
    }
}

fn checkpoint_error(error: LearningIterationCheckpointErrorV1) -> LearningIterationRuntimeErrorV1 {
    match error {
        LearningIterationCheckpointErrorV1::CommitUncertain(_) => {
            LearningIterationRuntimeErrorV1::CommitUncertain
        }
        error => LearningIterationRuntimeErrorV1::Checkpoint(error),
    }
}
