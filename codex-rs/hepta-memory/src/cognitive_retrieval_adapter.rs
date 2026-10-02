//! SQLite-owner adaptation with explicit multi-proposition semantic admission.
//! The predecessor HNMF packet remains unchanged; proposition evidence is observed in
//! the same owner transaction and bound transitively into every candidate's
//! support digest. This module never invents a source assertion or polarity.

#[path = "cognitive_retrieval_adapter_core.rs"]
mod core;

pub use core::OwnerRetrievalExecutionV1;
pub use core::RetrievalExecutionContextV1;
pub use core::sqlite_owner_cue_profile_digest;
pub use core::sqlite_owner_retrieval_policy_v1;

pub use core::OwnerRetrievalExecutionV2;
pub use core::execute_owner_observation_controlled;
pub use core::execute_owner_observation_v2_controlled;

use crate::CognitiveStoreError;
use crate::DurableCognitiveSnapshot;
use crate::RetrievalObservation;
use codex_hepta_types::Digest32;

/// Migration alias; explicit assertions require the V2 semantic admission API.
#[deprecated(note = "use execute_owner_observation_v2_controlled with explicit work control")]
pub fn execute_owner_observation(
    observation: &RetrievalObservation,
    cut: &DurableCognitiveSnapshot,
    context: &RetrievalExecutionContextV1,
    request_digest: Digest32,
    acquired_at_unix_ms: u64,
    lease_expires_unix_ms: u64,
    work: &codex_hepta_memory_retrieval::RecallWorkControlV1,
) -> Result<OwnerRetrievalExecutionV1, CognitiveStoreError> {
    execute_owner_observation_controlled(
        observation,
        cut,
        context,
        request_digest,
        acquired_at_unix_ms,
        lease_expires_unix_ms,
        work,
    )
}

#[cfg(test)]
#[path = "cognitive_proposition_owner_tests.rs"]
mod proposition_tests;
