//! Retain the physical worker from the original generation construction.
//! This factual composition grants no new admission or model-use authority.
use super::AgentdNeuronHandleV2;
use super::CpuNeuronGenerationPlanV1;
use super::SharedCpuNeuronInferenceControlV3;
use codex_hepta_agentd::AgentdError;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use std::sync::Arc;
use std::sync::Mutex;

/// A read-only view of the original compiler's actual physical compositions.
/// The compiler publishes at most its original successor and rollback once.
#[derive(Clone, Default)]
pub struct CpuNeuronGenerationCompositionReaderV2 {
    compositions: Arc<Mutex<Option<Vec<CpuNeuronGenerationCompositionV2>>>>,
}
impl CpuNeuronGenerationCompositionReaderV2 {
    pub(crate) fn retain(
        &self,
        compositions: Vec<CpuNeuronGenerationCompositionV2>,
    ) -> Result<(), AgentdError> {
        if compositions.is_empty() {
            return Ok(());
        }
        if compositions.len() != 2 {
            return Err(AgentdError::Invalid(
                "original physical composition pair is incomplete".into(),
            ));
        }
        // Readers only clone the immutable snapshot while holding this mutex.
        // Keep the actual physical owners even after a poisoned publication;
        // reads below still reject the poisoned state and cannot grant use.
        let mut original = self
            .compositions
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if original.is_some() {
            return Err(AgentdError::Invalid(
                "original physical compositions cannot be replaced".into(),
            ));
        }
        *original = Some(compositions);
        Ok(())
    }

    pub fn resolve(
        &self,
        generation: Generation,
        configuration_digest: Digest32,
        body_digest: Digest32,
    ) -> Result<Option<CpuNeuronGenerationCompositionV2>, AgentdError> {
        let compositions = self
            .compositions
            .try_lock()
            .map_err(|error| match error {
                std::sync::TryLockError::WouldBlock => {
                    AgentdError::Overloaded { retry_after_ms: 25 }
                }
                std::sync::TryLockError::Poisoned(_) => AgentdError::Protocol(
                    "original physical composition requires owner reconciliation".into(),
                ),
            })?
            .clone();
        for composition in compositions.into_iter().flatten() {
            if composition.matches(generation, configuration_digest, body_digest)? {
                return Ok(Some(composition));
            }
        }
        Ok(None)
    }
}

#[derive(Clone)]
pub struct CpuNeuronGenerationCompositionV2 {
    plan: CpuNeuronGenerationPlanV1,
    handle: AgentdNeuronHandleV2,
    physical: SharedCpuNeuronInferenceControlV3,
}

impl CpuNeuronGenerationCompositionV2 {
    #[cfg(target_os = "linux")]
    pub(super) fn new(
        plan: CpuNeuronGenerationPlanV1,
        handle: AgentdNeuronHandleV2,
        physical: SharedCpuNeuronInferenceControlV3,
    ) -> Self {
        Self {
            plan,
            handle,
            physical,
        }
    }

    pub fn plan(&self) -> &CpuNeuronGenerationPlanV1 {
        &self.plan
    }

    pub fn handle(&self) -> &AgentdNeuronHandleV2 {
        &self.handle
    }

    pub(crate) fn physical_shared(&self) -> SharedCpuNeuronInferenceControlV3 {
        self.physical.clone()
    }

    pub(crate) fn matches(
        &self,
        generation: Generation,
        configuration_digest: Digest32,
        body_digest: Digest32,
    ) -> Result<bool, AgentdError> {
        if self.plan.runtime.generation != generation
            || self.plan.runtime.semantic_digest().ok() != Some(configuration_digest)
            || self.plan.body.semantic_digest().ok() != Some(body_digest)
        {
            return Ok(false);
        }
        if self.handle.generation().map_err(|error| {
            AgentdError::Protocol(format!("original physical generation: {error}"))
        })? != generation.get()
            || self.handle.configuration_digest() != configuration_digest
            || self.handle.body_bundle_digest() != Some(body_digest)
        {
            return Err(AgentdError::Invalid(
                "original physical generation identity changed".into(),
            ));
        }
        self.physical_shared()
            .validate_runtime(&self.plan.runtime)
            .map_err(|error| {
                AgentdError::Protocol(format!("original shared physical worker: {error}"))
            })?;
        Ok(true)
    }

    #[cfg(target_os = "linux")]
    pub(super) fn into_handle(self) -> AgentdNeuronHandleV2 {
        self.handle
    }
}
