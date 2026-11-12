//! Original B/retention data for the existing final-holdout runner.
//!
//! Only completed original Source publications and independently authenticated
//! ledger Outcomes enter this adapter. It neither executes B nor creates its
//! outcome, signers, model, holdout owner or adoption authority. The separate
//! Evaluator still reads the original Trainer and both Cell owners.
//!
//! The concrete capability is not Clone or Deserialize. All original sources,
//! the exact signed freeze and physical ledger/witness CURRENT are read again
//! before release. Cached material is never a source of rows on a later call.

use std::collections::BTreeMap;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::FinalHoldoutJournalReceiptV1;
use codex_hepta_intelligence_eval::FinalHoldoutProviderV1;
use codex_hepta_intelligence_eval::HoldoutUseDispositionV1;
use codex_hepta_intelligence_eval::ProductProviderErrorV1;
use codex_hepta_intelligence_eval::TemporalComparisonInputsV1;
use codex_hepta_intelligence_eval::TemporalEvaluationError;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CellEvaluationPlanV1;
use crate::CircuitTaskErrorV1;
use crate::CircuitTaskSourcePublicationV1;

#[path = "circuit_original_evaluation_provider_binding.rs"]
mod binding;
#[path = "circuit_original_evaluation_provider_contract.rs"]
mod contract;
#[path = "circuit_original_evaluation_provider_records.rs"]
mod records;
#[path = "circuit_original_evaluation_provider_read.rs"]
mod read;

pub use contract::OriginalCircuitEvaluationCohortConfigV1;
pub use contract::OriginalCircuitEvaluationCohortRuleV1;
pub use contract::OriginalCircuitEvaluationEpisodeV1;
pub use contract::OriginalCircuitEvaluationSourceOwnersV1;
pub use contract::OriginalCircuitEvaluationSourceV1;
pub use contract::OriginalCircuitEvaluationTargetV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitEvaluationProviderErrorV1 {
    #[error("original evaluation provider binding: {0}")]
    Binding(&'static str),
    #[error("original evaluation provider is fenced or release was already attempted")]
    Indeterminate,
    #[error("original evaluation source: {0}")]
    Source(#[from] CircuitTaskErrorV1),
    #[error("original evaluation ledger: {0}")]
    Ledger(#[from] ProductionLedgerError),
    #[error("original evaluation Training: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original evaluation signature: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original evaluation temporal plan: {0}")]
    Temporal(#[from] TemporalEvaluationError),
}

type Error = OriginalCircuitEvaluationProviderErrorV1;

struct Materialized {
    manifest: Digest32,
    dataset: DatasetSnapshotReceiptV3,
    inputs: TemporalComparisonInputsV1,
}

type Publications = BTreeMap<StableId, CircuitTaskSourcePublicationV1>;

/// One observed cohort with its original owners retained. The only public
/// observations are metadata for freezing the original evaluation plan.
/// Holding this object is not a lease on any data or an execution capability.
pub struct OriginalCircuitEvaluationCohortV1 {
    owners: OriginalCircuitEvaluationSourceOwnersV1,
    config: OriginalCircuitEvaluationCohortConfigV1,
    rule_digest: Digest32,
    manifest: Option<Digest32>,
    dataset: Option<DatasetSnapshotReceiptV3>,
    last_observed_at: u64,
    fenced: bool,
}

impl OriginalCircuitEvaluationCohortV1 {
    /// Use the original host's blocking lane. This consumes the independently
    /// owned B ledger and the concrete source views; it opens or signs nothing.
    pub fn read_original(
        owners: OriginalCircuitEvaluationSourceOwnersV1,
        config: OriginalCircuitEvaluationCohortConfigV1,
    ) -> Result<Self, Error> {
        Self::read_original_with_clock(owners, config, now)
    }

    fn read_original_with_clock(
        owners: OriginalCircuitEvaluationSourceOwnersV1,
        config: OriginalCircuitEvaluationCohortConfigV1,
        clock: impl FnMut() -> Result<u64, Error>,
    ) -> Result<Self, Error> {
        let rule_digest = binding::validate_configuration(&owners, &config)?;
        let mut owner = Self {
            owners,
            config,
            rule_digest,
            manifest: None,
            dataset: None,
            last_observed_at: 0,
            fenced: false,
        };
        let observed = owner.read_current_with_clock(clock)?;
        owner.manifest = Some(observed.manifest);
        owner.dataset = Some(observed.dataset);
        Ok(owner)
    }

    /// Metadata from the completed constructor read, not renewed permission.
    pub fn observed_manifest_digest(&self) -> Result<Digest32, Error> {
        self.manifest.ok_or(Error::Indeterminate)
    }

    pub fn observed_dataset(&self) -> Result<&DatasetSnapshotReceiptV3, Error> {
        self.dataset.as_ref().ok_or(Error::Indeterminate)
    }

    /// Bind the actual independently frozen plan after its manifest is known.
    /// The plan does not release data or change the original owner custody.
    pub fn into_final_holdout_provider(
        self,
        plan: CellEvaluationPlanV1,
    ) -> Result<OriginalCircuitFinalHoldoutProviderV1, Error> {
        binding::require_plan(&self, &plan)?;
        Ok(OriginalCircuitFinalHoldoutProviderV1 {
            original: self,
            plan,
            release_attempted: false,
        })
    }

    fn read_current_with_clock(
        &mut self,
        mut clock: impl FnMut() -> Result<u64, Error>,
    ) -> Result<Materialized, Error> {
        if self.fenced {
            return Err(Error::Indeterminate);
        }
        self.fenced = true;
        let started_at = clock()?;
        if started_at < self.last_observed_at {
            return Err(Error::Binding("system clock moved backwards"));
        }
        let observed = self.read_original_material(started_at, &mut clock)?;
        if self.manifest.is_some_and(|expected| expected != observed.manifest)
            || self.dataset.as_ref().is_some_and(|expected| expected != &observed.dataset)
        {
            return Err(Error::Binding("same exact original cohort and signatures"));
        }
        self.fenced = false;
        Ok(observed)
    }

    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// Only the original FinalHoldoutProvider path can return rows. A failed or
/// uncertain release consumes this instance; a new instance cannot bypass the
/// original holdout owner's persistent consumed state.
pub struct OriginalCircuitFinalHoldoutProviderV1 {
    original: OriginalCircuitEvaluationCohortV1,
    plan: CellEvaluationPlanV1,
    release_attempted: bool,
}

impl FinalHoldoutProviderV1 for OriginalCircuitFinalHoldoutProviderV1 {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        self.manifest_with_clock(now)
    }

    fn release_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        self.release_with_clock(receipt, now)
    }
}

impl OriginalCircuitFinalHoldoutProviderV1 {
    fn manifest_with_clock(
        &mut self,
        clock: impl FnMut() -> Result<u64, Error>,
    ) -> Result<Digest32, ProductProviderErrorV1> {
        if self.release_attempted {
            return Err(ProductProviderErrorV1::Indeterminate);
        }
        self.original
            .read_current_with_clock(clock)
            .map(|observed| observed.manifest)
            .map_err(provider_error)
    }

    fn release_with_clock(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
        clock: impl FnMut() -> Result<u64, Error>,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        if self.release_attempted {
            return Err(ProductProviderErrorV1::Indeterminate);
        }
        // Consume before receipt validation or physical I/O. A caller cannot
        // retry a failed release or classify an uncertain response as NoUpdate.
        self.release_attempted = true;
        let plan = &self.plan.product_plan().frozen_plan;
        let used = &receipt.use_receipt;
        if receipt.disposition != HoldoutUseDispositionV1::Recorded
            || used.disposition != HoldoutUseDispositionV1::Recorded
            || receipt.sequence == 0
            || receipt.record_digest.is_zero()
            || receipt.head_digest != receipt.record_digest
            || receipt.authority.grants_any()
            || used.authority.grants_any()
            || used.plan_id != plan.plan_id
            || used.plan_digest != plan.plan_digest
            || used.claim_scope != plan.claim_scope
            || used.candidate_id != plan.candidate_id
            || used.baseline_id != plan.baseline_id
            || used.objective_digest != plan.objective_digest
            || used.dataset_digest != plan.dataset_digest
            || used.estimand_digest != plan.estimand_digest
            || used.metric_contract_digest != plan.metric_contract_digest
            || used.final_holdout_window_id != plan.final_holdout_window_id
            || used.holdout_digest != plan.final_holdout_digest
            || used.registry_digest.is_zero()
            || used.use_digest.is_zero()
        {
            return Err(ProductProviderErrorV1::Rejected);
        }
        let observed = self.original.read_current_with_clock(clock).map_err(provider_error)?;
        if observed.manifest != plan.final_holdout_digest {
            return Err(ProductProviderErrorV1::Indeterminate);
        }
        Ok(observed.inputs)
    }
}

fn provider_error(error: Error) -> ProductProviderErrorV1 {
    match error {
        Error::Binding(_) | Error::Iteration(_) | Error::Evidence(_) | Error::Temporal(_) => {
            ProductProviderErrorV1::Rejected
        }
        Error::Indeterminate | Error::Source(_) | Error::Ledger(_) => {
            ProductProviderErrorV1::Indeterminate
        }
    }
}

fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs())
        .map_err(|_| Error::Binding("system clock before Unix epoch"))
}


#[cfg(test)]
#[path = "circuit_original_evaluation_provider_access_tests.rs"]
pub(crate) mod test_access;
