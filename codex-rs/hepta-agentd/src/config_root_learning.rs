//! Retain the original Root learning capability until actual stage assembly.

use std::sync::Arc;

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdRootLearningInputsV1;
use crate::LearningIterationHandleV1;
use crate::LearningIterationStageOwnerPortsV1;

impl AgentdConfig {
    pub(crate) async fn with_root_q24_learning_owners(
        mut self,
        mut factory: crate::AgentdRootQ24ModelFactoryV1,
        original: crate::OriginalCellQ24LearningInputsV1,
    ) -> Result<
        (
            Self,
            LearningIterationHandleV1,
            Arc<crate::OriginalCellQ24LearningStageOwnersV1>,
        ),
        AgentdError,
    > {
        let inputs: AgentdRootLearningInputsV1 =
            self.root_learning_inputs.take().ok_or_else(|| {
                AgentdError::Invalid("original Root learning handoff is required".into())
            })?;
        inputs.require_prepared_q24(&original.prepared)?;
        if original.prepared.initial().owners.evidence_trust_digest
            != original.verifier.trust_digest()
            || !(1..=64).contains(&original.queue_capacity)
        {
            return Err(AgentdError::Invalid(
                "original Q24 trust and bounded queue required".into(),
            ));
        }
        factory.require_current().await?;
        let local = original
            .local
            .open_original_local_decision(&original.prepared, original.verifier.clone(), &factory)
            .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
        let owners = crate::OriginalCellQ24LearningStageOwnersV1::from_original_owners(
            original.prepared,
            original.sources,
            original.verifier.clone(),
            original.training,
            local,
            factory,
            original.mode,
        )
        .await
        .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
        let (handle, bootstrap) = inputs.into_q24_learning_runtime(
            Arc::clone(&owners),
            original.verifier,
            original.queue_capacity,
        )?;
        Ok((
            self.with_learning_iteration_bootstrap(bootstrap)?,
            handle,
            owners,
        ))
    }

    pub(crate) fn with_root_learning_inputs(
        mut self,
        inputs: AgentdRootLearningInputsV1,
    ) -> Result<Self, AgentdError> {
        inputs.require_identity(&self.identity)?;
        if self.root_learning_inputs.is_some() || self.learning_iteration_bootstrap.is_some() {
            return Err(AgentdError::Invalid(
                "original learning capability already configured".into(),
            ));
        }
        self.root_learning_inputs = Some(inputs);
        Ok(self)
    }

    /// Complete the admitted host's stage assembly using the capability
    /// received by ordinary startup. No descriptor or local JSON can supply
    /// these owners. The existing runtime requires Circuit and plasticity too.
    pub fn with_root_learning_stage_owners(
        mut self,
        stages: Arc<dyn LearningIterationStageOwnerPortsV1>,
        verifier: LearningEvidenceVerifierV1,
        capacity: usize,
    ) -> Result<(Self, LearningIterationHandleV1), AgentdError> {
        let inputs: AgentdRootLearningInputsV1 =
            self.root_learning_inputs.take().ok_or_else(|| {
                AgentdError::Invalid("original Root learning handoff is required".into())
            })?;
        let (handle, bootstrap) = inputs.into_learning_runtime(stages, verifier, capacity)?;
        Ok((self.with_learning_iteration_bootstrap(bootstrap)?, handle))
    }

    pub(crate) fn require_root_learning_assembled(&self) -> Result<(), AgentdError> {
        if self.root_learning_inputs.is_some() {
            return Err(AgentdError::Invalid(
                "original learning checkpoint received, but actual stage owners are not assembled"
                    .into(),
            ));
        }
        Ok(())
    }
}
