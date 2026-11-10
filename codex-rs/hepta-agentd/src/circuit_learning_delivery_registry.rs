//! A bounded, immutable list of complete host-authored delivery requests.
//! It supplies no request generator, checkpoint dispatch or new authority.

use super::*;

pub(crate) const MAX_REGISTERED_CIRCUIT_LEARNING: usize = 64;

/// Explicit tasks sharing the original bootstrap's stage owners and trust.
/// Each task still needs its own original recoverable checkpoint at those
/// ports. A single-task checkpoint cannot silently serve another operation.
pub struct CircuitLearningDeliveryRegistryV1 {
    pub(crate) requests: Vec<LearningIterationRequestV1>,
}

impl CircuitLearningDeliveryRegistryV1 {
    pub fn new(requests: Vec<LearningIterationRequestV1>) -> Result<Self, AgentdError> {
        if !(1..=MAX_REGISTERED_CIRCUIT_LEARNING).contains(&requests.len()) {
            return Err(AgentdError::Invalid("Circuit learning registry capacity".into()));
        }
        for (index, request) in requests.iter().enumerate() {
            if request.agent_id != requests[0].agent_id
                || requests[..index].iter().any(|previous| {
                    previous.source_run_id == request.source_run_id
                        || previous.operation_id == request.operation_id
                })
            {
                return Err(AgentdError::Invalid("Circuit learning registry identity conflict".into()));
            }
        }
        Ok(Self { requests })
    }
}
