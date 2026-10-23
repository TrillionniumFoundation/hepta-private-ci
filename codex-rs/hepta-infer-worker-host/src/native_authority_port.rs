//! Host-owned final-use port shared by the production native caller and issuer adapter.

use std::future::Future;
use std::pin::Pin;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::VerifiedUseToken;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

pub type TurnStartAuthorityFuture<'a> =
    Pin<Box<dyn Future<Output = Result<VerifiedUseToken>> + Send + 'a>>;

/// Host-owned final-use port. runtime.codex can request a claim for the exact
/// final binding, but it cannot construct a VerifiedUseToken itself.
pub trait TurnStartAuthorizer: Send + Sync {
    fn claim<'a>(&'a self, binding: FinalUseBinding) -> TurnStartAuthorityFuture<'a>;
}
