//! Minimal Neural Circuit runtime adapter on top of the existing TaskFlow
//! definition owner. It records deterministic choices and stops at wait/effect
//! boundaries; it is not a second scheduler, ledger or authority issuer.

mod runtime;
mod types;

pub use runtime::checkpoint_for_circuit_outcome_v1;
pub use runtime::circuit_runtime_outcome_digest_v1;
pub use runtime::resume_neural_circuit_after_effect_v1;
pub use runtime::resume_neural_circuit_v1;
pub use runtime::run_neural_circuit_v1;
pub use runtime::runtime_profile_digest_v1;
pub use runtime::validate_circuit_runtime_outcome_v1;
pub use types::*;

#[cfg(test)]
mod tests;
