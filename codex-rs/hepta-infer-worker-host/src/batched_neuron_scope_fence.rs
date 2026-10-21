//! Exact live CNS route-fence admission for physical multi-scope inference.
//!
//! The batching scheduler stores historical scope keys, not current authority.
//! Production composition MUST obtain this guard from an independently owned,
//! authenticated CNS route state. Its read-side guard must exclude generation,
//! route, model or authority-epoch cutover while a physical backend batch runs.
//! A synthetic test port is never production currentness evidence.

use codex_hepta_infer_core::microbatch::MicrobatchKeyV1;

/// Physical execution is denied when any scope's exact current binding cannot
/// be fenced atomically. A transport failure is never interpreted as current.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PhysicalScopeCurrentnessErrorV1 {
    Unavailable,
    StaleBinding,
    Conflict,
}

/// Opaque guard held across the complete, synchronous physical driver call.
/// The CNS owner must not publish a conflicting route while this guard lives.
pub trait PhysicalScopeBatchGuardV1 {}

/// Only a separately owned CNS route/currentness adapter may implement this
/// production port. Validate all scope keys as one atomic snapshot and retain
/// the relevant read fences until the returned guard is dropped.
///
/// This contract itself does not implement a CNS owner, grant permissions, or
/// claim that a test fixture is an authenticated production implementation.
pub trait PhysicalScopeCurrentnessPortV1: std::fmt::Debug + Send + Sync {
    fn enter_current<'a>(
        &'a self,
        bindings: &[MicrobatchKeyV1],
    ) -> Result<Box<dyn PhysicalScopeBatchGuardV1 + 'a>, PhysicalScopeCurrentnessErrorV1>;
}
