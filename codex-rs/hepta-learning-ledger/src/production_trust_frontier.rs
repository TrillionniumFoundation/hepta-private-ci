//! Independent root-distribution floor at every product writer admission.
//! The store must be durably hosted outside the rollback domain of this ledger.
//! There is no local-file or in-memory production fallback for a PQ writer.
use super::*;
use crate::LearningAuthenticationProfile;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use std::sync::Arc;

pub use codex_hepta_contracts::LearningTrustFrontier;

#[must_use]
pub fn learning_trust_frontier(trust: &ActivatedLearningTrustV1) -> LearningTrustFrontier {
    LearningTrustFrontier {
        root_digest: *trust.root_digest().as_array(),
        distribution_digest: *trust.distribution_digest().as_array(),
        generation: trust.generation(),
        authority_epoch: trust.verifier().authority_epoch(),
    }
}

/// Verify the separately retained activation floor before accepting replayed
/// immutable learning evidence at an installation or writer boundary.
pub fn verify_learning_trust_frontier(
    binding: Digest32,
    trust: &ActivatedLearningTrustV1,
    store: &dyn AuthorityFrontierStore<LearningTrustFrontier>,
) -> Result<(), AuthorityTrustError> {
    verify_expected_frontier(binding, &learning_trust_frontier(trust), store)
}

pub(crate) fn verify_expected_frontier(
    binding: Digest32,
    expected: &LearningTrustFrontier,
    store: &dyn AuthorityFrontierStore<LearningTrustFrontier>,
) -> Result<(), AuthorityTrustError> {
    if binding.is_zero() {
        return Err(AuthorityTrustError::Invalid);
    }
    if store.load(&owner_id(binding))? != *expected {
        return Err(AuthorityTrustError::Conflict);
    }
    Ok(())
}

fn owner_id(binding: Digest32) -> String {
    format!("hepta-learning-trust:{binding}")
}

pub(super) fn verify_required_frontier(
    binding: Digest32,
    trust: &ActivatedLearningTrustV1,
    store: Option<&dyn AuthorityFrontierStore<LearningTrustFrontier>>,
) -> Result<(), ProductionLedgerError> {
    match (trust.verifier().authentication_profile(), store) {
        (_, Some(store)) => verify_learning_trust_frontier(binding, trust, store)
            .map_err(ProductionLedgerError::TrustFrontier),
        (LearningAuthenticationProfile::ClassicalV1, None) => Ok(()),
        (LearningAuthenticationProfile::MlDsa65V2, None) => Err(
            ProductionLedgerError::TrustFrontier(AuthorityTrustError::Unavailable),
        ),
    }
}

impl LedgerWriter {
    pub fn from_durable_with_trust_frontier(
        ledger: DurableLedger,
        witness: LedgerWitnessStore,
        trust: ActivatedLearningTrustV1,
        ledger_directory: &File,
        witness_directory: &File,
        frontier: Arc<dyn AuthorityFrontierStore<LearningTrustFrontier>>,
    ) -> Result<Self, ProductionLedgerError> {
        verify_learning_trust_frontier(ledger.binding_digest(), &trust, frontier.as_ref())
            .map_err(ProductionLedgerError::TrustFrontier)?;
        sync_directory_handle(ledger_directory)?;
        sync_directory_handle(witness_directory)?;
        Self::new_with_trust_frontier(
            LedgerBackend::Durable(ledger),
            witness,
            trust,
            Some(frontier),
        )
    }

    pub fn from_segmented_with_trust_frontier(
        ledger: SegmentedLedger,
        witness: LedgerWitnessStore,
        trust: ActivatedLearningTrustV1,
        segment_directory: &File,
        witness_directory: &File,
        frontier: Arc<dyn AuthorityFrontierStore<LearningTrustFrontier>>,
    ) -> Result<Self, ProductionLedgerError> {
        verify_learning_trust_frontier(ledger.binding_digest(), &trust, frontier.as_ref())
            .map_err(ProductionLedgerError::TrustFrontier)?;
        sync_directory_handle(segment_directory)?;
        sync_directory_handle(witness_directory)?;
        Self::new_with_trust_frontier(
            LedgerBackend::Segmented(ledger),
            witness,
            trust,
            Some(frontier),
        )
    }

    pub(super) fn ensure_current_trust(&self) -> Result<(), ProductionLedgerError> {
        verify_required_frontier(
            self.backend.binding(),
            &self.trust,
            self.trust_frontier_store.as_deref(),
        )
    }

    pub(super) fn advance_trust_frontier(
        &self,
        next: &ActivatedLearningTrustV1,
    ) -> Result<(), crate::LearningTrustDistributionError> {
        if let Some(store) = &self.trust_frontier_store {
            store
                .compare_and_set(
                    &owner_id(self.backend.binding()),
                    &learning_trust_frontier(&self.trust),
                    &learning_trust_frontier(next),
                )
                .map_err(crate::LearningTrustDistributionError::TrustFrontier)?;
        } else if next.verifier().authentication_profile()
            == LearningAuthenticationProfile::MlDsa65V2
        {
            return Err(crate::LearningTrustDistributionError::TrustFrontier(
                AuthorityTrustError::Unavailable,
            ));
        }
        Ok(())
    }
}
