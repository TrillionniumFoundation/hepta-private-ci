//! An actual Root/Q24 bootstrap's stage context. No callback, raw snapshot,
//! replacement ports or caller-selected trust can construct this capsule.

use super::*;
use crate::OriginalCellQ24LearningStageOwnersV1;
use crate::cell_composed_q24::OriginalPreparedReadV1;
use crate::learning_iteration_checkpoint::OriginalRootQ24CheckpointV1;

pub(crate) enum OriginalHistoricalStageAdmissionV1 {
    ReadOnly,
    NewWork,
}

pub(crate) struct OriginalHistoricalStageContextV1 {
    state: Arc<AgentdState>,
    original: Arc<OriginalCellQ24LearningStageOwnersV1>,
    checkpoint: Arc<OriginalRootQ24CheckpointV1>,
    source: Arc<historical_source::RegisteredHistoricalLearningSourceV1>,
    verifier: LearningEvidenceVerifierV1,
}

impl OriginalHistoricalStageContextV1 {
    pub(super) fn from_original_bootstrap(
        bootstrap: &LearningIterationRuntimeBootstrapV1,
        state: Arc<AgentdState>,
    ) -> Result<Arc<Self>, LearningIterationRuntimeErrorV1> {
        bootstrap
            .require_identity(state.identity())
            .map_err(|_| LearningIterationRuntimeErrorV1::WrongScope)?;
        let original: &Arc<OriginalCellQ24LearningStageOwnersV1> = bootstrap
            .original_q24
            .as_ref()
            .ok_or(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                "actual historical Q24 aggregate",
            ))?;
        let checkpoint: &Arc<OriginalRootQ24CheckpointV1> = bootstrap
            .original_q24_checkpoint
            .as_ref()
            .ok_or(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                "same original Q24 Root checkpoint",
            ))?;
        let source = bootstrap
            .historical_source
            .as_ref()
            .ok_or(LearningIterationRuntimeErrorV1::WrongScope)?;
        let prepared = OriginalCellQ24LearningStageOwnersV1::prepared(original);
        bootstrap.require_frozen_scope(&prepared.initial().request)?;
        if !bootstrap.enforce_circuit_admission
            || bootstrap.retained_source.is_some()
            || bootstrap.scope.as_ref() != Some(prepared.scope())
            || bootstrap.owners != prepared.initial().owners
            || bootstrap.verifier.trust_digest() != prepared.initial().owners.evidence_trust_digest
            || bootstrap.verifier.objective_digest()
                != prepared.initial().request.envelope.objective_digest
            || source.request() != &prepared.initial().request
        {
            return Err(LearningIterationRuntimeErrorV1::WrongScope);
        }
        OriginalRootQ24CheckpointV1::require_original_owners(checkpoint, original)?;
        Ok(Arc::new(Self {
            state,
            original: Arc::clone(original),
            checkpoint: Arc::clone(checkpoint),
            source: Arc::clone(source),
            verifier: bootstrap.verifier.clone(),
        }))
    }

    pub(crate) fn require_original_aggregate(
        &self,
        original: &OriginalCellQ24LearningStageOwnersV1,
    ) -> Result<(), LearningIterationRuntimeErrorV1> {
        if !std::ptr::eq(self.original.as_ref(), original) {
            return Err(LearningIterationRuntimeErrorV1::WrongScope);
        }
        OriginalRootQ24CheckpointV1::require_original_owners(&self.checkpoint, &self.original)
    }

    pub(crate) fn require_in_operation(
        &self,
        read: &OriginalPreparedReadV1<'_>,
        admission: OriginalHistoricalStageAdmissionV1,
    ) -> Result<(), LearningIterationRuntimeErrorV1> {
        self.require_original_aggregate(self.original.as_ref())?;
        self.current_time()?;
        historical_source::RegisteredHistoricalLearningSourceV1::require_original_stage_operation(
            &self.source,
            self.state.identity(),
            read,
        )
        .map_err(|_| LearningIterationRuntimeErrorV1::WrongScope)?;
        if matches!(admission, OriginalHistoricalStageAdmissionV1::NewWork)
            && self.current_time()?
                >= self
                    .original
                    .prepared()
                    .initial()
                    .request
                    .envelope
                    .expiry_unix_seconds
        {
            return Err(LearningIterationRuntimeErrorV1::DeadlineExceeded);
        }
        Ok(())
    }

    pub(crate) fn current_time(&self) -> Result<u64, LearningIterationRuntimeErrorV1> {
        require_ready(&self.state)?;
        if !self
            .state
            .automation_admission_ready()
            .map_err(|_| LearningIterationRuntimeErrorV1::Unavailable)?
        {
            return Err(LearningIterationRuntimeErrorV1::Unavailable);
        }
        now_unix_seconds()
    }

    pub(crate) fn verifier(&self) -> &LearningEvidenceVerifierV1 {
        &self.verifier
    }

    pub(crate) async fn restore_checkpoint(
        &self,
        request: &LearningIterationRequestV1,
    ) -> Result<Option<LearningIterationSnapshotV1>, LearningIterationRuntimeErrorV1> {
        OriginalRootQ24CheckpointV1::restore_original(&self.checkpoint, request).await
    }

    pub(crate) async fn commit_checkpoint(
        &self,
        previous: Digest32,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<Digest32, LearningIterationRuntimeErrorV1> {
        OriginalRootQ24CheckpointV1::checkpoint_original(&self.checkpoint, previous, snapshot).await
    }
}
