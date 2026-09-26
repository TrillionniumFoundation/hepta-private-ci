//! Minimal Neural Circuit runtime adapter on top of the existing TaskFlow
//! definition owner. It records deterministic choices and stops at wait/effect
//! boundaries; it is not a second scheduler, ledger or authority issuer.

mod runtime;
mod types;

pub use runtime::run_neural_circuit_v1;
pub use types::*;

#[cfg(test)]
mod tests;
