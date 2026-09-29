//! Revision- and authority-epoch-fenced runtime control state plus a bounded,
//! snapshot-coherent global planning kernel.
//!
//! The historical crate root is retained in `lib_core.rs`. This root adds the
//! authenticated context adapter, persistent dispatch-claim contract and
//! explicit per-target organ fanout receipts without rewriting unrelated
//! public surfaces.

#![forbid(unsafe_code)]

#[path = "lib_core.rs"]
mod legacy_root;
pub use legacy_root::*;

/// Result of consulting the durable dispatch owner for one exact operation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlannerDispatchClaimOutcomeV1 {
    /// This caller durably acquired the first claim and may proceed to final
    /// authority revalidation and effect dispatch.
    Acquired,
    /// A claim exists without a conclusive terminal observation. The grant is
    /// the exact grant recorded by the first attempt and may only bind an
    /// effect-owner reconciliation query; the effect must not be replayed.
    ExistingClaim {
        original_grant_digest: codex_hepta_types::Digest32,
    },
    /// A conclusive durable terminal observation already exists. Idempotent
    /// retries return it unchanged without invoking the executor or reconciler.
    ExistingTerminal {
        receipt: Box<PlannerTerminalReceiptV1>,
    },
}

/// Persistent admission boundary used before any planner effect dispatch.
///
/// `Acquired` permits the first dispatch. `ExistingClaim` requires
/// reconciliation against the stable operation identity and never permits
/// replay. `ExistingTerminal` returns the already committed receipt. The sink
/// stores the original grant digest so a later authorization refresh cannot be
/// misreported as the grant used by the first attempt.
pub trait PlannerDispatchClaimSinkV1: PlannerTerminalReceiptSinkV1 {
    /// Inspect an exact operation without creating or changing durable state.
    /// A conclusive terminal result may be returned after the original request
    /// expires because this path does not authorize or dispatch a new effect.
    fn inspect_dispatch(
        &self,
        operation_identity_digest: codex_hepta_types::Digest32,
        request_digest: codex_hepta_types::Digest32,
        final_payload_digest: codex_hepta_types::Digest32,
    ) -> Result<Option<PlannerDispatchClaimOutcomeV1>, PlannerExecutionError>;

    fn claim_dispatch(
        &mut self,
        operation_identity_digest: codex_hepta_types::Digest32,
        request_digest: codex_hepta_types::Digest32,
        grant_digest: codex_hepta_types::Digest32,
        final_payload_digest: codex_hepta_types::Digest32,
        claimed_at_micros: u64,
    ) -> Result<PlannerDispatchClaimOutcomeV1, PlannerExecutionError>;
}

/// Maximum number of unresolved durable claims returned by one recovery page.
pub const MAX_PENDING_DISPATCH_PAGE_ITEMS_V1: usize = 256;

/// Read-only evidence for one operation that owns a durable dispatch claim but
/// does not yet have a conclusive terminal observation.
///
/// This projection never carries authority to dispatch. The original grant
/// digest may bind only a reconciliation query for the exact operation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerPendingDispatchV1 {
    pub claim_sequence: u64,
    pub claim_record_digest: codex_hepta_types::Digest32,
    pub operation_identity_digest: codex_hepta_types::Digest32,
    pub request_digest: codex_hepta_types::Digest32,
    pub original_grant_digest: codex_hepta_types::Digest32,
    pub final_payload_digest: codex_hepta_types::Digest32,
    pub authority: codex_hepta_types::AuthorityPosture,
}

/// Bounded round-robin projection of unresolved durable dispatch claims.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerPendingDispatchPageV1 {
    pub items: Vec<PlannerPendingDispatchV1>,
    /// Pass this value back as `after_sequence` to continue from the next
    /// unresolved claim. `None` means no unresolved claim exists.
    pub next_after_sequence: Option<u64>,
    /// True when this page crossed the end of the unresolved-claim order and
    /// resumed from its beginning.
    pub wrapped: bool,
    pub authority: codex_hepta_types::AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OrganTargetDeliveryDispositionV1 {
    Delivered,
    /// The legacy handler completed before a later target failed, but the old
    /// aggregate error path did not preserve that target's output bytes.
    DeliveredOutputUnavailable,
    Failed,
    NotAttempted,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganTargetDeliveryReceiptV1 {
    pub target: codex_hepta_types::StableId,
    pub input_port: usize,
    pub disposition: OrganTargetDeliveryDispositionV1,
    pub output_digest: Option<codex_hepta_types::Digest32>,
    pub fault_code: Option<codex_hepta_types::StableId>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganFanoutReceiptV1 {
    pub generation: codex_hepta_types::Generation,
    pub source: codex_hepta_types::StableId,
    pub output_port: usize,
    pub payload_digest: codex_hepta_types::Digest32,
    pub targets: Vec<OrganTargetDeliveryReceiptV1>,
    pub error: Option<OrganRuntimeError>,
    pub authority: codex_hepta_types::AuthorityPosture,
}

mod organ_fanout_recovery;
pub use organ_fanout_recovery::{
    OrganFanoutContinuationV1, OrganFanoutRecoveryErrorV1,
};

mod authenticated_context;
pub use authenticated_context::{
    AuthenticatedContextRecordV1, AuthenticatedObservedContextV1,
    plan_authenticated_observed_context,
};
