//! Independent evaluation composition above the estimator primitives.
//!
//! Estimators remain pure evidence producers. This module verifies authenticated
//! role separation, frozen K-fold lineage, final-holdout use, conservative
//! interval gates, future-window coverage, retention and unlearning before it
//! emits an eligibility decision. Eligibility is still not selection, promotion
//! or release authority.

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
pub struct IndependentEvaluationBundleV1 {
    pub evaluation_id: StableId,
    pub candidate_id: StableId,
    pub baseline_id: StableId,
    pub claim_scope: EvaluationClaimScopeV1,
    pub generator: AuthenticatedPrincipalV1,
    pub evaluator: AuthenticatedPrincipalV1,
    pub plan_digest: Digest32,
    pub objective_digest: Digest32,
    pub estimate_receipt_digest: Digest32,
    pub support_audit_digest: Digest32,
    pub confidence_receipt_digest: Digest32,
    pub retention_receipt_digests: Vec<Digest32>,
    pub unlearning_receipt_digest: Digest32,
    pub snapshot_ids: Vec<StableId>,
    pub future_window_ids: Vec<StableId>,
    pub final_holdout_digest: Digest32,
    pub family_alpha_ppm: u32,
    pub simultaneous_comparisons: u32,
    pub analysis_plan_frozen: bool,
    pub final_holdout_reused: bool,
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

pub fn decide_independently(
    mut bundle: IndependentEvaluationBundleV1,
    now: u64,
) -> Result<IndependentEvaluationDecisionV1, EvaluationClosureError> {
    verify_independent_roles(&bundle.generator, &bundle.evaluator, now)?;
    if !bundle.analysis_plan_frozen {
        return Err(EvaluationClosureError::PlanNotFrozen);
    }
    if bundle.final_holdout_reused {
        return Err(EvaluationClosureError::FinalHoldoutReused);
    }
    for (label, digest) in [
        ("evaluation plan", bundle.plan_digest),
        ("objective", bundle.objective_digest),
        ("estimate receipt", bundle.estimate_receipt_digest),
        ("support audit", bundle.support_audit_digest),
        ("confidence receipt", bundle.confidence_receipt_digest),
        ("final holdout", bundle.final_holdout_digest),
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
        let superiority = match metric.direction {
            EvaluationDirectionV1::Maximize => metric.candidate.lower > metric.baseline.upper,
            EvaluationDirectionV1::Minimize => metric.candidate.upper < metric.baseline.lower,
        };
        let safety = metric
            .safety_floor
            .is_none_or(|floor| match metric.direction {
                EvaluationDirectionV1::Maximize => metric.candidate.lower >= floor,
                EvaluationDirectionV1::Minimize => metric.candidate.upper <= floor,
            });
        if !superiority || !safety {
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
    pub folds: Vec<CrossFoldPartitionV1>,
    pub final_holdout_window_id: StableId,
    pub final_holdout_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CrossFoldPlanReceiptV1 {
    pub plan_id: StableId,
    pub fold_count: u32,
    pub plan_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn freeze_cross_fold_plan(
    mut plan: CrossFoldPlanV1,
) -> Result<CrossFoldPlanReceiptV1, EvaluationClosureError> {
    if !(2..=MAX_FOLDS).contains(&plan.folds.len()) {
        return Err(EvaluationClosureError::FoldLimit);
    }
    require_digest(plan.final_holdout_digest, "final holdout")?;
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

    let mut bytes = b"hepta.intelligence-eval.cross-fold-plan.v1".to_vec();
    push_id(&mut bytes, &plan.plan_id);
    push_id(&mut bytes, &plan.final_holdout_window_id);
    bytes.extend_from_slice(plan.final_holdout_digest.as_array());
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
    Ok(CrossFoldPlanReceiptV1 {
        plan_id: plan.plan_id,
        fold_count: u32::try_from(plan.folds.len())
            .map_err(|_| EvaluationClosureError::Arithmetic)?,
        plan_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HoldoutUseDispositionV1 {
    Recorded,
    IdempotentReplay,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HoldoutUseReceiptV1 {
    pub disposition: HoldoutUseDispositionV1,
    pub holdout_digest: Digest32,
    pub plan_id: StableId,
    pub registry_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Default)]
pub struct FinalHoldoutRegistry {
    uses: BTreeMap<Digest32, StableId>,
}

impl FinalHoldoutRegistry {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn consume(
        &mut self,
        plan_id: StableId,
        holdout_digest: Digest32,
    ) -> Result<HoldoutUseReceiptV1, EvaluationClosureError> {
        require_digest(holdout_digest, "final holdout")?;
        let disposition = match self.uses.get(&holdout_digest) {
            Some(existing) if existing == &plan_id => HoldoutUseDispositionV1::IdempotentReplay,
            Some(_) => return Err(EvaluationClosureError::FinalHoldoutReused),
            None => {
                self.uses.insert(holdout_digest, plan_id.clone());
                HoldoutUseDispositionV1::Recorded
            }
        };
        Ok(HoldoutUseReceiptV1 {
            disposition,
            holdout_digest,
            plan_id,
            registry_digest: self.digest(),
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.intelligence-eval.final-holdout-registry.v1".to_vec();
        for (holdout, plan_id) in &self.uses {
            bytes.extend_from_slice(holdout.as_array());
            push_id(&mut bytes, plan_id);
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EvaluationClosureError {
    Role(CausalV2Error),
    EmptyDigest(&'static str),
    PlanNotFrozen,
    FinalHoldoutReused,
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
            | Self::PlanNotFrozen
            | Self::FinalHoldoutReused
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

fn digest_evaluation_bundle(
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
        bundle.plan_digest,
        bundle.objective_digest,
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
    bytes.extend_from_slice(bundle.final_holdout_digest.as_array());
    bytes.extend_from_slice(&bundle.family_alpha_ppm.to_be_bytes());
    bytes.extend_from_slice(&bundle.simultaneous_comparisons.to_be_bytes());
    bytes.push(u8::from(bundle.analysis_plan_frozen));
    bytes.push(u8::from(bundle.final_holdout_reused));
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

fn normalize_unique_ids(values: &mut Vec<StableId>) -> Result<(), EvaluationClosureError> {
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
