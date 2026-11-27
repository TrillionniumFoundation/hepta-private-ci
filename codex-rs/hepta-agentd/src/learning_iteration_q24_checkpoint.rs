//! The same original Root checkpoint retained beside concrete Q24 owners.
//! Only the consumed original Root input assembly can obtain this capsule;
//! it has no constructor from a snapshot, a callback or a replacement port.

use super::*;
use crate::OriginalCellQ24LearningStageOwnersV1;

pub(crate) struct OriginalRootQ24CheckpointV1 {
    client: Arc<AgentdLearningCheckpointClientV1>,
    owners: Arc<OriginalCellQ24LearningStageOwnersV1>,
}

impl AgentdLearningCheckpointClientV1 {
    pub(crate) fn with_original_q24_checkpoint(
        self,
        owners: Arc<OriginalCellQ24LearningStageOwnersV1>,
    ) -> Result<
        (
            Arc<dyn LearningIterationOwnerPortsV1>,
            Arc<OriginalRootQ24CheckpointV1>,
        ),
        LearningIterationRuntimeErrorV1,
    > {
        let prepared = owners.prepared();
        if self.initial != *prepared.initial() || self.scope.as_ref() != Some(prepared.scope()) {
            return Err(LearningIterationRuntimeErrorV1::WrongScope);
        }
        let client = Arc::new(self);
        let capsule = Arc::new(OriginalRootQ24CheckpointV1 {
            client: Arc::clone(&client),
            owners: Arc::clone(&owners),
        });
        let ports: Arc<dyn LearningIterationOwnerPortsV1> = Arc::new(CheckpointedIterationPorts {
            initial: client.initial.clone(),
            checkpoint: Checkpoint::RootClient(client),
            stages: owners,
        });
        Ok((ports, capsule))
    }
}

impl OriginalRootQ24CheckpointV1 {
    pub(crate) fn require_original_owners(
        &self,
        owners: &Arc<OriginalCellQ24LearningStageOwnersV1>,
    ) -> Result<(), LearningIterationRuntimeErrorV1> {
        let prepared = owners.prepared();
        if !Arc::ptr_eq(&self.owners, owners)
            || self.client.initial != *prepared.initial()
            || self.client.scope.as_ref() != Some(prepared.scope())
        {
            return Err(LearningIterationRuntimeErrorV1::WrongScope);
        }
        Ok(())
    }

    // The complete historical stage must authenticate every restored original
    // receipt itself inside its one source operation. Generic restore keeps
    // the existing stage validation in CheckpointedIterationPorts.
    pub(crate) async fn restore_original(
        &self,
        request: &LearningIterationRequestV1,
    ) -> Result<Option<LearningIterationSnapshotV1>, LearningIterationRuntimeErrorV1> {
        self.require_original_owners(&self.owners)?;
        self.client.restore(request).await.map_err(checkpoint_error)
    }

    pub(crate) async fn checkpoint_original(
        &self,
        previous: Digest32,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<Digest32, LearningIterationRuntimeErrorV1> {
        self.require_original_owners(&self.owners)?;
        self.client
            .checkpoint(previous, snapshot)
            .await
            .map_err(checkpoint_error)
    }
}
