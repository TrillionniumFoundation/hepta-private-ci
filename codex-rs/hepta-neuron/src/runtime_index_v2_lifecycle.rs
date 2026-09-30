//! Admission-only failure tombstones and the pre-dispatch fence. Successful
//! checkpoint results remain exclusively authoritative in HPTNGS02. New event
//! kinds are forward-only: old readers fail closed rather than replaying them.
use super::*;

/// A durable negative result for the Neuron state transition, not a claim that
/// an upstream model never ran. Unknown upstream outcomes cannot use this path.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NeuronOperationFailureV2 {
    ModelRejected,
    InvalidModelOutput,
    InvalidTransition,
    AdmissionDenied,
    ResultOverBudget,
}

impl NeuronOperationFailureV2 {
    /// Stable low-cardinality terminal reason for host metrics and runbooks.
    /// The serialized snake-case representation remains unchanged.
    #[must_use]
    pub const fn stable_code(self) -> &'static str {
        match self {
            Self::ModelRejected => "model_rejected",
            Self::InvalidModelOutput => "invalid_model_output",
            Self::InvalidTransition => "invalid_transition",
            Self::AdmissionDenied => "admission_denied",
            Self::ResultOverBudget => "result_over_budget",
        }
    }
}

impl FileNeuronRuntimeIndexV2 {
    pub(crate) fn failure(
        &self,
        key: &NeuronOperationKeyV2,
    ) -> Result<Option<NeuronOperationFailureV2>, NeuronRuntimeIndexError> {
        self.ensure_healthy()?;
        validate_key(key)?;
        match self.failures.get(&key.tick_id) {
            Some((previous, failure)) if previous == key => Ok(Some(*failure)),
            Some(_) => Err(NeuronRuntimeIndexError::Conflict),
            None => Ok(None),
        }
    }

    pub(crate) fn dispatched(&self) -> Result<bool, NeuronRuntimeIndexError> {
        self.ensure_healthy()?;
        Ok(self.dispatched)
    }

    pub(crate) fn mark_dispatched(
        &mut self,
        key: &NeuronOperationKeyV2,
    ) -> Result<(), NeuronRuntimeIndexError> {
        self.ensure_healthy()?;
        if self.pending.as_ref().is_none_or(|value| value.key != *key) {
            return Err(NeuronRuntimeIndexError::Conflict);
        }
        if self.dispatched {
            return Ok(());
        }
        let event = IndexEventV2::DispatchStarted {
            key: OperationKeyDto::from_key(key),
        };
        let payload = encode_event(self.event_frontier, &event)?;
        self.append_payload(&payload)?;
        self.event_frontier = event_digest(&payload)?;
        self.dispatched = true;
        Ok(())
    }

    pub(crate) fn fail_operation(
        &mut self,
        key: &NeuronOperationKeyV2,
        failure: NeuronOperationFailureV2,
    ) -> Result<(), NeuronRuntimeIndexError> {
        self.ensure_healthy()?;
        if let Some(previous) = self.failure(key)? {
            return if previous == failure {
                Ok(())
            } else {
                Err(NeuronRuntimeIndexError::Conflict)
            };
        }
        if self.pending.as_ref().is_none_or(|value| value.key != *key)
            || self.tick_index.contains_key(&key.tick_id)
        {
            return Err(NeuronRuntimeIndexError::Conflict);
        }
        let event = IndexEventV2::Failed {
            key: OperationKeyDto::from_key(key),
            failure,
        };
        let payload = encode_event(self.event_frontier, &event)?;
        self.append_payload(&payload)?;
        self.event_frontier = event_digest(&payload)?;
        self.failures
            .insert(key.tick_id.clone(), (key.clone(), failure));
        self.pending = None;
        self.dispatched = false;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn terminal_failure_codes_are_stable() {
        assert_eq!(
            NeuronOperationFailureV2::ModelRejected.stable_code(),
            "model_rejected"
        );
        assert_eq!(
            NeuronOperationFailureV2::InvalidModelOutput.stable_code(),
            "invalid_model_output"
        );
        assert_eq!(
            NeuronOperationFailureV2::InvalidTransition.stable_code(),
            "invalid_transition"
        );
        assert_eq!(
            NeuronOperationFailureV2::AdmissionDenied.stable_code(),
            "admission_denied"
        );
        assert_eq!(
            NeuronOperationFailureV2::ResultOverBudget.stable_code(),
            "result_over_budget"
        );
    }
}
