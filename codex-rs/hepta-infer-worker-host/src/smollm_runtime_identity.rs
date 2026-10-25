//! Physical model inputs, separated from the evaluated Agentd admission pin.
//! The existing read-port constructor projects its retained complete pin.
//! This data projection is neither qualification nor model-load evidence.

use codex_hepta_agentd::NeuralCognitivePinV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct SmolLmRuntimeIdentityV1 {
    pub(crate) payload_digest: Digest32,
    pub(crate) generation: Generation,
    pub(crate) family_digest: Digest32,
    pub(crate) execution_profile_digest: Digest32,
}

impl From<&NeuralCognitivePinV1> for SmolLmRuntimeIdentityV1 {
    fn from(pin: &NeuralCognitivePinV1) -> Self {
        Self {
            payload_digest: pin.payload_digest,
            generation: pin.generation,
            family_digest: pin.family_digest,
            execution_profile_digest: pin.execution_profile_digest,
        }
    }
}

#[cfg(test)]
#[path = "smollm_runtime_identity_tests.rs"]
mod tests;
