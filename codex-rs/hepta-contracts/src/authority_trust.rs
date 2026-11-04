//! External trust interfaces used by kernel.authority production compositions.
//!
//! These traits deliberately do not manufacture trust. Deployments provide an
//! attested/monotonic clock and an externally durable CAS frontier store. The
//! authority owners use them to fail closed on time uncertainty and local
//! snapshot rollback.

use std::fmt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorityTrustError {
    Invalid,
    Conflict,
    Unavailable,
}

impl fmt::Display for AuthorityTrustError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for AuthorityTrustError {}

/// Host-owned trusted wall/monotonic-time projection.
///
/// Production implementations are expected to bind this to an attested or
/// otherwise protected time source. The system clock implementation below is a
/// compatibility/testing implementation, not an attestation claim.
pub trait AuthorityClock: Send + Sync {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SystemAuthorityClock;

impl AuthorityClock for SystemAuthorityClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| AuthorityTrustError::Unavailable)?
            .as_millis();
        u64::try_from(millis).map_err(|_| AuthorityTrustError::Unavailable)
    }
}

/// Externally durable compare-and-set frontier.
///
/// The external store must survive rollback/replacement of the local authority
/// directory. compare_and_set must durably commit next only when the current
/// value exactly equals expected. Authority owners call it before committing
/// the corresponding local state. If the local commit then fails, the owner
/// fences itself; reopening observes an external frontier ahead of local state
/// and fails closed until operator recovery.
///
/// All clients for an owner must share the same linearizable state. `load`
/// returns a fresh observation ordered between its invocation and completion;
/// a cached checkpoint or a lagging replica must not be reported as current.
/// The observation does not lease the frontier against later changes or prove
/// that an already-entered external effect has completed.
///
/// The full value, including any state digest, participates in the comparison.
/// A revision counter alone cannot preserve consumed rights or revocations.
/// An uncertain write may have committed: callers must keep the operation's
/// existing identity and fail closed until reconciliation, rather than treat
/// an error as proof of no effect. Implementations must bound unavailability
/// and return an error when freshness or durable completion is unknown.
pub trait AuthorityFrontierStore<F>: Send + Sync {
    /// Observe this owner's current durable frontier with the consistency
    /// contract above; never substitute a local or cached recovery checkpoint.
    fn load(&self, owner_id: &str) -> Result<F, AuthorityTrustError>;

    /// Atomically compare the complete expected value and durably install the
    /// complete next value. `Ok(())` means the write has durably committed.
    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &F,
        next: &F,
    ) -> Result<(), AuthorityTrustError>;
}
