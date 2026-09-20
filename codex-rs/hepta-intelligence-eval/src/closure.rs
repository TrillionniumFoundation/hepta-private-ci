//! Independent evaluation composition above the estimator primitives.
//!
//! Estimators remain pure evidence producers. This module checks supplied
//! role separation, frozen K-fold lineage, final-holdout use, conservative
//! interval gates, future-window coverage, retention and unlearning before it
//! emits an eligibility decision. Eligibility is still not selection, promotion
//! or release authority. External claims require the signed-evaluation entry
//! points to authenticate those supplied identities and evidence bytes.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CausalV2Error;
use codex_hepta_learning_ledger::verify_independent_roles;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

#[path = "metric_roles.rs"]
mod metric_roles;

pub use metric_roles::MetricRoleContractV2;
pub use metric_roles::MetricRoleV2;
pub use metric_roles::decide_independently_v2;
pub(crate) use metric_roles::digest_evaluation_roles;
pub use metric_roles::freeze_cross_fold_plan_v2;

#[path = "holdout_codec.rs"]
mod holdout_codec;
pub(crate) use holdout_codec::decode as decode_holdout_plan;
pub(crate) use holdout_codec::encode as encode_holdout_plan;

const MAX_FOLDS: usize = 32;
const MAX_METRICS: usize = 128;
const MAX_LINEAGE_IDS: usize = 1_000_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EvaluationClaimScopeV1 {
    Qualification,
    SystemLongitudinal,
}

impl EvaluationClaimScopeV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Qualification => 0,
            Self::SystemLongitudinal => 1,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EvaluationDirectionV1 {
    Maximize,
    Minimize,
}

impl EvaluationDirectionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Maximize => 0,
            Self::Minimize => 1,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EvaluationIntervalV1 {
    pub lower: FixedQ32,
    pub upper: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MetricGateV1 {
    pub metric_id: StableId,
    pub direction: EvaluationDirectionV1,
    pub candidate: EvaluationIntervalV1,
    pub baseline: EvaluationIntervalV1,
    pub safety_floor: Option<FixedQ32>,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MetricContractV1 {
    pub metric_id: StableId,
    pub direction: EvaluationDirectionV1,
    pub safety_floor: Option<FixedQ32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IndependentEvaluationBundleV1 {
    pub evaluation_id: StableId,
    pub candidate_id: StableId,
    pub baseline_id: StableId,
    pub claim_scope: EvaluationClaimScopeV1,
    pub generator: AuthenticatedPrincipalV1,
    pub evaluator: AuthenticatedPrincipalV1,
    pub frozen_plan: CrossFoldPlanReceiptV1,
    pub holdout_use: HoldoutUseReceiptV1,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub estimand_digest: Digest32,
    pub estimate_receipt_digest: Digest32,
    pub support_audit_digest: Digest32,
    pub confidence_receipt_digest: Digest32,
    pub retention_receipt_digests: Vec<Digest32>,
    pub unlearning_receipt_digest: Digest32,
    pub snapshot_ids: Vec<StableId>,
    pub future_window_ids: Vec<StableId>,
    pub family_alpha_ppm: u32,
    pub simultaneous_comparisons: u32,
    pub metrics: Vec<MetricGateV1>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IndependentEvaluationDispositionV1 {
    EligibleForIndependentSelection,
    Ineligible,
    InsufficientEvidence,
}

impl IndependentEvaluationDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::EligibleForIndependentSelection => 0,
            Self::Ineligible => 1,
            Self::InsufficientEvidence => 2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IndependentEvaluationDecisionV1 {
    pub evaluation_id: StableId,
    pub candidate_id: StableId,
    pub baseline_id: StableId,
    pub disposition: IndependentEvaluationDispositionV1,
    pub failed_metrics: Vec<StableId>,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// Legacy contract: every metric must strictly outperform its baseline.
/// Use [`decide_independently_v2`] for preregistered metric roles.
pub fn decide_independently(
    bundle: IndependentEvaluationBundleV1,
    now: u64,
) -> Result<IndependentEvaluationDecisionV1, EvaluationClosureError> {
    let contract_digest = digest_metric_contracts(&mut metric_contracts(&bundle.metrics))?;
    decide_with_metric_contract(bundle, now, contract_digest, |metric| {
        match metric.direction {
            EvaluationDirectionV1::Maximize => metric.candidate.lower > metric.baseline.upper,
            EvaluationDirectionV1::Minimize => metric.candidate.upper < metric.baseline.lower,
        }
    })
}

fn decide_with_metric_contract(
    mut bundle: IndependentEvaluationBundleV1,
    now: u64,
    contract_digest: Digest32,
    relative_gate: impl Fn(&MetricGateV1) -> bool,
) -> Result<IndependentEvaluationDecisionV1, EvaluationClosureError> {
    verify_independent_roles(&bundle.generator, &bundle.evaluator, now)?;
    for (label, digest) in [
        ("objective", bundle.objective_digest),
        ("evaluation dataset", bundle.dataset_digest),
        ("estimand", bundle.estimand_digest),
        ("estimate receipt", bundle.estimate_receipt_digest),
        ("support audit", bundle.support_audit_digest),
        ("confidence receipt", bundle.confidence_receipt_digest),
    ] {
        require_digest(digest, label)?;
    }
    if !(1..=100_000).contains(&bundle.family_alpha_ppm)
        || !(1..=1_024).contains(&bundle.simultaneous_comparisons)
    {
        return Err(EvaluationClosureError::MultiplicityProfile);
    }
    if bundle.metrics.len() > MAX_METRICS {
        return Err(EvaluationClosureError::MetricLimit);
    }
    normalize_unique_ids(&mut bundle.snapshot_ids)?;
    normalize_unique_ids(&mut bundle.future_window_ids)?;
    bundle.retention_receipt_digests.sort_unstable();
    reject_duplicate_digests(&bundle.retention_receipt_digests)?;
    if bundle
        .retention_receipt_digests
        .iter()
        .any(|digest| digest.is_zero())
    {
        return Err(EvaluationClosureError::EmptyDigest("retention receipt"));
    }
    bundle
        .metrics
        .sort_by_key(|metric| metric.metric_id.clone());
    if let Some(adjacent) = bundle
        .metrics
        .windows(2)
        .find(|adjacent| adjacent[0].metric_id == adjacent[1].metric_id)
    {
        return Err(EvaluationClosureError::DuplicateMetric(
            adjacent[0].metric_id.to_string(),
        ));
    }
    validate_frozen_evaluation_binding(&bundle, contract_digest)?;

    let mut insufficient = bundle.metrics.is_empty();
    match bundle.claim_scope {
        EvaluationClaimScopeV1::Qualification => {
            insufficient |= bundle.snapshot_ids.is_empty() || bundle.future_window_ids.is_empty();
        }
        EvaluationClaimScopeV1::SystemLongitudinal => {
            insufficient |= bundle.snapshot_ids.len() < 3
                || bundle.future_window_ids.len() < 2
                || bundle.retention_receipt_digests.is_empty()
                || bundle.unlearning_receipt_digest.is_zero();
        }
    }

    let mut failed_metrics = Vec::new();
    for metric in &bundle.metrics {
        if metric.candidate.lower > metric.candidate.upper
            || metric.baseline.lower > metric.baseline.upper
        {
            return Err(EvaluationClosureError::InvalidInterval(
                metric.metric_id.to_string(),
            ));
        }
        if metric.support_digest.is_zero() {
            insufficient = true;
            continue;
        }
        let safety = metric
            .safety_floor
            .is_none_or(|floor| match metric.direction {
                EvaluationDirectionV1::Maximize => metric.candidate.lower >= floor,
                EvaluationDirectionV1::Minimize => metric.candidate.upper <= floor,
            });
        if !relative_gate(metric) || !safety {
            failed_metrics.push(metric.metric_id.clone());
        }
    }

    let disposition = if !failed_metrics.is_empty() {
        IndependentEvaluationDispositionV1::Ineligible
    } else if insufficient {
        IndependentEvaluationDispositionV1::InsufficientEvidence
    } else {
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    };
    let evidence_digest = digest_evaluation_bundle(&bundle, disposition, &failed_metrics)?;
    Ok(IndependentEvaluationDecisionV1 {
        evaluation_id: bundle.evaluation_id,
        candidate_id: bundle.candidate_id,
        baseline_id: bundle.baseline_id,
        disposition,
        failed_metrics,
        evidence_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CrossFoldPartitionV1 {
    pub fold_id: StableId,
    pub training_principals: Vec<StableId>,
    pub training_episodes: Vec<StableId>,
    pub training_windows: Vec<StableId>,
    pub holdout_principals: Vec<StableId>,
    pub holdout_episodes: Vec<StableId>,
    pub holdout_windows: Vec<StableId>,
    pub model_digest: Digest32,
    pub predictions_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CrossFoldPlanV1 {
    pub plan_id: StableId,
    pub claim_scope: EvaluationClaimScopeV1,
    pub candidate_id: StableId,
    pub baseline_id: StableId,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub estimand_digest: Digest32,
    pub metric_contracts: Vec<MetricContractV1>,
    pub family_alpha_ppm: u32,
    pub simultaneous_comparisons: u32,
    pub folds: Vec<CrossFoldPartitionV1>,
    pub final_holdout_window_id: StableId,
    pub final_holdout_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CrossFoldPlanReceiptV1 {
    pub plan_id: StableId,
    pub claim_scope: EvaluationClaimScopeV1,
    pub candidate_id: StableId,
    pub baseline_id: StableId,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub estimand_digest: Digest32,
    pub metric_contract_digest: Digest32,
    pub family_alpha_ppm: u32,
    pub simultaneous_comparisons: u32,
    pub final_holdout_window_id: StableId,
    pub final_holdout_digest: Digest32,
    pub fold_count: u32,
    pub plan_digest: Digest32,
    pub authority: AuthorityPosture,
    receipt_seal: Digest32,
}

pub fn freeze_cross_fold_plan(
    mut plan: CrossFoldPlanV1,
) -> Result<CrossFoldPlanReceiptV1, EvaluationClosureError> {
    if !(2..=MAX_FOLDS).contains(&plan.folds.len()) {
        return Err(EvaluationClosureError::FoldLimit);
    }
    for (label, digest) in [
        ("evaluation objective", plan.objective_digest),
        ("evaluation dataset", plan.dataset_digest),
        ("evaluation estimand", plan.estimand_digest),
        ("final holdout", plan.final_holdout_digest),
    ] {
        require_digest(digest, label)?;
    }
    if !(1..=100_000).contains(&plan.family_alpha_ppm)
        || !(1..=1_024).contains(&plan.simultaneous_comparisons)
    {
        return Err(EvaluationClosureError::MultiplicityProfile);
    }
    let metric_contract_digest = digest_metric_contracts(&mut plan.metric_contracts)?;
    plan.folds.sort_by_key(|fold| fold.fold_id.clone());
    if let Some(adjacent) = plan
        .folds
        .windows(2)
        .find(|adjacent| adjacent[0].fold_id == adjacent[1].fold_id)
    {
        return Err(EvaluationClosureError::DuplicateFold(
            adjacent[0].fold_id.to_string(),
        ));
    }

    let mut held_out_principals = BTreeSet::new();
    let mut held_out_episodes = BTreeSet::new();
    let mut held_out_windows = BTreeSet::new();
    let mut final_holdout_count = 0_usize;
    for fold in &mut plan.folds {
        require_digest(fold.model_digest, "fold model")?;
        require_digest(fold.predictions_digest, "fold predictions")?;
        for values in [
            &mut fold.training_principals,
            &mut fold.training_episodes,
            &mut fold.training_windows,
            &mut fold.holdout_principals,
            &mut fold.holdout_episodes,
            &mut fold.holdout_windows,
        ] {
            if values.is_empty() || values.len() > MAX_LINEAGE_IDS {
                return Err(EvaluationClosureError::FoldLineageLimit);
            }
            normalize_unique_ids(values)?;
        }
        if sorted_sets_overlap(&fold.training_principals, &fold.holdout_principals)
            || sorted_sets_overlap(&fold.training_episodes, &fold.holdout_episodes)
            || sorted_sets_overlap(&fold.training_windows, &fold.holdout_windows)
        {
            return Err(EvaluationClosureError::CrossFoldLeakage(
                fold.fold_id.to_string(),
            ));
        }
        if fold
            .training_windows
            .contains(&plan.final_holdout_window_id)
        {
            return Err(EvaluationClosureError::FinalHoldoutLeakage);
        }
        final_holdout_count +=
            usize::from(fold.holdout_windows.contains(&plan.final_holdout_window_id));
        insert_unique_holdouts(&mut held_out_principals, &fold.holdout_principals)?;
        insert_unique_holdouts(&mut held_out_episodes, &fold.holdout_episodes)?;
        insert_unique_holdouts(&mut held_out_windows, &fold.holdout_windows)?;
    }
    if final_holdout_count != 1 {
        return Err(EvaluationClosureError::FinalHoldoutCoverage);
    }

    let mut bytes = b"hepta.intelligence-eval.cross-fold-plan.v2".to_vec();
    push_id(&mut bytes, &plan.plan_id);
    push_id(&mut bytes, &plan.candidate_id);
    push_id(&mut bytes, &plan.baseline_id);
    push_id(&mut bytes, &plan.final_holdout_window_id);
    bytes.push(plan.claim_scope.tag());
    for digest in [
        plan.objective_digest,
        plan.dataset_digest,
        plan.estimand_digest,
        metric_contract_digest,
        plan.final_holdout_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&plan.family_alpha_ppm.to_be_bytes());
    bytes.extend_from_slice(&plan.simultaneous_comparisons.to_be_bytes());
    bytes.extend_from_slice(
        &u32::try_from(plan.folds.len())
            .map_err(|_| EvaluationClosureError::Arithmetic)?
            .to_be_bytes(),
    );
    for fold in &plan.folds {
        push_id(&mut bytes, &fold.fold_id);
        push_id_vec(&mut bytes, &fold.training_principals)?;
        push_id_vec(&mut bytes, &fold.training_episodes)?;
        push_id_vec(&mut bytes, &fold.training_windows)?;
        push_id_vec(&mut bytes, &fold.holdout_principals)?;
        push_id_vec(&mut bytes, &fold.holdout_episodes)?;
        push_id_vec(&mut bytes, &fold.holdout_windows)?;
        bytes.extend_from_slice(fold.model_digest.as_array());
        bytes.extend_from_slice(fold.predictions_digest.as_array());
    }
    let plan_digest = Digest32::of_bytes(&bytes);
    let mut receipt = CrossFoldPlanReceiptV1 {
        plan_id: plan.plan_id,
        claim_scope: plan.claim_scope,
        candidate_id: plan.candidate_id,
        baseline_id: plan.baseline_id,
        objective_digest: plan.objective_digest,
        dataset_digest: plan.dataset_digest,
        estimand_digest: plan.estimand_digest,
        metric_contract_digest,
        family_alpha_ppm: plan.family_alpha_ppm,
        simultaneous_comparisons: plan.simultaneous_comparisons,
        final_holdout_window_id: plan.final_holdout_window_id,
        final_holdout_digest: plan.final_holdout_digest,
        fold_count: u32::try_from(plan.folds.len())
            .map_err(|_| EvaluationClosureError::Arithmetic)?,
        plan_digest,
        authority: AuthorityPosture::DENY_ALL,
        receipt_seal: Digest32::ZERO,
    };
    receipt.receipt_seal = frozen_plan_receipt_seal(&receipt);
    Ok(receipt)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HoldoutUseDispositionV1 {
    Recorded,
    IdempotentReplay,
}

impl HoldoutUseDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Recorded => 0,
            Self::IdempotentReplay => 1,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HoldoutUseReceiptV1 {
    pub disposition: HoldoutUseDispositionV1,
    pub holdout_digest: Digest32,
    pub plan_id: StableId,
    pub claim_scope: EvaluationClaimScopeV1,
    pub plan_digest: Digest32,
    pub candidate_id: StableId,
    pub baseline_id: StableId,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub estimand_digest: Digest32,
    pub metric_contract_digest: Digest32,
    pub final_holdout_window_id: StableId,
    pub registry_digest: Digest32,
    pub use_digest: Digest32,
    pub authority: AuthorityPosture,
    receipt_seal: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct HoldoutBindingV1 {
    holdout_digest: Digest32,
    plan_id: StableId,
    claim_scope: EvaluationClaimScopeV1,
    plan_digest: Digest32,
    candidate_id: StableId,
    baseline_id: StableId,
    objective_digest: Digest32,
    dataset_digest: Digest32,
    estimand_digest: Digest32,
    metric_contract_digest: Digest32,
    final_holdout_window_id: StableId,
}

impl HoldoutBindingV1 {
    fn from_plan(plan: &CrossFoldPlanReceiptV1) -> Self {
        Self {
            holdout_digest: plan.final_holdout_digest,
            plan_id: plan.plan_id.clone(),
            claim_scope: plan.claim_scope,
            plan_digest: plan.plan_digest,
            candidate_id: plan.candidate_id.clone(),
            baseline_id: plan.baseline_id.clone(),
            objective_digest: plan.objective_digest,
            dataset_digest: plan.dataset_digest,
            estimand_digest: plan.estimand_digest,
            metric_contract_digest: plan.metric_contract_digest,
            final_holdout_window_id: plan.final_holdout_window_id.clone(),
        }
    }

    fn append_to(&self, bytes: &mut Vec<u8>) {
        bytes.extend_from_slice(self.holdout_digest.as_array());
        push_id(bytes, &self.plan_id);
        bytes.push(self.claim_scope.tag());
        bytes.extend_from_slice(self.plan_digest.as_array());
        push_id(bytes, &self.candidate_id);
        push_id(bytes, &self.baseline_id);
        for digest in [
            self.objective_digest,
            self.dataset_digest,
            self.estimand_digest,
            self.metric_contract_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_id(bytes, &self.final_holdout_window_id);
    }

    fn use_digest(&self, registry_digest: Digest32) -> Digest32 {
        let mut bytes = b"hepta.intelligence-eval.final-holdout-use.v2".to_vec();
        self.append_to(&mut bytes);
        bytes.extend_from_slice(registry_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct HoldoutUseRecordV1 {
    binding: HoldoutBindingV1,
    registry_digest: Digest32,
    use_digest: Digest32,
}

#[derive(Clone, Debug, Default)]
pub struct FinalHoldoutRegistry {
    uses_by_holdout: BTreeMap<Digest32, StableId>,
    uses_by_window: BTreeMap<StableId, StableId>,
    uses_by_plan: BTreeMap<StableId, HoldoutUseRecordV1>,
}

impl FinalHoldoutRegistry {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn consume(
        &mut self,
        plan: &CrossFoldPlanReceiptV1,
    ) -> Result<HoldoutUseReceiptV1, EvaluationClosureError> {
        validate_frozen_plan_receipt_integrity(plan)?;
        if plan.authority.grants_any() {
            return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
                "authority",
            ));
        }
        for (label, digest) in [
            ("frozen plan", plan.plan_digest),
            ("evaluation objective", plan.objective_digest),
            ("evaluation dataset", plan.dataset_digest),
            ("evaluation estimand", plan.estimand_digest),
            ("metric contract", plan.metric_contract_digest),
            ("final holdout", plan.final_holdout_digest),
        ] {
            require_digest(digest, label)?;
        }
        let binding = HoldoutBindingV1::from_plan(plan);
        if let Some(existing) = self.uses_by_plan.get(&binding.plan_id) {
            if existing.binding != binding {
                return Err(EvaluationClosureError::FinalHoldoutIdentityConflict(
                    binding.plan_id.to_string(),
                ));
            }
            if self.uses_by_holdout.get(&binding.holdout_digest) != Some(&binding.plan_id)
                || self.uses_by_window.get(&binding.final_holdout_window_id)
                    != Some(&binding.plan_id)
            {
                return Err(EvaluationClosureError::InternalInvariant);
            }
            return Ok(holdout_use_receipt(
                &existing.binding,
                HoldoutUseDispositionV1::IdempotentReplay,
                existing.registry_digest,
                existing.use_digest,
            ));
        }
        if self.uses_by_holdout.contains_key(&binding.holdout_digest)
            || self
                .uses_by_window
                .contains_key(&binding.final_holdout_window_id)
        {
            return Err(EvaluationClosureError::FinalHoldoutReused);
        }
        self.uses_by_holdout
            .insert(binding.holdout_digest, binding.plan_id.clone());
        self.uses_by_window.insert(
            binding.final_holdout_window_id.clone(),
            binding.plan_id.clone(),
        );
        self.uses_by_plan.insert(
            binding.plan_id.clone(),
            HoldoutUseRecordV1 {
                binding: binding.clone(),
                registry_digest: Digest32::ZERO,
                use_digest: Digest32::ZERO,
            },
        );
        let registry_digest = self.digest();
        let use_digest = binding.use_digest(registry_digest);
        let record = self
            .uses_by_plan
            .get_mut(&binding.plan_id)
            .ok_or(EvaluationClosureError::InternalInvariant)?;
        record.registry_digest = registry_digest;
        record.use_digest = use_digest;
        Ok(holdout_use_receipt(
            &record.binding,
            HoldoutUseDispositionV1::Recorded,
            record.registry_digest,
            record.use_digest,
        ))
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.intelligence-eval.final-holdout-registry.v2".to_vec();
        for record in self.uses_by_plan.values() {
            record.binding.append_to(&mut bytes);
        }
        Digest32::of_bytes(&bytes)
    }
}

fn holdout_use_receipt(
    binding: &HoldoutBindingV1,
    disposition: HoldoutUseDispositionV1,
    registry_digest: Digest32,
    use_digest: Digest32,
) -> HoldoutUseReceiptV1 {
    let mut receipt = HoldoutUseReceiptV1 {
        disposition,
        holdout_digest: binding.holdout_digest,
        plan_id: binding.plan_id.clone(),
        claim_scope: binding.claim_scope,
        plan_digest: binding.plan_digest,
        candidate_id: binding.candidate_id.clone(),
        baseline_id: binding.baseline_id.clone(),
        objective_digest: binding.objective_digest,
        dataset_digest: binding.dataset_digest,
        estimand_digest: binding.estimand_digest,
        metric_contract_digest: binding.metric_contract_digest,
        final_holdout_window_id: binding.final_holdout_window_id.clone(),
        registry_digest,
        use_digest,
        authority: AuthorityPosture::DENY_ALL,
        receipt_seal: Digest32::ZERO,
    };
    receipt.receipt_seal = holdout_use_receipt_seal(&receipt);
    receipt
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EvaluationClosureError {
    Role(CausalV2Error),
    EmptyDigest(&'static str),
    FrozenPlanReceiptIntegrity,
    HoldoutUseReceiptIntegrity,
    FrozenPlanBindingMismatch(&'static str),
    HoldoutUseBindingMismatch(&'static str),
    FinalHoldoutIdentityConflict(String),
    FinalHoldoutReused,
    InternalInvariant,
    MultiplicityProfile,
    MetricLimit,
    DuplicateMetric(String),
    DuplicateLineage(String),
    DuplicateDigest,
    InvalidInterval(String),
    FoldLimit,
    FoldLineageLimit,
    DuplicateFold(String),
    CrossFoldLeakage(String),
    HoldoutAppearsInMultipleFolds(String),
    FinalHoldoutLeakage,
    FinalHoldoutCoverage,
    Arithmetic,
}

impl fmt::Display for EvaluationClosureError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for EvaluationClosureError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Role(error) => Some(error),
            Self::EmptyDigest(_)
            | Self::FrozenPlanReceiptIntegrity
            | Self::HoldoutUseReceiptIntegrity
            | Self::FrozenPlanBindingMismatch(_)
            | Self::HoldoutUseBindingMismatch(_)
            | Self::FinalHoldoutIdentityConflict(_)
            | Self::FinalHoldoutReused
            | Self::InternalInvariant
            | Self::MultiplicityProfile
            | Self::MetricLimit
            | Self::DuplicateMetric(_)
            | Self::DuplicateLineage(_)
            | Self::DuplicateDigest
            | Self::InvalidInterval(_)
            | Self::FoldLimit
            | Self::FoldLineageLimit
            | Self::DuplicateFold(_)
            | Self::CrossFoldLeakage(_)
            | Self::HoldoutAppearsInMultipleFolds(_)
            | Self::FinalHoldoutLeakage
            | Self::FinalHoldoutCoverage
            | Self::Arithmetic => None,
        }
    }
}

impl From<CausalV2Error> for EvaluationClosureError {
    fn from(value: CausalV2Error) -> Self {
        Self::Role(value)
    }
}

fn frozen_plan_receipt_seal(receipt: &CrossFoldPlanReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.frozen-plan-receipt-seal.v1".to_vec();
    push_id(&mut bytes, &receipt.plan_id);
    bytes.push(receipt.claim_scope.tag());
    push_id(&mut bytes, &receipt.candidate_id);
    push_id(&mut bytes, &receipt.baseline_id);
    for digest in [
        receipt.objective_digest,
        receipt.dataset_digest,
        receipt.estimand_digest,
        receipt.metric_contract_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.family_alpha_ppm.to_be_bytes());
    bytes.extend_from_slice(&receipt.simultaneous_comparisons.to_be_bytes());
    push_id(&mut bytes, &receipt.final_holdout_window_id);
    bytes.extend_from_slice(receipt.final_holdout_digest.as_array());
    bytes.extend_from_slice(&receipt.fold_count.to_be_bytes());
    bytes.extend_from_slice(receipt.plan_digest.as_array());
    bytes.push(u8::from(receipt.authority.grants_any()));
    Digest32::of_bytes(&bytes)
}

fn validate_frozen_plan_receipt_integrity(
    receipt: &CrossFoldPlanReceiptV1,
) -> Result<(), EvaluationClosureError> {
    if receipt.receipt_seal != frozen_plan_receipt_seal(receipt) {
        return Err(EvaluationClosureError::FrozenPlanReceiptIntegrity);
    }
    Ok(())
}

fn holdout_use_receipt_seal(receipt: &HoldoutUseReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.holdout-use-receipt-seal.v1".to_vec();
    bytes.push(receipt.disposition.tag());
    bytes.extend_from_slice(receipt.holdout_digest.as_array());
    push_id(&mut bytes, &receipt.plan_id);
    bytes.push(receipt.claim_scope.tag());
    bytes.extend_from_slice(receipt.plan_digest.as_array());
    push_id(&mut bytes, &receipt.candidate_id);
    push_id(&mut bytes, &receipt.baseline_id);
    for digest in [
        receipt.objective_digest,
        receipt.dataset_digest,
        receipt.estimand_digest,
        receipt.metric_contract_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &receipt.final_holdout_window_id);
    bytes.extend_from_slice(receipt.registry_digest.as_array());
    bytes.extend_from_slice(receipt.use_digest.as_array());
    bytes.push(u8::from(receipt.authority.grants_any()));
    Digest32::of_bytes(&bytes)
}

fn validate_holdout_use_receipt_integrity(
    receipt: &HoldoutUseReceiptV1,
) -> Result<(), EvaluationClosureError> {
    if receipt.receipt_seal != holdout_use_receipt_seal(receipt) {
        return Err(EvaluationClosureError::HoldoutUseReceiptIntegrity);
    }
    Ok(())
}

pub(crate) fn digest_evaluation_bundle(
    bundle: &IndependentEvaluationBundleV1,
    disposition: IndependentEvaluationDispositionV1,
    failed_metrics: &[StableId],
) -> Result<Digest32, EvaluationClosureError> {
    let mut bytes = b"hepta.intelligence-eval.independent-decision.v1".to_vec();
    push_id(&mut bytes, &bundle.evaluation_id);
    push_id(&mut bytes, &bundle.candidate_id);
    push_id(&mut bytes, &bundle.baseline_id);
    bytes.push(bundle.claim_scope.tag());
    push_principal(&mut bytes, &bundle.generator);
    push_principal(&mut bytes, &bundle.evaluator);
    for digest in [
        bundle.frozen_plan.plan_digest,
        bundle.holdout_use.use_digest,
        bundle.objective_digest,
        bundle.dataset_digest,
        bundle.estimand_digest,
        bundle.estimate_receipt_digest,
        bundle.support_audit_digest,
        bundle.confidence_receipt_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_digest_vec(&mut bytes, &bundle.retention_receipt_digests)?;
    bytes.extend_from_slice(bundle.unlearning_receipt_digest.as_array());
    push_id_vec(&mut bytes, &bundle.snapshot_ids)?;
    push_id_vec(&mut bytes, &bundle.future_window_ids)?;
    bytes.extend_from_slice(&bundle.family_alpha_ppm.to_be_bytes());
    bytes.extend_from_slice(&bundle.simultaneous_comparisons.to_be_bytes());
    for metric in &bundle.metrics {
        push_id(&mut bytes, &metric.metric_id);
        bytes.push(metric.direction.tag());
        for interval in [metric.candidate, metric.baseline] {
            bytes.extend_from_slice(&interval.lower.raw().to_be_bytes());
            bytes.extend_from_slice(&interval.upper.raw().to_be_bytes());
        }
        match metric.safety_floor {
            Some(floor) => {
                bytes.push(1);
                bytes.extend_from_slice(&floor.raw().to_be_bytes());
            }
            None => bytes.push(0),
        }
        bytes.extend_from_slice(metric.support_digest.as_array());
    }
    bytes.push(disposition.tag());
    push_id_vec(&mut bytes, failed_metrics)?;
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_frozen_evaluation_binding(
    bundle: &IndependentEvaluationBundleV1,
    contract_digest: Digest32,
) -> Result<(), EvaluationClosureError> {
    let plan = &bundle.frozen_plan;
    let holdout = &bundle.holdout_use;
    validate_frozen_plan_receipt_integrity(plan)?;
    validate_holdout_use_receipt_integrity(holdout)?;
    if plan.authority.grants_any() {
        return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "authority",
        ));
    }
    if holdout.authority.grants_any() {
        return Err(EvaluationClosureError::HoldoutUseBindingMismatch(
            "authority",
        ));
    }
    for (label, digest) in [
        ("frozen plan", plan.plan_digest),
        ("metric contract", plan.metric_contract_digest),
        ("holdout registry", holdout.registry_digest),
        ("holdout use", holdout.use_digest),
    ] {
        require_digest(digest, label)?;
    }
    if plan.claim_scope != bundle.claim_scope {
        return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "claim scope",
        ));
    }
    if plan.candidate_id != bundle.candidate_id {
        return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "candidate",
        ));
    }
    if plan.baseline_id != bundle.baseline_id {
        return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "baseline",
        ));
    }
    if plan.objective_digest != bundle.objective_digest {
        return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "objective",
        ));
    }
    if plan.dataset_digest != bundle.dataset_digest {
        return Err(EvaluationClosureError::FrozenPlanBindingMismatch("dataset"));
    }
    if plan.estimand_digest != bundle.estimand_digest {
        return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "estimand",
        ));
    }
    if plan.family_alpha_ppm != bundle.family_alpha_ppm
        || plan.simultaneous_comparisons != bundle.simultaneous_comparisons
    {
        return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "multiplicity",
        ));
    }
    if contract_digest != plan.metric_contract_digest {
        return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "metric contract",
        ));
    }
    if holdout.plan_id != plan.plan_id {
        return Err(EvaluationClosureError::HoldoutUseBindingMismatch("plan id"));
    }
    if holdout.plan_digest != plan.plan_digest {
        return Err(EvaluationClosureError::HoldoutUseBindingMismatch(
            "plan digest",
        ));
    }
    if holdout.holdout_digest != plan.final_holdout_digest {
        return Err(EvaluationClosureError::HoldoutUseBindingMismatch(
            "holdout digest",
        ));
    }
    if holdout.final_holdout_window_id != plan.final_holdout_window_id {
        return Err(EvaluationClosureError::HoldoutUseBindingMismatch(
            "holdout window",
        ));
    }
    if holdout.claim_scope != plan.claim_scope
        || holdout.candidate_id != plan.candidate_id
        || holdout.baseline_id != plan.baseline_id
        || holdout.objective_digest != plan.objective_digest
        || holdout.dataset_digest != plan.dataset_digest
        || holdout.estimand_digest != plan.estimand_digest
        || holdout.metric_contract_digest != plan.metric_contract_digest
    {
        return Err(EvaluationClosureError::HoldoutUseBindingMismatch(
            "analysis semantics",
        ));
    }
    let expected_use = HoldoutBindingV1::from_plan(plan).use_digest(holdout.registry_digest);
    if holdout.use_digest != expected_use {
        return Err(EvaluationClosureError::HoldoutUseBindingMismatch(
            "use digest",
        ));
    }
    Ok(())
}

fn metric_contracts(metrics: &[MetricGateV1]) -> Vec<MetricContractV1> {
    metrics
        .iter()
        .map(|metric| MetricContractV1 {
            metric_id: metric.metric_id.clone(),
            direction: metric.direction,
            safety_floor: metric.safety_floor,
        })
        .collect()
}

fn digest_metric_contracts(
    contracts: &mut [MetricContractV1],
) -> Result<Digest32, EvaluationClosureError> {
    if contracts.len() > MAX_METRICS {
        return Err(EvaluationClosureError::MetricLimit);
    }
    contracts.sort_by_key(|contract| contract.metric_id.clone());
    if let Some(adjacent) = contracts
        .windows(2)
        .find(|adjacent| adjacent[0].metric_id == adjacent[1].metric_id)
    {
        return Err(EvaluationClosureError::DuplicateMetric(
            adjacent[0].metric_id.to_string(),
        ));
    }
    let mut bytes = b"hepta.intelligence-eval.metric-contract.v1".to_vec();
    bytes.extend_from_slice(
        &u32::try_from(contracts.len())
            .map_err(|_| EvaluationClosureError::Arithmetic)?
            .to_be_bytes(),
    );
    for contract in contracts {
        push_id(&mut bytes, &contract.metric_id);
        bytes.push(contract.direction.tag());
        match contract.safety_floor {
            Some(floor) => {
                bytes.push(1);
                bytes.extend_from_slice(&floor.raw().to_be_bytes());
            }
            None => bytes.push(0),
        }
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn normalize_unique_ids(values: &mut [StableId]) -> Result<(), EvaluationClosureError> {
    if values.len() > MAX_LINEAGE_IDS {
        return Err(EvaluationClosureError::FoldLineageLimit);
    }
    values.sort();
    if let Some(adjacent) = values
        .windows(2)
        .find(|adjacent| adjacent[0] == adjacent[1])
    {
        return Err(EvaluationClosureError::DuplicateLineage(
            adjacent[0].to_string(),
        ));
    }
    Ok(())
}

fn reject_duplicate_digests(values: &[Digest32]) -> Result<(), EvaluationClosureError> {
    if values.windows(2).any(|adjacent| adjacent[0] == adjacent[1]) {
        return Err(EvaluationClosureError::DuplicateDigest);
    }
    Ok(())
}

fn insert_unique_holdouts(
    seen: &mut BTreeSet<StableId>,
    values: &[StableId],
) -> Result<(), EvaluationClosureError> {
    for value in values {
        if !seen.insert(value.clone()) {
            return Err(EvaluationClosureError::HoldoutAppearsInMultipleFolds(
                value.to_string(),
            ));
        }
    }
    Ok(())
}

fn sorted_sets_overlap(left: &[StableId], right: &[StableId]) -> bool {
    let mut left_index = 0_usize;
    let mut right_index = 0_usize;
    while left_index < left.len() && right_index < right.len() {
        match left[left_index].cmp(&right[right_index]) {
            std::cmp::Ordering::Less => left_index += 1,
            std::cmp::Ordering::Equal => return true,
            std::cmp::Ordering::Greater => right_index += 1,
        }
    }
    false
}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), EvaluationClosureError> {
    if digest.is_zero() {
        return Err(EvaluationClosureError::EmptyDigest(label));
    }
    Ok(())
}

fn push_principal(bytes: &mut Vec<u8>, principal: &AuthenticatedPrincipalV1) {
    push_id(bytes, &principal.principal_id);
    bytes.extend_from_slice(principal.credential_chain_digest.as_array());
    bytes.extend_from_slice(principal.signing_key_digest.as_array());
    bytes.extend_from_slice(principal.scope_digest.as_array());
    bytes.extend_from_slice(&principal.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&principal.authenticated_at.to_be_bytes());
    bytes.extend_from_slice(&principal.expires_at.to_be_bytes());
}

fn push_digest_vec(bytes: &mut Vec<u8>, values: &[Digest32]) -> Result<(), EvaluationClosureError> {
    bytes.extend_from_slice(
        &u32::try_from(values.len())
            .map_err(|_| EvaluationClosureError::Arithmetic)?
            .to_be_bytes(),
    );
    for value in values {
        bytes.extend_from_slice(value.as_array());
    }
    Ok(())
}

fn push_id_vec(bytes: &mut Vec<u8>, values: &[StableId]) -> Result<(), EvaluationClosureError> {
    bytes.extend_from_slice(
        &u32::try_from(values.len())
            .map_err(|_| EvaluationClosureError::Arithmetic)?
            .to_be_bytes(),
    );
    for value in values {
        push_id(bytes, value);
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "closure_tests.rs"]
mod tests;
