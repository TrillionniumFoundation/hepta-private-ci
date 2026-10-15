//! One real SQLite CognitiveStore write-side fence for experimental AMCN calls.
//!
//! A successful pinned read followed by releasing the transaction BEFORE
//! model execution is unsafe: a source writer can withdraw or revise that
//! evidence between the read and the neuron tick. This feature-only method
//! keeps the *real SQLite BEGIN IMMEDIATE transaction* alive until the bounded
//! synchronous research callback has fully returned.
//!
//! It is intentionally NOT an implementation of a fleet-wide model lease.
//! The Learning Artifacts / persistent quarantine and Runtime Witness owners
//! have separate transaction domains. Independent provenance and release
//! authority cannot be inferred from this locally compared SHA-bearing anchor.
//! No final-use token, model activation, topology change or effect is issued.

use super::{capture, CognitiveRecoveryAnchor};
use crate::{CognitiveAccess, CognitiveScope, CognitiveStore, CognitiveStoreError};
use crate::cognitive_store::unavailable;

pub const AMCN_SHADOW_COGNITIVE_FENCE_PRODUCTION_ACCEPTED: bool = false;

impl CognitiveStore {
    /// Hold one SQLite source-state writer fence ACROSS a synchronous, bounded
    /// research callback, provided the complete owner cut equals a separately
    /// retained CURRENT witness. No writable transaction is passed to callback.
    ///
    /// Security constraints for the eventual host integration:
    /// - authenticate expected_current_cut OUT OF BAND; a caller computing
    ///   it from a suspect store or replayed backup does not prevent rollback;
    /// - independently fence Learning Artifacts, source withdrawals outside
    ///   this DB, runtime generation and the durable quarantine CAS;
    /// - do not re-enter this SQLite owner from execute, avoiding deadlock;
    /// - perform potentially long model execution on a dedicated blocking
    ///   worker. This async prototype blocks its executor during execute
    ///   and is deliberately unsuitable for production inference latency;
    /// - do not use this receipt for product FinalUse/authority.
    ///
    /// The transaction is rolled back rather than committed after callback
    /// to avoid silently conferring any cognitive.store write privilege.
    /// Any closure error still releases the source transaction before return.
    pub async fn with_amcn_shadow_cognitive_cut<T, F>(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        expected_current_cut: &CognitiveRecoveryAnchor,
        execute: F,
    ) -> Result<T, CognitiveStoreError>
    where
        F: FnOnce() -> Result<T, CognitiveStoreError>,
    {
        self.authorize(access, scope)?;
        if expected_current_cut.owner_agent_id != self.owner_agent_id {
            return Err(CognitiveStoreError::AccessDenied(
                "AMCN shadow owner-cut witness belongs to another agent".to_string(),
            ));
        }
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let actual = capture(&mut transaction, &self.owner_agent_id).await?;
        if actual != *expected_current_cut {
            return Err(CognitiveStoreError::AccessDenied(
                "AMCN shadow source cut changed after external witness".to_string(),
            ));
        }

        // It is critical that transaction remains alive throughout execute.
        // This locks source-ledger writers that use this SAME SQLite owner.
        // It does NOT fence a separate quarantine/model/Runtime writer.
        let result = execute();
        transaction.rollback().await.map_err(unavailable)?;
        result
    }
}

#[cfg(test)]
#[path = "cognitive_store_recovery_amcn_fence_tests.rs"]
mod tests;
