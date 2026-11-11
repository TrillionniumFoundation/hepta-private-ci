//! Only the existing original Root/Q24 join may install a historical source.

use super::*;
use crate::OriginalCellQ24RetainedLearningSourceV1;

impl LearningIterationRuntimeBootstrapV1 {
    pub(crate) fn with_retained_q24_source(
        mut self,
        source: OriginalCellQ24RetainedLearningSourceV1,
        identity: &AgentdIdentity,
    ) -> Result<Self, AgentdError> {
        self.require_identity(identity)?;
        let original = self.original_q24.as_ref().ok_or_else(|| {
            AgentdError::GenerationFenced("original Root Q24 owners required".into())
        })?;
        let original: &crate::OriginalCellQ24LearningStageOwnersV1 = original.as_ref();
        let prepared = original.prepared();
        let registry = self.circuit_delivery_registry.as_ref().ok_or_else(|| {
            AgentdError::GenerationFenced("original Root source registry required".into())
        })?;
        if self.retained_source.is_some()
            || !self.enforce_circuit_admission
            || !matches!(
                self.circuit_delivery_source,
                CircuitLearningSourceV1::OriginalQ24
            )
            || self.scope.as_ref() != Some(prepared.scope())
            || self.owners != prepared.initial().owners
            || registry.requests.as_slice() != std::slice::from_ref(&prepared.initial().request)
        {
            return Err(AgentdError::GenerationFenced(
                "retained source differs from original Root registration".into(),
            ));
        }
        self.retained_source = Some(source.register_original_scope(
            identity.clone(),
            prepared.initial(),
            prepared.scope(),
        )?);
        Ok(self)
    }
}
