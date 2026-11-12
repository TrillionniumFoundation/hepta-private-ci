//! Original paired on-policy B/retention data for the same final-holdout owner.
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
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::FinalHoldoutJournalReceiptV1;
use codex_hepta_intelligence_eval::FinalHoldoutProviderV1;
use codex_hepta_intelligence_eval::HoldoutUseDispositionV1;
use codex_hepta_intelligence_eval::ProductProviderErrorV1;
use codex_hepta_intelligence_eval::OnPolicyTemporalComparisonInputsV1;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CellEvaluationPlanV1;
use crate::CircuitTaskSourcePublicationV1;
use crate::OriginalCircuitEvaluationSourceOwnersV1;
use codex_hepta_intelligence_eval::OnPolicyPairingContractV1;
use codex_hepta_intelligence_eval::TemporalComparisonInputsV1;

#[path = "circuit_on_policy_evaluation_binding.rs"]
mod binding;
#[path = "circuit_on_policy_evaluation_policy.rs"]
mod policy;
#[path = "circuit_on_policy_evaluation_policy_config.rs"]
mod policy_config;
pub use policy::OriginalCircuitOnPolicyComparisonPolicyV2;
pub use policy::OriginalCircuitOnPolicyEvaluationPolicyInputV2;
pub use policy::OriginalCircuitOnPolicyEvaluationPolicyV2;
pub use policy::OriginalCircuitOnPolicyPanelPolicyV2;
pub use policy_config::OriginalCircuitOnPolicyCohortConfigV2;
#[path = "circuit_on_policy_evaluation_contract.rs"]
mod contract;
#[path = "circuit_on_policy_evaluation_readback.rs"]
mod current;
#[path = "circuit_on_policy_evaluation_read.rs"]
mod read;
#[path = "circuit_on_policy_evaluation_records.rs"]
mod records;

#[path = "circuit_on_policy_evaluation_protocol.rs"]
mod protocol;
#[path = "circuit_on_policy_evaluation_episode.rs"]
mod episode;
#[path = "circuit_evaluation_cohort_custody.rs"]
mod cohort_custody;
pub use cohort_custody::OriginalCellEvaluationCohortCustodyV1;
pub(crate) use cohort_custody::OriginalCellEvaluationCohortCurrentV1;

pub use contract::OriginalCircuitOnPolicyCohortConfigV1;
pub use contract::OriginalCircuitOnPolicyCohortRuleV1;
pub use contract::OriginalCircuitOnPolicyHistoryV1;
pub use contract::OriginalCircuitOnPolicyPairV1;
pub use protocol::OriginalCircuitOnPolicyProtocolV1;
pub use protocol::OriginalCircuitOnPolicyAdmissionV1;
pub use current::OriginalCircuitOnPolicyCohortCurrentV1;
pub use current::OriginalCircuitOnPolicyCohortReadbackV1;

type Error = crate::OriginalCircuitEvaluationProviderErrorV1;

struct Materialized {
    manifest: Digest32,
    dataset: DatasetSnapshotReceiptV3,
    inputs: OnPolicyTemporalComparisonInputsV1,
    pairing: OnPolicyPairingContractV1,
    freeze_payload: Vec<u8>,
}

type Publications = BTreeMap<StableId, CircuitTaskSourcePublicationV1>;

/// One observed cohort with its original owners retained. The only public
/// observations are metadata for freezing the original evaluation plan.
/// Holding this object is not a lease on any data or an execution capability.
pub struct OriginalCircuitOnPolicyCohortV1 {
    owners: OriginalCircuitEvaluationSourceOwnersV1,
    config: OriginalCircuitOnPolicyCohortConfigV1,
    rule_digest: Digest32,
    policy: Option<Arc<OriginalCircuitOnPolicyPanelPolicyV2>>,
    manifest: Option<Digest32>,
    dataset: Option<DatasetSnapshotReceiptV3>,
    pairing: Option<OnPolicyPairingContractV1>,
    last_observed_at: u64,
    fenced: bool,
}

impl OriginalCircuitOnPolicyCohortV1 {
    /// Use the original host's blocking lane. This consumes the independently
    /// owned B ledger and the concrete source views; it opens or signs nothing.
    pub fn read_original(
        owners: OriginalCircuitEvaluationSourceOwnersV1,
        config: OriginalCircuitOnPolicyCohortConfigV1,
    ) -> Result<Self, Error> {
        Self::read_original_with_clock(owners, config, now)
    }

    fn read_original_with_clock(
        owners: OriginalCircuitEvaluationSourceOwnersV1,
        config: OriginalCircuitOnPolicyCohortConfigV1,
        clock: impl FnMut() -> Result<u64, Error>,
    ) -> Result<Self, Error> {
        Self::read_with_policy(owners, config, /*policy*/ None, clock)
    }

    /// Explicit V2 input. The original T must already commit this full policy.
    pub fn read_original_v2(
        owners: OriginalCircuitEvaluationSourceOwnersV1,
        config: OriginalCircuitOnPolicyCohortConfigV2,
    ) -> Result<Self, Error> {
        Self::read_with_policy(owners, config.original, Some(config.policy), now)
    }

    fn read_with_policy(
        owners: OriginalCircuitEvaluationSourceOwnersV1,
        config: OriginalCircuitOnPolicyCohortConfigV1,
        policy: Option<Arc<OriginalCircuitOnPolicyPanelPolicyV2>>,
        clock: impl FnMut() -> Result<u64, Error>,
    ) -> Result<Self, Error> {
        let rule_digest = binding::validate_configuration(&owners, &config, policy.as_deref())?;
        let mut owner = Self {
            owners,
            config,
            rule_digest,
            policy,
            manifest: None,
            dataset: None,
            pairing: None,
            last_observed_at: 0,
            fenced: false,
        };
        let observed = owner.read_current_with_clock(clock)?;
        owner.manifest = Some(observed.manifest);
        owner.dataset = Some(observed.dataset);
        owner.pairing = Some(observed.pairing);
        Ok(owner)
    }

    /// Metadata from the completed constructor read, not renewed permission.
    pub fn observed_manifest_digest(&self) -> Result<Digest32, Error> {
        self.manifest.ok_or(Error::Indeterminate)
    }

    pub fn observed_dataset(&self) -> Result<&DatasetSnapshotReceiptV3, Error> {
        self.dataset.as_ref().ok_or(Error::Indeterminate)
    }

    /// The identities are derived from the original ledger and frozen rule.
    /// No observed reward or action selects or changes either arm.
    pub fn observed_pairing_contract(&self) -> Result<&OnPolicyPairingContractV1, Error> {
        self.pairing.as_ref().ok_or(Error::Indeterminate)
    }

    /// Bind the actual independently frozen plan after its manifest is known.
    /// The plan does not release data or change the original owner custody.
    pub fn into_final_holdout_provider(
        self,
        plan: CellEvaluationPlanV1,
    ) -> Result<OriginalCircuitOnPolicyFinalHoldoutProviderV1, Error> {
        // Legacy V1 remains readable, but cannot acquire V2 release eligibility.
        crate::OriginalCircuitOnPolicyCohortV1::original_pre_b_policy(&self)?;
        binding::require_plan(&self, &plan)?;
        Ok(OriginalCircuitOnPolicyFinalHoldoutProviderV1 {
            original: self,
            plan,
            release_attempted: false,
            release_completed: false,
        })
    }

    /// Cold reconstruction retains only readonly source custody. It does not
    /// claim that any evaluation or holdout use completed and cannot release
    /// data. The panel must separately read those original completed owners.
    pub fn into_readback_only(
        self,
        plan: CellEvaluationPlanV1,
    ) -> Result<OriginalCircuitOnPolicyCohortReadbackV1, Error> {
        binding::require_plan(&self, &plan)?;
        let mut readback = OriginalCircuitOnPolicyCohortReadbackV1::retaining(self, plan);
        OriginalCircuitOnPolicyCohortReadbackV1::read_current(&mut readback)?;
        Ok(readback)
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
        let observed = OriginalCircuitOnPolicyCohortV1::read_original_material(
            self, started_at, &mut clock,
        )?;
        if self
            .manifest
            .is_some_and(|expected| expected != observed.manifest)
            || self
                .dataset
                .as_ref()
                .is_some_and(|expected| expected != &observed.dataset)
            || self.pairing.as_ref().is_some_and(|expected| expected != &observed.pairing)
        {
            return Err(Error::Binding("same exact original cohort and signatures"));
        }
        self.fenced = false;
        Ok(observed)
    }

    pub(crate) fn original_pre_b_policy(
        &self,
    ) -> Result<(&OriginalCircuitOnPolicyEvaluationPolicyV2, &codex_hepta_learning_artifacts::LearningIterationSnapshotV1), Error> {
        let panel = self.policy.as_ref()
            .ok_or(Error::Binding("legacy paired V1 has no V2 pre-B policy"))?;
        crate::OriginalCircuitOnPolicyPanelPolicyV2::require_original_panel_training(panel, &self.config.training)?;
        let policy = panel.member(&self.config.rule.plan_id)?;
        crate::OriginalCircuitOnPolicyEvaluationPolicyV2::require_original_rule(policy, &self.config.rule, &self.owners.ledger)?;
        Ok((policy, &self.config.training))
    }

    pub(crate) fn require_original_pre_b_plan(&self, plan: &CellEvaluationPlanV1) -> Result<(), Error> {
        crate::OriginalCircuitOnPolicyCohortV1::original_pre_b_policy(self)?;
        binding::require_plan(self, plan)
    }

    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// Only the original FinalHoldoutProvider path can return rows. A failed or
/// uncertain release consumes this instance; a new instance cannot bypass the
/// original holdout owner's persistent consumed state.
pub struct OriginalCircuitOnPolicyFinalHoldoutProviderV1 {
    original: OriginalCircuitOnPolicyCohortV1,
    plan: CellEvaluationPlanV1,
    release_attempted: bool,
    release_completed: bool,
}

impl FinalHoldoutProviderV1 for OriginalCircuitOnPolicyFinalHoldoutProviderV1 {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        self.manifest_with_clock(now)
    }

    fn release_after_consumption(
        &mut self,
        _receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        // A paired cohort cannot be relabeled as legacy shared behavior.
        self.release_attempted = true;
        Err(ProductProviderErrorV1::Rejected)
    }

    fn release_paired_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
        pairing: &OnPolicyPairingContractV1,
    ) -> Result<OnPolicyTemporalComparisonInputsV1, ProductProviderErrorV1> {
        self.release_with_clock(receipt, pairing, now)
    }
}

impl OriginalCircuitOnPolicyFinalHoldoutProviderV1 {
    /// Consume only this instance's successful original release. Failed and
    /// uncertain releases never acquire a completed brand. The returned owner
    /// can only re-read the same original sources; it cannot release again.
    pub fn into_original_readback(
        self,
    ) -> Result<OriginalCircuitOnPolicyCohortReadbackV1, Error> {
        if !self.release_completed || self.original.fenced {
            return Err(Error::Indeterminate);
        }
        Ok(OriginalCircuitOnPolicyCohortReadbackV1::retaining(
            self.original,
            self.plan,
        ))
    }

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
        pairing: &OnPolicyPairingContractV1,
        clock: impl FnMut() -> Result<u64, Error>,
    ) -> Result<OnPolicyTemporalComparisonInputsV1, ProductProviderErrorV1> {
        if self.release_attempted {
            return Err(ProductProviderErrorV1::Indeterminate);
        }
        // Consume before receipt validation or physical I/O. A caller cannot
        // retry a failed release or classify an uncertain response as NoUpdate.
        self.release_attempted = true;
        crate::OriginalCircuitOnPolicyCohortV1::require_original_pre_b_plan(&self.original, &self.plan).map_err(provider_error)?;
        let plan = &self.plan.product_plan().frozen_plan;
        let used = &receipt.use_receipt;
        if self.original.pairing.as_ref() != Some(pairing)
            || receipt.disposition != HoldoutUseDispositionV1::Recorded
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
        let observed = self
            .original
            .read_current_with_clock(clock)
            .map_err(provider_error)?;
        if observed.manifest != plan.final_holdout_digest || &observed.pairing != pairing {
            return Err(ProductProviderErrorV1::Indeterminate);
        }
        self.release_completed = true;
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

