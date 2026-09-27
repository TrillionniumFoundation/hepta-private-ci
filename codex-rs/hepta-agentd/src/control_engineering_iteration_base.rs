//! Stable control.engineering iteration records plus hardened terminal journal.
//!
//! The original coordinator implementation remains available as a private legacy
//! module because its public request, error and freeze types are compatibility
//! surfaces. The exported terminal journal is the protected-length V2 format.

#[allow(dead_code, unused_imports, unused_mut)]
#[path = "control_engineering_iteration_base_legacy.rs"]
mod legacy;
#[path = "control_engineering_terminal_journal.rs"]
mod terminal_journal;

pub use legacy::ControlEngineeringIterationErrorV1;
pub use legacy::ControlEngineeringParameterIterationRequestV1;
pub use legacy::ControlEngineeringTopologyIterationRequestV1;
pub use legacy::DurableIterationJournalErrorV1;
pub use legacy::FrozenPlasticityContextV1;
pub use legacy::IterationPlasticityKindV1;
pub use legacy::IterationPlasticityTerminalDispositionV1;
pub use legacy::IterationPlasticityTerminalReceiptV1;
pub use legacy::freeze_parameter_context_v1;
pub use legacy::freeze_topology_context_v1;
pub use legacy::iteration_envelope_digest_v1;
pub use terminal_journal::DurableIterationTerminalJournalV1;
