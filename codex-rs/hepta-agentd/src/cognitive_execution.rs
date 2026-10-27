//! One bounded observation slot on the original read execution window. It
//! cannot load a model, issue a receipt, extend a deadline or authorize use.

use crate::CognitiveContextExecutionV1;
use crate::CognitiveContextSnapshot;
use crate::CognitiveNeuralExecutionV1;
use crate::NeuralCognitiveExecutionV1;

#[derive(Default)]
pub(crate) struct ReadObservationV1 {
    settled: Option<CognitiveNeuralExecutionV1>,
}

pub(crate) struct ExpectedNeuralReadV1<'a> {
    pub(crate) owner: &'a codex_hepta_contracts::AgentId,
    pub(crate) body_generation: u64,
    pub(crate) parameter: codex_hepta_types::Digest32,
    pub(crate) model_generation: u64,
    pub(crate) response: codex_hepta_types::Digest32,
    pub(crate) source: crate::CognitiveNeuralSourceV1,
}

impl NeuralCognitiveExecutionV1 {
    pub(crate) fn collect_settled_read_v1(&self) -> Result<(), String> {
        self.check()?;
        let mut slot = self
            .observations
            .try_lock()
            .map_err(|_| "read observation is busy")?;
        if slot.is_some() {
            return Err("read observation collection cannot be rebound".to_owned());
        }
        *slot = Some(ReadObservationV1::default());
        Ok(())
    }

    pub(crate) fn match_settled_read_v1(
        &self,
        expected: ExpectedNeuralReadV1<'_>,
    ) -> Result<(), String> {
        self.check()?;
        let slot = self
            .observations
            .try_lock()
            .map_err(|_| "read observation is busy")?;
        if let Some(slot) = slot.as_ref() {
            let actual = slot
                .settled
                .as_ref()
                .ok_or("selected neural read has no original settled execution observation")?;
            if actual.owner_id != *expected.owner
                || actual.body_generation != expected.body_generation
                || actual.parameter_file_digest.as_str() != expected.parameter.to_string()
                || actual.model_generation != expected.model_generation
                || actual.response_digest.as_str() != expected.response.to_string()
                || actual.source != expected.source
            {
                return Err("settled execution differs from the selected neural read".to_owned());
            }
        }
        Ok(())
    }

    /// Called only after the original physical owner has joined both Completed
    /// journal records to the actual Ready and forward. No wire input invokes
    /// this method. Legacy reads do not opt in to the new observation envelope.
    pub fn observe_settled_read_v1(
        &self,
        observed: CognitiveNeuralExecutionV1,
    ) -> Result<(), String> {
        self.check()?;
        let mut slot = self
            .observations
            .try_lock()
            .map_err(|_| "read observation is busy")?;
        let Some(slot) = slot.as_mut() else {
            return Ok(());
        };
        observed.validate()?;
        if slot.settled.is_some() {
            return Err("a second forward cannot replace the original read observation".to_owned());
        }
        slot.settled = Some(observed);
        Ok(())
    }

    pub(crate) fn context_with_execution_v1(
        &self,
        snapshot: CognitiveContextSnapshot,
    ) -> Result<CognitiveContextExecutionV1, String> {
        self.check()?;
        let slot = self
            .observations
            .try_lock()
            .map_err(|_| "read observation is busy")?;
        let slot = slot
            .as_ref()
            .ok_or("read observation collection was not requested")?;
        let context = CognitiveContextExecutionV1 {
            schema_version: 1,
            snapshot,
            neural: slot.settled.clone(),
        };
        validate_context_execution_v1(&context)?;
        Ok(context)
    }
}

pub(crate) fn validate_context_execution_v1(
    context: &CognitiveContextExecutionV1,
) -> Result<(), String> {
    if context.schema_version != 1
        || serde_json::to_vec(context)
            .map_err(|error| error.to_string())?
            .len()
            > crate::MAX_COGNITIVE_CONTEXT_BYTES
    {
        return Err("unsupported or oversized cognitive execution envelope".to_owned());
    }
    if let Some(neural) = &context.neural {
        neural.validate()?;
    }
    Ok(())
}

#[cfg(test)]
#[path = "cognitive_execution_tests.rs"]
mod tests;
