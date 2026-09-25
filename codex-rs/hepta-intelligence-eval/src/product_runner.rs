//! Product composition for independent candidate evaluation.
//!
//! This adapter is the canonical source path that binds preregistration,
//! fenced final-holdout consumption, held-out data release, estimator receipts,
//! signed qualification and durable evidence publication. Callers never submit
//! final metric intervals: they are derived from sealed estimator receipts.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ClusterAssignment;
use crate::ClusterOpeEstimate;
use crate::CrossFoldPlanReceiptV1;
use crate::CrossFoldPlanV1;
use crate::EvaluationClaimScopeV1;
use crate::EvaluationClosureError;
use crate::EvaluationDirectionV1;
use crate::EvaluationIntervalV1;
use crate::FencedFinalHoldoutOwnerV1;
use crate::FencedHoldoutError;
use crate::FinalHoldoutCasStoreV1;
use crate::FinalHoldoutJournalReceiptV1;
use crate::HeldOutTarget;
use crate::IndependentEvaluationBundleV1;
use crate::LongitudinalTimeEvidenceV1;
use crate::MetricContractV1;
use crate::MetricGateV1;
use crate::MetricRoleContractV2;
use crate::MetricRoleV2;
use crate::OpeInterval;
use crate::OpeRow;
use crate::OutcomeTrainingSample;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationError;
use crate::SignedEvaluationEvidenceV1;
use crate::TemporalEvaluationError;
use crate::TemporalEvaluationPlan;
use crate::TemporalEvaluationReceipt;
use crate::decide_with_signed_evidence_v2;
use crate::decide_with_signed_longitudinal_evidence_v3;
use crate::evaluate_temporal_holdout;
use crate::freeze_cross_fold_plan_v2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductMetricSourceV1 {
    Ips,
    Snips,
    DoublyRobust,
}

impl ProductMetricSourceV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Ips => 0,
            Self::Snips => 1,
            Self::DoublyRobust => 2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductMetricSourceContractV1 {
    pub metric_id: StableId,
    pub source: ProductMetricSourceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductFrozenEvaluationPlanV1 {
    pub frozen_plan: CrossFoldPlanReceiptV1,
    pub metric_roles: Vec<MetricRoleContractV2>,
    pub metric_contracts: Vec<MetricContractV1>,
    pub metric_sources: Vec<ProductMetricSourceContractV1>,
    pub base_estimand_digest: Digest32,
    pub candidate_temporal_plan_digest: Digest32,
    pub baseline_temporal_plan_digest: Digest32,
    receipt_seal: Digest32,
}

impl ProductFrozenEvaluationPlanV1 {
    fn validate_integrity(&self) -> Result<(), ProductEvaluationError> {
        if self.receipt_seal != product_plan_seal(self)? {
            return Err(ProductEvaluationError::Integrity("product plan"));
        }
        let expected = bound_estimand_digest(
            self.base_estimand_digest,
            self.candidate_temporal_plan_digest,
            self.baseline_temporal_plan_digest,
            &self.metric_sources,
        )?;
        if self.frozen_plan.estimand_digest != expected {
            return Err(ProductEvaluationError::Binding("bound estimand"));
        }
        Ok(())
    }
}

pub fn freeze_product_evaluation_plan_v1(
    mut plan: CrossFoldPlanV1,
    mut metric_roles: Vec<MetricRoleContractV2>,
    mut metric_sources: Vec<ProductMetricSourceContractV1>,
    candidate_temporal: &TemporalEvaluationPlan,
    baseline_temporal: &TemporalEvaluationPlan,
) -> Result<ProductFrozenEvaluationPlanV1, ProductEvaluationError> {
    if candidate_temporal.plan_digest.is_zero()
        || baseline_temporal.plan_digest.is_zero()
        || candidate_temporal.plan_digest != candidate_temporal.canonical_digest()?
        || baseline_temporal.plan_digest != baseline_temporal.canonical_digest()?
        || candidate_temporal.objective_digest != plan.objective_digest
        || baseline_temporal.objective_digest != plan.objective_digest
        || candidate_temporal.confidence.family_alpha_ppm != plan.family_alpha_ppm
        || baseline_temporal.confidence.family_alpha_ppm != plan.family_alpha_ppm
        || candidate_temporal.confidence.simultaneous_comparisons != plan.simultaneous_comparisons
        || baseline_temporal.confidence.simultaneous_comparisons != plan.simultaneous_comparisons
    {
        return Err(ProductEvaluationError::Binding("temporal plan"));
    }
    if plan.metric_contracts.is_empty() || plan.estimand_digest.is_zero() {
        return Err(ProductEvaluationError::Binding("metric or estimand"));
    }
    let mut metric_contracts = plan.metric_contracts.clone();
    metric_contracts.sort_by_key(|row| row.metric_id.clone());
    metric_sources.sort_by_key(|row| row.metric_id.clone());
    metric_roles.sort_by_key(|row| row.metric_id.clone());
    if metric_sources.len() != metric_contracts.len()
        || metric_roles.len() != metric_contracts.len()
        || metric_contracts
            .iter()
            .zip(metric_sources.iter())
            .any(|(contract, source)| contract.metric_id != source.metric_id)
        || metric_contracts
            .iter()
            .zip(metric_roles.iter())
            .any(|(contract, role)| contract.metric_id != role.metric_id)
    {
        return Err(ProductEvaluationError::Binding("metric source coverage"));
    }

    let base_estimand_digest = plan.estimand_digest;
    plan.estimand_digest = bound_estimand_digest(
        base_estimand_digest,
        candidate_temporal.plan_digest,
        baseline_temporal.plan_digest,
        &metric_sources,
    )?;
    let frozen_plan = freeze_cross_fold_plan_v2(plan, metric_roles.clone())?;
    let mut receipt = ProductFrozenEvaluationPlanV1 {
        frozen_plan,
        metric_roles,
        metric_contracts,
        metric_sources,
        base_estimand_digest,
        candidate_temporal_plan_digest: candidate_temporal.plan_digest,
        baseline_temporal_plan_digest: baseline_temporal.plan_digest,
        receipt_seal: Digest32::ZERO,
    };
    receipt.receipt_seal = product_plan_seal(&receipt)?;
    Ok(receipt)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductProviderErrorV1 {
    Rejected,
    Unavailable,
    Indeterminate,
}

impl fmt::Display for ProductProviderErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProductProviderErrorV1 {}

#[derive(Clone, Debug)]
pub struct TemporalComparisonInputsV1 {
    pub training: Vec<OutcomeTrainingSample>,
    pub targets: Vec<HeldOutTarget>,
    pub candidate_observations: Vec<OpeRow>,
    pub baseline_observations: Vec<OpeRow>,
    pub assignments: Vec<ClusterAssignment>,
    pub snapshot_ids: Vec<StableId>,
    pub future_window_ids: Vec<StableId>,
}

pub trait FinalHoldoutProviderV1 {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1>;

    /// This method is invoked only after the authoritative fenced owner has
    /// durably consumed the frozen final-holdout plan.
    fn release_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductEvidenceSinkErrorV1 {
    Rejected,
    Unavailable,
    Indeterminate,
}

impl fmt::Display for ProductEvidenceSinkErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProductEvidenceSinkErrorV1 {}

pub trait ProductQualificationEvidenceSinkV1 {
    /// Persist the terminal qualification evidence through the declared
    /// evidence owner. Return a nonzero durable publication digest only after
    /// the publication is committed.
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductTemporalEvaluationReceiptV1 {
    pub holdout: FinalHoldoutJournalReceiptV1,
    pub product_plan: ProductFrozenEvaluationPlanV1,
    pub candidate: TemporalEvaluationReceipt,
    pub baseline: TemporalEvaluationReceipt,
    pub metrics: Vec<MetricGateV1>,
    pub estimate_receipt_digest: Digest32,
    pub support_audit_digest: Digest32,
    pub confidence_receipt_digest: Digest32,
    pub snapshot_ids: Vec<StableId>,
    pub future_window_ids: Vec<StableId>,
    pub execution_digest: Digest32,
    pub authority: AuthorityPosture,
    receipt_seal: Digest32,
}

impl ProductTemporalEvaluationReceiptV1 {
    fn validate_integrity(&self) -> Result<(), ProductEvaluationError> {
        self.product_plan.validate_integrity()?;
        self.candidate.validate_integrity()?;
        self.baseline.validate_integrity()?;
        let expected_metrics = derive_metric_gates(
            &self.product_plan,
            &self.candidate.estimate,
            &self.baseline.estimate,
        )?;
        if expected_metrics != self.metrics {
            return Err(ProductEvaluationError::Integrity("metric evidence"));
        }
        let (estimate, support, confidence) =
            comparison_digests(&self.candidate, &self.baseline, &self.metrics);
        if self.estimate_receipt_digest != estimate
            || self.support_audit_digest != support
            || self.confidence_receipt_digest != confidence
        {
            return Err(ProductEvaluationError::Integrity("comparison evidence"));
        }
        let expected_execution = execution_digest(
            &self.holdout,
            &self.product_plan,
            &self.candidate,
            &self.baseline,
            &self.metrics,
            &self.snapshot_ids,
            &self.future_window_ids,
            estimate,
            support,
            confidence,
        );
        if self.execution_digest != expected_execution
            || self.receipt_seal != product_evaluation_seal(self)?
        {
            return Err(ProductEvaluationError::Integrity("product evaluation"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct ProductQualificationContextV1 {
    pub generator: AuthenticatedPrincipalV1,
    pub evaluator: AuthenticatedPrincipalV1,
    pub retention_receipt_digests: Vec<Digest32>,
    pub unlearning_receipt_digest: Digest32,
}

pub enum ProductTimingEvidenceV1<'a> {
    Qualification,
    SystemLongitudinal {
        timing: &'a LongitudinalTimeEvidenceV1,
        minimum_window_micros: u64,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductQualificationReceiptV1 {
    pub temporal_execution_digest: Digest32,
    pub candidate_id: StableId,
    pub evaluator: AuthenticatedPrincipalV1,
    pub generator: AuthenticatedPrincipalV1,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub snapshot_ids: Vec<StableId>,
    pub claim_scope: EvaluationClaimScopeV1,
    pub decision: SignedEvaluationDecisionV1,
    pub publication_digest: Digest32,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
    receipt_seal: Digest32,
}

impl ProductQualificationReceiptV1 {
    /// Re-authenticate the exact signed bundle against this already persisted
    /// qualification. This is read-only consumption, never a way to mint a
    /// qualification without the fenced runner and durable evidence sink.
    pub fn verify_signed_bundle_current(
        &self,
        bundle: &IndependentEvaluationBundleV1,
        roles: &[MetricRoleContractV2],
        evidence: &SignedEvaluationEvidenceV1,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<(), ProductEvaluationError> {
        self.validate_integrity()?;
        if self.decision.trust_digest != verifier.trust_digest()
            || self.candidate_id != bundle.candidate_id
            || self.objective_digest != bundle.objective_digest
            || self.dataset_digest != bundle.dataset_digest
            || self.generator != bundle.generator
            || self.evaluator != bundle.evaluator
            || self.snapshot_ids != bundle.snapshot_ids
            || self.claim_scope != bundle.claim_scope
        {
            return Err(ProductEvaluationError::Binding(
                "current qualification consumption",
            ));
        }
        let payload = crate::evaluation_signing_payload_v2(bundle, roles)?;
        let authenticated =
            crate::signed_evaluation::authenticate(bundle, evidence, verifier, &payload, now)?;
        if authenticated != self.decision.authentication_digest {
            return Err(ProductEvaluationError::Integrity(
                "qualification signed bundle",
            ));
        }
        Ok(())
    }

    pub fn validate_integrity(&self) -> Result<(), ProductEvaluationError> {
        if self.temporal_execution_digest.is_zero()
            || self.objective_digest.is_zero()
            || self.dataset_digest.is_zero()
            || self.publication_digest.is_zero()
            || self.decision.decision.evidence_digest.is_zero()
            || self.decision.trust_digest.is_zero()
            || self.decision.authentication_digest.is_zero()
            || self.snapshot_ids.is_empty()
            || self.authority.grants_any()
            || self.decision.decision.authority.grants_any()
            || self.decision.decision.candidate_id != self.candidate_id
        {
            return Err(ProductEvaluationError::Integrity("qualification receipt"));
        }
        let expected = product_qualification_evidence_digest(self);
        if self.evidence_digest != expected || self.receipt_seal != product_qualification_seal(self)
        {
            return Err(ProductEvaluationError::Integrity(
                "qualification receipt seal",
            ));
        }
        Ok(())
    }
}

pub struct ProductEvaluationRunnerV1<S> {
    holdout: FencedFinalHoldoutOwnerV1<S>,
}

impl<S: FinalHoldoutCasStoreV1> ProductEvaluationRunnerV1<S> {
    #[must_use]
    pub fn new(holdout: FencedFinalHoldoutOwnerV1<S>) -> Self {
        Self { holdout }
    }

    #[must_use]
    pub fn holdout_state_digest(&self) -> Digest32 {
        self.holdout.state_digest()
    }

    #[must_use]
    pub fn holdout_anchor(&self) -> crate::FinalHoldoutCasAnchorV1 {
        self.holdout.anchor()
    }

    pub fn evaluate_temporal_comparison<P: FinalHoldoutProviderV1>(
        &mut self,
        product_plan: &ProductFrozenEvaluationPlanV1,
        candidate_plan: &TemporalEvaluationPlan,
        baseline_plan: &TemporalEvaluationPlan,
        provider: &mut P,
    ) -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationError> {
        product_plan.validate_integrity()?;
        if candidate_plan.plan_digest != product_plan.candidate_temporal_plan_digest
            || baseline_plan.plan_digest != product_plan.baseline_temporal_plan_digest
            || candidate_plan.objective_digest != product_plan.frozen_plan.objective_digest
            || baseline_plan.objective_digest != product_plan.frozen_plan.objective_digest
        {
            return Err(ProductEvaluationError::Binding("temporal execution plan"));
        }
        let manifest = provider.manifest_digest()?;
        if manifest.is_zero() || manifest != product_plan.frozen_plan.final_holdout_digest {
            return Err(ProductEvaluationError::Binding("final holdout manifest"));
        }

        let holdout = self.holdout.consume(&product_plan.frozen_plan)?;
        let mut inputs = provider.release_after_consumption(&holdout)?;
        validate_released_inputs(&product_plan.frozen_plan, &inputs)?;
        validate_comparable_observations(
            &inputs.candidate_observations,
            &inputs.baseline_observations,
        )?;
        normalize_unique_ids(&mut inputs.snapshot_ids)?;
        normalize_unique_ids(&mut inputs.future_window_ids)?;

        let candidate = evaluate_temporal_holdout(
            candidate_plan,
            &inputs.training,
            &inputs.targets,
            &inputs.candidate_observations,
            &inputs.assignments,
        )?;
        let baseline = evaluate_temporal_holdout(
            baseline_plan,
            &inputs.training,
            &inputs.targets,
            &inputs.baseline_observations,
            &inputs.assignments,
        )?;
        candidate.validate_integrity()?;
        baseline.validate_integrity()?;

        let metrics = derive_metric_gates(product_plan, &candidate.estimate, &baseline.estimate)?;
        let (estimate_receipt_digest, support_audit_digest, confidence_receipt_digest) =
            comparison_digests(&candidate, &baseline, &metrics);
        let execution_digest = execution_digest(
            &holdout,
            product_plan,
            &candidate,
            &baseline,
            &metrics,
            &inputs.snapshot_ids,
            &inputs.future_window_ids,
            estimate_receipt_digest,
            support_audit_digest,
            confidence_receipt_digest,
        );
        let mut receipt = ProductTemporalEvaluationReceiptV1 {
            holdout,
            product_plan: product_plan.clone(),
            candidate,
            baseline,
            metrics,
            estimate_receipt_digest,
            support_audit_digest,
            confidence_receipt_digest,
            snapshot_ids: inputs.snapshot_ids,
            future_window_ids: inputs.future_window_ids,
            execution_digest,
            authority: AuthorityPosture::DENY_ALL,
            receipt_seal: Digest32::ZERO,
        };
        receipt.receipt_seal = product_evaluation_seal(&receipt)?;
        Ok(receipt)
    }

    pub fn qualification_bundle(
        &self,
        temporal: &ProductTemporalEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
    ) -> Result<IndependentEvaluationBundleV1, ProductEvaluationError> {
        temporal.validate_integrity()?;
        let frozen = &temporal.product_plan.frozen_plan;
        Ok(IndependentEvaluationBundleV1 {
            evaluation_id: frozen.plan_id.clone(),
            candidate_id: frozen.candidate_id.clone(),
            baseline_id: frozen.baseline_id.clone(),
            claim_scope: frozen.claim_scope,
            generator: context.generator.clone(),
            evaluator: context.evaluator.clone(),
            frozen_plan: frozen.clone(),
            holdout_use: temporal.holdout.use_receipt.clone(),
            objective_digest: frozen.objective_digest,
            dataset_digest: frozen.dataset_digest,
            estimand_digest: frozen.estimand_digest,
            estimate_receipt_digest: temporal.estimate_receipt_digest,
            support_audit_digest: temporal.support_audit_digest,
            confidence_receipt_digest: temporal.confidence_receipt_digest,
            retention_receipt_digests: context.retention_receipt_digests.clone(),
            unlearning_receipt_digest: context.unlearning_receipt_digest,
            snapshot_ids: temporal.snapshot_ids.clone(),
            future_window_ids: temporal.future_window_ids.clone(),
            family_alpha_ppm: frozen.family_alpha_ppm,
            simultaneous_comparisons: frozen.simultaneous_comparisons,
            metrics: temporal.metrics.clone(),
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub fn qualify_and_persist(
        &self,
        temporal: &ProductTemporalEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<ProductQualificationReceiptV1, ProductEvaluationError> {
        let bundle = self.qualification_bundle(temporal, context)?;
        let candidate_id = bundle.candidate_id.clone();
        let evaluator = bundle.evaluator.clone();
        let generator = bundle.generator.clone();
        let objective_digest = bundle.objective_digest;
        let dataset_digest = bundle.dataset_digest;
        let snapshot_ids = bundle.snapshot_ids.clone();
        let claim_scope = bundle.claim_scope;
        let roles = temporal.product_plan.metric_roles.clone();
        let decision =
            publication::verify_qualification(bundle, roles, evidence, timing, verifier, now)?;
        let publication_digest = sink.persist(temporal.execution_digest, &decision)?;
        if publication_digest.is_zero() {
            return Err(ProductEvaluationError::Integrity("publication digest"));
        }
        let mut receipt = ProductQualificationReceiptV1 {
            temporal_execution_digest: temporal.execution_digest,
            candidate_id,
            evaluator,
            generator,
            objective_digest,
            dataset_digest,
            snapshot_ids,
            claim_scope,
            decision,
            publication_digest,
            evidence_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
            receipt_seal: Digest32::ZERO,
        };
        receipt.evidence_digest = product_qualification_evidence_digest(&receipt);
        receipt.receipt_seal = product_qualification_seal(&receipt);
        receipt.validate_integrity()?;
        Ok(receipt)
    }
}

fn product_qualification_evidence_digest(receipt: &ProductQualificationReceiptV1) -> Digest32 {
    // V4 binds the complete terminal decision object, not only the decision's
    // opaque evidence digest. Older V3 receipts fail closed and must be
    // requalified because their mutable disposition/identity fields were not
    // covered by the product receipt seal.
    let mut bytes = b"hepta.intelligence-eval.product-qualification.v4".to_vec();
    for digest in [
        receipt.temporal_execution_digest,
        receipt.objective_digest,
        receipt.dataset_digest,
        receipt.publication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &receipt.candidate_id);
    push_principal(&mut bytes, &receipt.evaluator);
    push_principal(&mut bytes, &receipt.generator);
    bytes.push(match receipt.claim_scope {
        EvaluationClaimScopeV1::Qualification => 0,
        EvaluationClaimScopeV1::SystemLongitudinal => 1,
    });
    push_ids(&mut bytes, &receipt.snapshot_ids);
    push_signed_evaluation_decision(&mut bytes, &receipt.decision);
    bytes.push(u8::from(receipt.authority.grants_any()));
    Digest32::of_bytes(&bytes)
}

fn push_signed_evaluation_decision(bytes: &mut Vec<u8>, decision: &SignedEvaluationDecisionV1) {
    push_id(bytes, &decision.decision.evaluation_id);
    push_id(bytes, &decision.decision.candidate_id);
    push_id(bytes, &decision.decision.baseline_id);
    bytes.push(match decision.decision.disposition {
        crate::IndependentEvaluationDispositionV1::EligibleForIndependentSelection => 0,
        crate::IndependentEvaluationDispositionV1::Ineligible => 1,
        crate::IndependentEvaluationDispositionV1::InsufficientEvidence => 2,
    });
    push_ids(bytes, &decision.decision.failed_metrics);
    for digest in [
        decision.decision.evidence_digest,
        decision.trust_digest,
        decision.authentication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.push(u8::from(decision.decision.authority.grants_any()));
}

fn product_qualification_seal(receipt: &ProductQualificationReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.product-qualification-receipt.v2".to_vec();
    bytes.extend_from_slice(product_qualification_evidence_digest(receipt).as_array());
    bytes.extend_from_slice(receipt.evidence_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_principal(bytes: &mut Vec<u8>, principal: &AuthenticatedPrincipalV1) {
    push_id(bytes, &principal.principal_id);
    bytes.extend_from_slice(principal.credential_chain_digest.as_array());
    bytes.extend_from_slice(principal.signing_key_digest.as_array());
    bytes.extend_from_slice(principal.scope_digest.as_array());
    for value in [
        principal.authority_epoch,
        principal.authenticated_at,
        principal.expires_at,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
}

fn validate_released_inputs(
    frozen: &CrossFoldPlanReceiptV1,
    inputs: &TemporalComparisonInputsV1,
) -> Result<(), ProductEvaluationError> {
    if inputs.targets.is_empty()
        || inputs
            .targets
            .iter()
            .any(|target| target.window_id != frozen.final_holdout_window_id)
        || inputs.targets.len() != inputs.candidate_observations.len()
        || inputs.targets.len() != inputs.baseline_observations.len()
        || inputs.targets.len() != inputs.assignments.len()
    {
        return Err(ProductEvaluationError::Binding("released holdout cohort"));
    }
    Ok(())
}

fn validate_comparable_observations(
    candidate: &[OpeRow],
    baseline: &[OpeRow],
) -> Result<(), ProductEvaluationError> {
    if candidate.len() != baseline.len() {
        return Err(ProductEvaluationError::Binding("comparison cohort"));
    }
    let mut left: Vec<_> = candidate.iter().collect();
    let mut right: Vec<_> = baseline.iter().collect();
    left.sort_by(|a, b| a.decision_id.cmp(&b.decision_id));
    right.sort_by(|a, b| a.decision_id.cmp(&b.decision_id));
    for (left, right) in left.into_iter().zip(right) {
        if left.decision_id != right.decision_id
            || left.chosen_action != right.chosen_action
            || left.complete_candidates != right.complete_candidates
            || left.finalized_outcome != right.finalized_outcome
            || left.outcome_observed_at != right.outcome_observed_at
            || left.outcome_evidence != right.outcome_evidence
            || left.actions.len() != right.actions.len()
        {
            return Err(ProductEvaluationError::Binding("comparison outcomes"));
        }
        let mut left_actions: Vec<_> = left.actions.iter().collect();
        let mut right_actions: Vec<_> = right.actions.iter().collect();
        left_actions.sort_by(|a, b| a.action_id.cmp(&b.action_id));
        right_actions.sort_by(|a, b| a.action_id.cmp(&b.action_id));
        if left_actions
            .into_iter()
            .zip(right_actions)
            .any(|(left, right)| {
                left.action_id != right.action_id
                    || left.behavior_probability != right.behavior_probability
            })
        {
            return Err(ProductEvaluationError::Binding(
                "comparison behavior policy",
            ));
        }
    }
    Ok(())
}

fn derive_metric_gates(
    plan: &ProductFrozenEvaluationPlanV1,
    candidate: &ClusterOpeEstimate,
    baseline: &ClusterOpeEstimate,
) -> Result<Vec<MetricGateV1>, ProductEvaluationError> {
    candidate
        .validate_integrity()
        .map_err(TemporalEvaluationError::Confidence)?;
    baseline
        .validate_integrity()
        .map_err(TemporalEvaluationError::Confidence)?;
    if plan.metric_contracts.len() != plan.metric_sources.len() {
        return Err(ProductEvaluationError::Integrity("metric source coverage"));
    }
    let mut metrics = Vec::with_capacity(plan.metric_contracts.len());
    for (contract, source) in plan.metric_contracts.iter().zip(plan.metric_sources.iter()) {
        if contract.metric_id != source.metric_id {
            return Err(ProductEvaluationError::Integrity("metric source identity"));
        }
        let candidate_interval = select_interval(candidate, source.source);
        let baseline_interval = select_interval(baseline, source.source);
        let mut support = b"hepta.intelligence-eval.product-metric-support.v1".to_vec();
        push_id(&mut support, &contract.metric_id);
        support.push(source.source.tag());
        for digest in [
            candidate.point.evidence_digest,
            candidate.evidence_digest,
            baseline.point.evidence_digest,
            baseline.evidence_digest,
        ] {
            support.extend_from_slice(digest.as_array());
        }
        metrics.push(MetricGateV1 {
            metric_id: contract.metric_id.clone(),
            direction: contract.direction,
            candidate: EvaluationIntervalV1 {
                lower: candidate_interval.lower,
                upper: candidate_interval.upper,
            },
            baseline: EvaluationIntervalV1 {
                lower: baseline_interval.lower,
                upper: baseline_interval.upper,
            },
            safety_floor: contract.safety_floor,
            support_digest: Digest32::of_bytes(&support),
        });
    }
    Ok(metrics)
}

fn select_interval(estimate: &ClusterOpeEstimate, source: ProductMetricSourceV1) -> OpeInterval {
    match source {
        ProductMetricSourceV1::Ips => estimate.ips,
        ProductMetricSourceV1::Snips => estimate.snips,
        ProductMetricSourceV1::DoublyRobust => estimate.doubly_robust,
    }
}

fn comparison_digests(
    candidate: &TemporalEvaluationReceipt,
    baseline: &TemporalEvaluationReceipt,
    metrics: &[MetricGateV1],
) -> (Digest32, Digest32, Digest32) {
    let mut estimate = b"hepta.intelligence-eval.product-estimate-pair.v1".to_vec();
    estimate.extend_from_slice(candidate.evidence_digest.as_array());
    estimate.extend_from_slice(baseline.evidence_digest.as_array());
    let mut support = b"hepta.intelligence-eval.product-support-pair.v1".to_vec();
    support.extend_from_slice(candidate.estimate.point.evidence_digest.as_array());
    support.extend_from_slice(baseline.estimate.point.evidence_digest.as_array());
    for metric in metrics {
        support.extend_from_slice(metric.support_digest.as_array());
    }
    let mut confidence = b"hepta.intelligence-eval.product-confidence-pair.v1".to_vec();
    confidence.extend_from_slice(candidate.estimate.evidence_digest.as_array());
    confidence.extend_from_slice(baseline.estimate.evidence_digest.as_array());
    (
        Digest32::of_bytes(&estimate),
        Digest32::of_bytes(&support),
        Digest32::of_bytes(&confidence),
    )
}

#[allow(clippy::too_many_arguments)]
fn execution_digest(
    holdout: &FinalHoldoutJournalReceiptV1,
    plan: &ProductFrozenEvaluationPlanV1,
    candidate: &TemporalEvaluationReceipt,
    baseline: &TemporalEvaluationReceipt,
    metrics: &[MetricGateV1],
    snapshot_ids: &[StableId],
    future_window_ids: &[StableId],
    estimate_digest: Digest32,
    support_digest: Digest32,
    confidence_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.product-execution.v1".to_vec();
    for digest in [
        holdout.record_digest,
        holdout.use_receipt.use_digest,
        plan.frozen_plan.plan_digest,
        candidate.evidence_digest,
        baseline.evidence_digest,
        estimate_digest,
        support_digest,
        confidence_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for metric in metrics {
        push_id(&mut bytes, &metric.metric_id);
        bytes.extend_from_slice(metric.support_digest.as_array());
    }
    push_ids(&mut bytes, snapshot_ids);
    push_ids(&mut bytes, future_window_ids);
    Digest32::of_bytes(&bytes)
}

fn product_evaluation_seal(
    receipt: &ProductTemporalEvaluationReceiptV1,
) -> Result<Digest32, ProductEvaluationError> {
    let mut bytes = b"hepta.intelligence-eval.product-evaluation-receipt.v1".to_vec();
    for digest in [
        receipt.holdout.record_digest,
        receipt.product_plan.frozen_plan.plan_digest,
        receipt.candidate.evidence_digest,
        receipt.baseline.evidence_digest,
        receipt.estimate_receipt_digest,
        receipt.support_audit_digest,
        receipt.confidence_receipt_digest,
        receipt.execution_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for metric in &receipt.metrics {
        push_metric(&mut bytes, metric);
    }
    push_ids(&mut bytes, &receipt.snapshot_ids);
    push_ids(&mut bytes, &receipt.future_window_ids);
    bytes.push(u8::from(receipt.authority.grants_any()));
    Ok(Digest32::of_bytes(&bytes))
}

fn product_plan_seal(
    plan: &ProductFrozenEvaluationPlanV1,
) -> Result<Digest32, ProductEvaluationError> {
    let mut bytes = b"hepta.intelligence-eval.product-frozen-plan.v1".to_vec();
    for digest in [
        plan.frozen_plan.plan_digest,
        plan.frozen_plan.metric_contract_digest,
        plan.base_estimand_digest,
        plan.candidate_temporal_plan_digest,
        plan.baseline_temporal_plan_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for contract in &plan.metric_contracts {
        push_id(&mut bytes, &contract.metric_id);
        bytes.push(match contract.direction {
            EvaluationDirectionV1::Maximize => 0,
            EvaluationDirectionV1::Minimize => 1,
        });
        match contract.safety_floor {
            Some(value) => {
                bytes.push(1);
                bytes.extend_from_slice(&value.raw().to_be_bytes());
            }
            None => bytes.push(0),
        }
    }
    for role in &plan.metric_roles {
        push_id(&mut bytes, &role.metric_id);
        match role.role {
            MetricRoleV2::PrimarySuperiority {
                minimum_improvement,
            } => {
                bytes.push(0);
                bytes.extend_from_slice(&minimum_improvement.raw().to_be_bytes());
            }
            MetricRoleV2::NonInferiority { maximum_regression } => {
                bytes.push(1);
                bytes.extend_from_slice(&maximum_regression.raw().to_be_bytes());
            }
            MetricRoleV2::AbsoluteConstraint => bytes.push(2),
        }
    }
    for source in &plan.metric_sources {
        push_id(&mut bytes, &source.metric_id);
        bytes.push(source.source.tag());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn bound_estimand_digest(
    base: Digest32,
    candidate_plan: Digest32,
    baseline_plan: Digest32,
    sources: &[ProductMetricSourceContractV1],
) -> Result<Digest32, ProductEvaluationError> {
    if base.is_zero() || candidate_plan.is_zero() || baseline_plan.is_zero() {
        return Err(ProductEvaluationError::Binding("estimand source"));
    }
    let mut bytes = b"hepta.intelligence-eval.product-estimand.v1".to_vec();
    for digest in [base, candidate_plan, baseline_plan] {
        bytes.extend_from_slice(digest.as_array());
    }
    for source in sources {
        push_id(&mut bytes, &source.metric_id);
        bytes.push(source.source.tag());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn normalize_unique_ids(values: &mut [StableId]) -> Result<(), ProductEvaluationError> {
    values.sort();
    if values.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(ProductEvaluationError::Binding(
            "duplicate evidence identity",
        ));
    }
    Ok(())
}

fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
    for value in values {
        push_id(bytes, value);
    }
}

fn push_metric(bytes: &mut Vec<u8>, metric: &MetricGateV1) {
    push_id(bytes, &metric.metric_id);
    bytes.push(match metric.direction {
        EvaluationDirectionV1::Maximize => 0,
        EvaluationDirectionV1::Minimize => 1,
    });
    for interval in [metric.candidate, metric.baseline] {
        bytes.extend_from_slice(&interval.lower.raw().to_be_bytes());
        bytes.extend_from_slice(&interval.upper.raw().to_be_bytes());
    }
    match metric.safety_floor {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.raw().to_be_bytes());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(metric.support_digest.as_array());
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u32).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

#[derive(Debug)]
pub enum ProductEvaluationError {
    Binding(&'static str),
    Integrity(&'static str),
    Frozen(EvaluationClosureError),
    Temporal(TemporalEvaluationError),
    Holdout(FencedHoldoutError),
    Provider(ProductProviderErrorV1),
    Signed(SignedEvaluationError),
    Sink(ProductEvidenceSinkErrorV1),
}

impl fmt::Display for ProductEvaluationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProductEvaluationError {}

impl From<EvaluationClosureError> for ProductEvaluationError {
    fn from(value: EvaluationClosureError) -> Self {
        Self::Frozen(value)
    }
}
impl From<TemporalEvaluationError> for ProductEvaluationError {
    fn from(value: TemporalEvaluationError) -> Self {
        Self::Temporal(value)
    }
}
impl From<FencedHoldoutError> for ProductEvaluationError {
    fn from(value: FencedHoldoutError) -> Self {
        Self::Holdout(value)
    }
}
impl From<ProductProviderErrorV1> for ProductEvaluationError {
    fn from(value: ProductProviderErrorV1) -> Self {
        Self::Provider(value)
    }
}
impl From<SignedEvaluationError> for ProductEvaluationError {
    fn from(value: SignedEvaluationError) -> Self {
        Self::Signed(value)
    }
}
impl From<ProductEvidenceSinkErrorV1> for ProductEvaluationError {
    fn from(value: ProductEvidenceSinkErrorV1) -> Self {
        Self::Sink(value)
    }
}

#[path = "product_publication.rs"]
mod publication;
pub use publication::product_qualification_publication_payload_v1;

#[cfg(test)]
#[path = "product_runner_tests.rs"]
mod tests;
