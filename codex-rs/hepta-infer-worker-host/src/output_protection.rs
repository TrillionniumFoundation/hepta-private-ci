//! Host-selected model-output protection boundary.
//!
//! The inference worker never receives a long-lived encryption key. A concrete
//! host adapter sends plaintext to an isolated KMS/vault boundary and returns
//! only authenticated encrypted-object metadata for the durable journal.

use std::future::Future;
use std::pin::Pin;

use codex_hepta_infer_core::control_contracts::ProtectedOutput;
use codex_hepta_infer_core::control_contracts::VerifiedExecutionPlan;

/// Asynchronous output-protection result.
pub type NativeOutputProtectionFuture<'a> =
    Pin<Box<dyn Future<Output = std::result::Result<ProtectedOutput, String>> + Send + 'a>>;

/// Host-selected encryption port. Implementations normally call a KMS or an
/// isolated local vault and return only a protected digest/reference envelope.
pub trait NativeOutputProtector: Send + Sync {
    fn protect<'a>(
        &'a self,
        plan: &'a VerifiedExecutionPlan,
        plaintext: &'a [u8],
        now_unix_ms: u64,
    ) -> NativeOutputProtectionFuture<'a>;
}
