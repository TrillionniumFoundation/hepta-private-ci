//! Combine original stage owners with their registered checkpoint capability.

use std::sync::Arc;

use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use tokio::sync::Semaphore;

#[cfg(target_os = "linux")]
use super::AgentdLearningCheckpointClientV1;
use super::LearningIterationCheckpointErrorV1;
use super::LearningIterationCheckpointOwnerV1;
use crate::LearningIterationOwnerFutureV1;
use crate::LearningIterationOwnerPortsV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::LearningIterationStageOwnerPortsV1;
use crate::PreparedLearningIterationProposalV1;

enum Checkpoint {
    Registered {
        owner: Arc<LearningIterationCheckpointOwnerV1>,
        persistence: Arc<Semaphore>,
    },
    #[cfg(target_os = "linux")]
    RootClient(Box<AgentdLearningCheckpointClientV1>),
    #[cfg(target_os = "linux")]
    SameActorRootClient(Arc<AgentdLearningCheckpointClientV1>),
}

struct CheckpointedIterationPorts {
    checkpoint: Checkpoint,
    initial: LearningIterationSnapshotV1,
    stages: Arc<dyn LearningIterationStageOwnerPortsV1>,
}

impl LearningIterationCheckpointOwnerV1 {
    /// Consume the original registered Root CAS capability and stage owners.
    /// Synchronous storage runs in one bounded blocking lane. Cancellation
    /// leaves that lane held until actual I/O ends; recovery reads the same
    /// CURRENT. No pathname, owner registration or fallback store is created.
    pub fn with_stage_owners(
        self,
        stages: Arc<dyn LearningIterationStageOwnerPortsV1>,
    ) -> Arc<dyn LearningIterationOwnerPortsV1> {
        Arc::new(CheckpointedIterationPorts {
            initial: self.initial.clone(),
            checkpoint: Checkpoint::Registered {
                owner: Arc::new(self),
                persistence: Arc::new(Semaphore::new(/*permits*/ 1)),
            },
            stages,
        })
    }
}

#[cfg(target_os = "linux")]
impl AgentdLearningCheckpointClientV1 {
    /// Consume the launcher-transferred Root connection beside original stage
    /// owners. Root retains its protected CAS; the daemon receives no writer.
    /// The transport's peer, lifetime, purpose and uncertainty checks remain
    /// active. An uncertain connection has no automatic replacement or retry.
    pub fn with_stage_owners(
        self,
        stages: Arc<dyn LearningIterationStageOwnerPortsV1>,
    ) -> Arc<dyn LearningIterationOwnerPortsV1> {
        Arc::new(CheckpointedIterationPorts {
            initial: self.initial.clone(),
            checkpoint: Checkpoint::RootClient(Box::new(self)),
            stages,
        })
    }
}

#[cfg(target_os = "linux")]
impl AgentdLearningCheckpointClientV1 {
    pub(crate) fn with_original_retirable_stage_owners(
        self,
        stages: Arc<crate::OriginalCellQ24LearningStageOwnersV1>,
        identity: &crate::AgentdIdentity,
        work: &Arc<crate::same_actor_q24_phase_learning::OriginalSameActorLearningWork>,
    ) -> Result<
        (
            Arc<dyn LearningIterationOwnerPortsV1>,
            super::OriginalLearningCheckpointRetirement,
        ),
        crate::AgentdError,
    > {
        crate::OriginalCellQ24LearningStageOwnersV1::require_original_same_actor_work(
            &stages, work,
        )
        .map_err(|error| crate::AgentdError::GenerationFenced(error.to_string()))?;
        let (client, retirement) =
            AgentdLearningCheckpointClientV1::into_original_retirable_checkpoint(
                self, identity, work,
            )?;
        let ports = Arc::new(CheckpointedIterationPorts {
            initial: client.initial.clone(),
            checkpoint: Checkpoint::SameActorRootClient(client),
            stages,
        });
        Ok((ports, retirement))
    }
}

impl CheckpointedIterationPorts {
    fn require_scope(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(), LearningIterationRuntimeErrorV1> {
        if snapshot.request != self.initial.request || snapshot.owners != self.initial.owners {
            return Err(LearningIterationRuntimeErrorV1::WrongScope);
        }
        Ok(())
    }
}

impl LearningIterationOwnerPortsV1 for CheckpointedIterationPorts {
    fn frozen_scope_binding(&self) -> Option<Digest32> {
        match &self.checkpoint {
            Checkpoint::Registered { owner, .. } => owner.frozen_scope_binding(),
            #[cfg(target_os = "linux")]
            Checkpoint::RootClient(client) => client.frozen_scope_binding(),
            #[cfg(target_os = "linux")]
            Checkpoint::SameActorRootClient(client) => client.frozen_scope_binding(),
        }
    }

    fn restore<'a>(
        &'a self,
        request: &'a LearningIterationRequestV1,
    ) -> LearningIterationOwnerFutureV1<'a, Option<LearningIterationSnapshotV1>> {
        Box::pin(async move {
            let restored = match &self.checkpoint {
                Checkpoint::Registered { owner, persistence } => {
                    let permit = Arc::clone(persistence)
                        .try_acquire_owned()
                        .map_err(|_| LearningIterationRuntimeErrorV1::CommitUncertain)?;
                    let owner = Arc::clone(owner);
                    let request = request.clone();
                    tokio::task::spawn_blocking(move || {
                        let _permit = permit;
                        owner.restore(&request).map_err(checkpoint_error)
                    })
                    .await
                    .map_err(|_| LearningIterationRuntimeErrorV1::CommitUncertain)??
                }
                #[cfg(target_os = "linux")]
                Checkpoint::RootClient(client) => {
                    client.restore(request).await.map_err(checkpoint_error)?
                }
                #[cfg(target_os = "linux")]
                Checkpoint::SameActorRootClient(client) => {
                    AgentdLearningCheckpointClientV1::restore(client, request)
                        .await
                        .map_err(checkpoint_error)?
                }
            };
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
            match &self.checkpoint {
                Checkpoint::Registered { owner, persistence } => {
                    let permit = Arc::clone(persistence)
                        .try_acquire_owned()
                        .map_err(|_| LearningIterationRuntimeErrorV1::CommitUncertain)?;
                    let owner = Arc::clone(owner);
                    let snapshot = snapshot.clone();
                    tokio::task::spawn_blocking(move || {
                        let _permit = permit;
                        owner
                            .checkpoint(expected_head, &snapshot)
                            .map_err(checkpoint_error)
                    })
                    .await
                    .map_err(|_| LearningIterationRuntimeErrorV1::CommitUncertain)?
                }
                #[cfg(target_os = "linux")]
                Checkpoint::RootClient(client) => client
                    .checkpoint(expected_head, snapshot)
                    .await
                    .map_err(checkpoint_error),
                #[cfg(target_os = "linux")]
                Checkpoint::SameActorRootClient(client) => {
                    AgentdLearningCheckpointClientV1::checkpoint(client, expected_head, snapshot)
                        .await
                        .map_err(checkpoint_error)
                }
            }
        })
    }

    fn execute_stage<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        Box::pin(async move {
            self.require_scope(snapshot)?;
            self.stages.execute_stage(snapshot, stage).await
        })
    }

    fn prepare_proposal<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        Box::pin(async move {
            self.require_scope(snapshot)?;
            self.stages.prepare_proposal(snapshot).await
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
            self.stages
                .receipt_attestation(snapshot, receipt, now_unix_seconds)
                .await
        })
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
