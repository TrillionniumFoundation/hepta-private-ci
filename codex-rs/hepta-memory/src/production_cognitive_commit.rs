//! Cancellation-safe final commit under the verifier-owned authority hold.
//!
//! SQLite runs on its own SQLx worker. A response waiter or runtime shutdown must
//! not release the authority/owner fences while COMMIT can still complete. The
//! bounded blocking task owns the transaction, guard and writer until the worker
//! answers; once started Tokio does not abort it during shutdown. No new work is
//! admitted here and only one transaction per SQLite writer reaches this point.

use std::future::Future;
use std::sync::Arc;

use super::ProductionAuthorityUseGuard;
use super::ProductionDurableWriter;
use crate::CognitiveStoreError;
use crate::cognitive_store::unavailable;

pub(super) async fn commit(
    transaction: sqlx::Transaction<'static, sqlx::Sqlite>,
    guard: ProductionAuthorityUseGuard,
    owner: Arc<ProductionDurableWriter>,
) -> Result<(), CognitiveStoreError> {
    let authority = owner.authority.clone();
    let owner_id = owner.owner_agent_id().clone();
    complete(
        async move {
            // The blocking pool may itself have queued. Recheck the signed
            // deadline at actual COMMIT entry rather than extending it by wait.
            authority
                .validate_for_agent(&owner_id)
                .map_err(|error| CognitiveStoreError::AccessDenied(error.to_string()))?;
            transaction.commit().await.map_err(unavailable)
        },
        guard,
        owner,
    )
    .await
}

async fn complete<F, H>(
    future: F,
    guard: ProductionAuthorityUseGuard,
    owner: H,
) -> Result<(), CognitiveStoreError>
where
    F: Future<Output = Result<(), CognitiveStoreError>> + Send + 'static,
    H: Send + 'static,
{
    let runtime = tokio::runtime::Handle::try_current().map_err(unavailable)?;
    tokio::task::spawn_blocking(move || {
        // SQLx commit waits on its database worker, not Tokio I/O or timers.
        let outcome = runtime.block_on(future);
        drop(guard);
        drop(owner);
        outcome
    })
    .await
    .map_err(|error| {
        CognitiveStoreError::Unavailable(format!(
            "cognitive commit task terminated; query the operation before retry: {error}"
        ))
    })?
}

#[cfg(test)]
#[path = "production_cognitive_commit_tests.rs"]
mod tests;
