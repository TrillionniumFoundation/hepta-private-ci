//! Production cut provider over the original locked custody owner. It releases
//! only the original signed O transport, after positional canonical CAS replay.
//! It neither signs metrics nor starts a model or creates a second holdout owner.
use crate::AuthenticatedPairedRegistrationV1;
use crate::FinalHoldoutCasAnchorV1;
use crate::FinalHoldoutJournalReceiptV1;
use crate::LockedFileCasErrorV1;
use crate::LockedFileFinalHoldoutCasStoreV1;
use crate::PairedFinalHoldoutProviderV1;
use crate::ProductProviderErrorV1;
use crate::SignedPairedObservationCutV1;
use crate::fenced_holdout_file::HeldPairedConsumptionV1;
use crate::paired_observer_transport::MAX_TRANSPORT_BYTES;
use crate::paired_observer_transport::decode_transport;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_types::Digest32;
use std::path::Path;
use std::path::PathBuf;

pub(crate) struct ProtectedPairedObservationProviderV1 {
    consumption: HeldPairedConsumptionV1,
    registration: AuthenticatedPairedRegistrationV1,
    cut_path: PathBuf,
    manifest: Digest32,
    attempted: bool,
}

impl ProtectedPairedObservationProviderV1 {
    pub(crate) fn open(
        store: &LockedFileFinalHoldoutCasStoreV1,
        original_cas_path: &Path,
        original_witness_path: &Path,
        original_cut_path: &Path,
        registration: &AuthenticatedPairedRegistrationV1,
    ) -> Result<Self, ProductProviderErrorV1> {
        // The original independent witness identifies the actual cohort. A
        // caller's preregistration cannot substitute itself as source metadata.
        let bytes = read_root_review_input(original_witness_path, 16 * 1024)
            .map_err(|_| ProductProviderErrorV1::Unavailable)?;
        let witness: crate::fixed_holdout_custody::Witness =
            serde_json::from_slice(&bytes).map_err(|_| ProductProviderErrorV1::Rejected)?;
        let manifest = witness
            .private_gold_digest
            .parse::<Digest32>()
            .map_err(|_| ProductProviderErrorV1::Rejected)?;
        let binding = witness
            .binding
            .parse::<Digest32>()
            .map_err(|_| ProductProviderErrorV1::Rejected)?;
        let config = witness
            .config_digest
            .parse::<Digest32>()
            .map_err(|_| ProductProviderErrorV1::Rejected)?;
        let binding_bytes = serde_json::to_vec(&serde_json::json!({
            "domain":"hepta.fixed-source-holdout.binding.v1", "config":config.to_string(), "gold":manifest.to_string()
        })).map_err(|_| ProductProviderErrorV1::Rejected)?;
        if witness.schema != "hepta.fixed-source-holdout.witness.v1"
            || manifest.is_zero()
            || config.is_zero()
            || Digest32::of_bytes(&binding_bytes) != binding
        {
            return Err(ProductProviderErrorV1::Rejected);
        }
        let minimum = FinalHoldoutCasAnchorV1 {
            fence_generation: witness.fence_generation,
            record_count: witness.record_count,
            state_digest: witness
                .state_digest
                .parse()
                .map_err(|_| ProductProviderErrorV1::Rejected)?,
        };
        let consumption = store
            .paired_consumption_reader(original_cas_path, binding, minimum)
            .map_err(|_| ProductProviderErrorV1::Rejected)?;
        Ok(Self {
            consumption,
            registration: registration.clone(),
            cut_path: original_cut_path.to_owned(),
            manifest,
            attempted: false,
        })
    }
}

impl PairedFinalHoldoutProviderV1 for ProtectedPairedObservationProviderV1 {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        // Preregistered metadata does not inspect observations or private gold.
        Ok(self.manifest)
    }

    fn release_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<SignedPairedObservationCutV1, ProductProviderErrorV1> {
        if self.attempted {
            return Err(ProductProviderErrorV1::Indeterminate);
        }
        self.consumption
            .verify(&self.registration.plan.frozen, receipt)
            .map_err(|error| match error {
                LockedFileCasErrorV1::Binding => ProductProviderErrorV1::Rejected,
                _ => ProductProviderErrorV1::Indeterminate,
            })?;
        // A failed transport read never means the original committed use did
        // not occur. The original runner rejects subsequent consumption replay.
        self.attempted = true;
        let bytes = read_root_review_input(&self.cut_path, MAX_TRANSPORT_BYTES)
            .map_err(|_| ProductProviderErrorV1::Unavailable)?;
        let observations =
            decode_transport(&bytes).map_err(|_| ProductProviderErrorV1::Rejected)?;
        if observations.cut.plan_digest != self.registration.plan.frozen.plan_digest
            || observations.cut.source_graph_digest != self.registration.plan.source_graph_digest()
            || observations.cut.runtime != self.registration.plan.runtime
        {
            return Err(ProductProviderErrorV1::Rejected);
        }
        // Original G/O/epoch/clock checks, O signature, complete source coverage
        // and estimation remain in the registered runner; E is independent.
        Ok(observations)
    }
}

#[cfg(test)]
#[path = "protected_paired_provider_tests.rs"]
mod tests;
