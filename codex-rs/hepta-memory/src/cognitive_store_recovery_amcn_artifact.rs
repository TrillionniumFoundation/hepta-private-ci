//! Experimental **two-owner** research fence combining the ORIGINAL
//! Learning Artifacts withdrawal registry and SQLite CognitiveStore owner.
//!
//! Correct lock ordering is artifact-withdrawal -> CognitiveStore writer.
//! Holding just one check before the model executes is insufficient: a
//! withdrawal can invalidate a previously reviewed and selected Head while
//! the CognitiveStore source text remains unchanged. Keep BOTH owner locks
//! across the bounded callback.
//!
//! This does not prove production atomicity. The Tokio Mutex is NOT a durable
//! signed LearningArtifactOwnerHost or selector: only product hosts can supply
//! a trusted/independently current withdrawal registry and publication lock.
//! No authority, activation or FinalUse is issued by this interface.

use codex_hepta_learning_artifacts::{
    ArtifactKind, DatasetWithdrawalRegistry, WithdrawalBoundArtifactAdmissionV3,
    validate_artifact_publication_v3,
};
use codex_hepta_types::{Digest32, StableId};
use tokio::sync::Mutex;

use crate::{CognitiveAccess, CognitiveScope, CognitiveStore, CognitiveStoreError};
use super::CognitiveRecoveryAnchor;

pub const AMCN_TWO_OWNER_SHADOW_PRODUCTION_ACCEPTED: bool = false;

impl CognitiveStore {
    /// Deny a former Head if EITHER the original CognitiveStore cut or the
    /// independent Artifact withdrawal head has changed. A product host
    /// must verify trust/owner signature and monotonicity OUTSIDE this method.
    ///
    /// Lock ordering for a future host: existing Artifact withdrawal writer
    /// before SQLite BEGIN IMMEDIATE, then the entire Neuron Runtime tick and
    /// witnessed CAS. Other paths must obey the same ordering or deadlock.
    ///
    /// The method is intentionally feature-only. It consumes NO signed current
    /// registry/selection credential and must never become a production grant.
    pub async fn with_amcn_shadow_artifact_and_source<T, F>(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        expected_cognitive_cut: &CognitiveRecoveryAnchor,
        withdrawal_owner: &Mutex<DatasetWithdrawalRegistry>,
        admission: &WithdrawalBoundArtifactAdmissionV3,
        expected_withdrawal_head: Digest32,
        expected_selected_artifact: &StableId,
        expected_runtime_tuple_digest: Digest32,
        expected_training_dataset_digest: Digest32,
        now: u64,
        execute: F,
    ) -> Result<T, CognitiveStoreError>
    where
        F: FnOnce() -> Result<T, CognitiveStoreError>,
    {
        if expected_withdrawal_head.is_zero()
            || expected_runtime_tuple_digest.is_zero()
            || expected_training_dataset_digest.is_zero()
        {
            return Err(CognitiveStoreError::AccessDenied(
                "AMCN withdrawal, runtime and training-source pins required".into(),
            ));
        }

        // A Tokio mutex is used here strictly as an isolated source test port.
        // In production this must be the persistent signed owner transaction,
        // not a new Mutex synthesized by the caller from untrusted JSON.
        let owner = withdrawal_owner.lock().await;
        if owner.head_digest() != expected_withdrawal_head {
            return Err(CognitiveStoreError::AccessDenied(
                "AMCN artifact withdrawal changed after current pin".into(),
            ));
        }
        let manifest = &admission.validated_manifest.manifest;
        if !matches!(manifest.kind, ArtifactKind::Model | ArtifactKind::Parameters)
            || manifest.artifact_id != *expected_selected_artifact
            || manifest.runtime_tuple_digest != expected_runtime_tuple_digest
            || !manifest.source_dataset_digests.contains(&expected_training_dataset_digest)
            || validate_artifact_publication_v3(admission, &owner, now).is_err()
        {
            return Err(CognitiveStoreError::AccessDenied(
                "AMCN selected artifact, runtime or withdrawal admission mismatch".into(),
            ));
        }
        // Re-check the ORIGINAL withdrawal registry against the entire
        // training-source set NOW. Receipt validation alone is not enough:
        // a forged caller-supplied admission must never bypass a tombstone.
        let current_manifest = owner.admit_manifest(manifest.clone(), now).map_err(|_| {
            CognitiveStoreError::AccessDenied(
                "AMCN training dataset currently withdrawn or invalid".into(),
            )
        })?;
        if current_manifest.manifest_digest != admission.validated_manifest.manifest_digest
            || current_manifest.authority.grants_any()
        {
            return Err(CognitiveStoreError::AccessDenied(
                "AMCN current manifest disagrees with admitted artifact".into(),
            ));
        }

        // SQLite owner maintains BEGIN IMMEDIATE until AFTER callback returns.
        // Artifact owner mutex stays locked over that entire source fence, too.
        let result = self.with_amcn_shadow_cognitive_cut(
            access, scope, expected_cognitive_cut, execute,
        ).await;
        drop(owner);
        result
    }
}

#[cfg(test)]
#[path = "cognitive_store_recovery_amcn_artifact_tests.rs"]
mod tests;
