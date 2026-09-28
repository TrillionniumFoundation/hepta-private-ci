//! Revision- and authority-epoch-fenced runtime control state plus a bounded,
//! snapshot-coherent global planning kernel.
//!
//! The historical crate root is retained in `lib_core.rs`. This root adds the
//! authenticated context adapter and the persistent dispatch-claim contract
//! without rewriting unrelated public surfaces.

#![forbid(unsafe_code)]

#[path = "lib_core.rs"]
mod legacy_root;
pub use legacy_root::*;

/// Persistent admission boundary used before any planner effect dispatch.
///
/// `Ok(true)` means this caller acquired the first durable claim for the exact
/// operation/request/grant tuple. `Ok(false)` means a claim or terminal record
/// already exists and dispatch must not be replayed; the caller must reconcile.
pub trait PlannerDispatchClaimSinkV1: PlannerTerminalReceiptSinkV1 {
    fn claim_dispatch(
        &mut self,
        operation_identity_digest: codex_hepta_types::Digest32,
        request_digest: codex_hepta_types::Digest32,
        grant_digest: codex_hepta_types::Digest32,
        final_payload_digest: codex_hepta_types::Digest32,
        claimed_at_micros: u64,
    ) -> Result<bool, PlannerExecutionError>;
}

mod authenticated_context;
pub use authenticated_context::{
    AuthenticatedContextRecordV1, AuthenticatedObservedContextV1,
    plan_authenticated_observed_context,
};
