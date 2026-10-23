//! Sealed transport of the original production request and final-use claim.

use super::ProductionDispatchRequest;
use super::ProductionTargetOutcome;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::VerifiedUseToken;
use std::future::Future;
use std::pin::Pin;

/// Original source-verified request and its one-shot final-use claim. Only the
/// production writer can construct this non-serializable, non-cloneable value.
/// A target cannot extract the token and rebind it to a second request.
pub struct ProductionVerifiedDispatch {
    pub(super) request: ProductionDispatchRequest,
    pub(super) authority: FinalUseAuthority,
    pub(super) token: VerifiedUseToken,
    pub(super) expected: FinalUseBinding,
}

impl ProductionVerifiedDispatch {
    pub fn request(&self) -> &ProductionDispatchRequest {
        &self.request
    }

    pub fn binding(&self) -> &FinalUseBinding {
        &self.expected
    }

    /// Consume the original claim at the target's final synchronous entry.
    /// Complete asynchronous preparation first. The callback must immediately
    /// cross its fixed physical boundary and retain ownership, without await.
    /// The target supplies its preconfigured authority, rejecting claims from
    /// a different owner even if their visible binding bytes are identical.
    pub fn with_dispatch_boundary<T>(
        self,
        authority: &FinalUseAuthority,
        boundary: impl FnOnce(&ProductionDispatchRequest) -> T,
    ) -> Result<T, FinalUseError> {
        authority.with_dispatch_boundary(self.token, &self.expected, || boundary(&self.request))
    }
}

pub type ProductionVerifiedDispatchFuture<'a> =
    Pin<Box<dyn Future<Output = Result<ProductionTargetOutcome, FinalUseError>> + Send + 'a>>;

#[cfg(test)]
#[path = "production_verified_dispatch_tests.rs"]
mod tests;
