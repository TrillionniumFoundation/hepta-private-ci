//! DecisionCell evaluation binding to the existing signed longitudinal owner.
//!
//! The estimator, fenced holdout, authenticated observers and independent
//! evaluator remain owned by the product evaluation runner. This adapter adds
//! complete CellSplit metric coverage, authentic resource measurements, and an
//! immutable receipt that can be bound into the final split contract.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_verified_role_separation;
use codex_hepta_types::CellSplitEvaluationBindingV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::EvaluationClaimScopeV1;
use crate::EvaluationDirectionV1;
use crate::IndependentEvaluationBundleV1;
use crate::IndependentEvaluationDispositionV1;
use crate::LongitudinalTimeEvidenceV1;
use crate::MetricGateV1;
use crate::MetricRoleContractV2;
use crate::MetricRoleV2;
use crate::ProductQualificationReceiptV1;
use crate::ProductTemporalEvaluationReceiptV1;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationEvidenceV1;
use crate::cell_split_lifecycle::CellSplitEvaluationDispositionV1;
use crate::cell_split_resources::CellSplitResourceEvidenceOriginV1;
use crate::cell_split_resources::CellSplitResourceReceiptV1;
use crate::decide_with_signed_longitudinal_evidence_v3;

/// Required metric identities and preregistered longitudinal duration. Their
/// semantics are explicit rather than inferred from a display name.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitEvaluationProfileV1 {
    pub utility: StableId,
    pub retention: StableId,
    pub task_coverage: StableId,
    pub negative_transfer: StableId,
    pub latency: StableId,
    pub memory: StableId,
    pub communication: StableId,
    pub training_cost: StableId,
    pub failure_rate: StableId,
    pub rollback_rate: StableId,
    pub minimum_future_window_micros: u64,
    pub base_estimand_digest: Digest32,
}

impl CellSplitEvaluationProfileV1 {
    fn metrics(&self) -> [(&StableId, EvaluationDirectionV1); 10] {
        use EvaluationDirectionV1::Maximize;
        use EvaluationDirectionV1::Minimize;
        [
            (&self.utility, Maximize),
            (&self.retention, Maximize),
            (&self.task_coverage, Maximize),
            (&self.negative_transfer, Minimize),
            (&self.latency, Minimize),
            (&self.memory, Minimize),
            (&self.communication, Minimize),
            (&self.training_cost, Minimize),
            (&self.failure_rate, Minimize),
            (&self.rollback_rate, Minimize),
        ]
    }

    fn validate(&self) -> Result<(), CellSplitEvaluationErrorV1> {
        let metrics = self.metrics();
        if self.minimum_future_window_micros == 0
            || self.base_estimand_digest.is_zero()
            || metrics
                .iter()
                .map(|row| row.0)
                .collect::<BTreeSet<_>>()
                .len()
                != metrics.len()
        {
            return Err(CellSplitEvaluationErrorV1::Binding("evaluation profile"));
        }
        Ok(())
    }
}

/// Freeze this digest as `CrossFoldPlanV1.estimand_digest` before passing the
/// plan to `freeze_product_evaluation_plan_v1`. The product runner additionally
/// binds its exact temporal estimator plans and metric sources.
pub fn cell_split_bound_estimand_digest_v1(
    split: &CellSplitV1,
    profile: &CellSplitEvaluationProfileV1,
) -> Result<Digest32, CellSplitEvaluationErrorV1> {
    profile.validate()?;
    let subject = split
        .evaluation_subject_digest()
        .map_err(|_| CellSplitEvaluationErrorV1::Binding("split subject"))?;
    let mut bytes = b"hepta.learning.cell-split.estimand.v1".to_vec();
    bytes.extend_from_slice(subject.as_array());
    bytes.extend_from_slice(profile.base_estimand_digest.as_array());
    bytes.extend_from_slice(&profile.minimum_future_window_micros.to_be_bytes());
    for (id, direction) in profile.metrics() {
        push_id(&mut bytes, id);
        bytes.push(match direction {
            EvaluationDirectionV1::Maximize => 0,
            EvaluationDirectionV1::Minimize => 1,
        });
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub struct CellSplitEvaluationRequestV1<'a> {
    pub split: &'a CellSplitV1,
    pub profile: &'a CellSplitEvaluationProfileV1,
    pub temporal: &'a ProductTemporalEvaluationReceiptV1,
    pub qualification: &'a ProductQualificationReceiptV1,
    pub bundle: IndependentEvaluationBundleV1,
    pub roles: Vec<MetricRoleContractV2>,
    pub evidence: &'a SignedEvaluationEvidenceV1,
    pub timing: &'a LongitudinalTimeEvidenceV1,
    pub resources: &'a CellSplitResourceReceiptV1,
    pub resource_evidence: &'a SignedLearningEvidenceV1,
}

/// Opaque, authenticated result. It is evidence for governance, not a runtime
/// apply/selection token. Fields are private to prevent fabricating a result
/// from receipt digests alone.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitLongHorizonEvaluationReceiptV1 {
    split_id: StableId,
    subject_digest: Digest32,
    binding: CellSplitEvaluationBindingV1,
    decision: SignedEvaluationDecisionV1,
    publication_digest: Digest32,
    resource_authentication_digest: Digest32,
    metrics: Vec<MetricGateV1>,
}

impl CellSplitLongHorizonEvaluationReceiptV1 {
    pub fn split_id(&self) -> &StableId {
        &self.split_id
    }
    pub fn subject_digest(&self) -> Digest32 {
        self.subject_digest
    }
    pub fn binding(&self) -> &CellSplitEvaluationBindingV1 {
        &self.binding
    }
    pub fn decision(&self) -> &SignedEvaluationDecisionV1 {
        &self.decision
    }
    pub fn metrics(&self) -> &[MetricGateV1] {
        &self.metrics
    }
    pub fn publication_digest(&self) -> Digest32 {
        self.publication_digest
    }
    pub fn resource_authentication_digest(&self) -> Digest32 {
        self.resource_authentication_digest
    }
    #[must_use]
    pub fn disposition(&self) -> CellSplitEvaluationDispositionV1 {
        match self.decision.decision.disposition {
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection => {
                CellSplitEvaluationDispositionV1::EligibleForCanary
            }
            IndependentEvaluationDispositionV1::InsufficientEvidence => {
                CellSplitEvaluationDispositionV1::InsufficientEvidence
            }
            IndependentEvaluationDispositionV1::Ineligible => {
                CellSplitEvaluationDispositionV1::Quarantine
            }
        }
    }

    pub fn bind_contract(&self, split: &mut CellSplitV1) -> Result<(), CellSplitEvaluationErrorV1> {
        if split.split_id != self.split_id
            || split
                .evaluation_subject_digest()
                .map_err(|_| CellSplitEvaluationErrorV1::Binding("subject"))?
                != self.subject_digest
        {
            return Err(CellSplitEvaluationErrorV1::Binding("evaluated subject"));
        }
        split.evaluation = self.binding.clone();
        split
            .validate()
            .map_err(|_| CellSplitEvaluationErrorV1::Binding("complete contract"))
    }

    pub fn verify_contract(&self, split: &CellSplitV1) -> Result<(), CellSplitEvaluationErrorV1> {
        if split.evaluation != self.binding
            || split.split_id != self.split_id
            || split
                .evaluation_subject_digest()
                .map_err(|_| CellSplitEvaluationErrorV1::Binding("subject"))?
                != self.subject_digest
        {
            return Err(CellSplitEvaluationErrorV1::Binding("contract receipt"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitEvaluationErrorV1 {
    Binding(&'static str),
    Evidence(String),
}
impl fmt::Display for CellSplitEvaluationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for CellSplitEvaluationErrorV1 {}

/// Reuse the production estimator/holdout receipt and reverify all signatures
/// under the current host trust snapshot. No local sample counter can bypass
/// this entrypoint or manufacture an independent future-window observation.
pub fn evaluate_cell_split_long_horizon_v1(
    request: CellSplitEvaluationRequestV1<'_>,
    verifier: &LearningEvidenceVerifierV1,
    now_unix_micros: u64,
) -> Result<CellSplitLongHorizonEvaluationReceiptV1, CellSplitEvaluationErrorV1> {
    let split = request.split;
    split
        .validate_plan()
        .map_err(|_| CellSplitEvaluationErrorV1::Binding("split plan"))?;
    if request.resources.origin != CellSplitResourceEvidenceOriginV1::TargetHostMeasurement {
        return Err(CellSplitEvaluationErrorV1::Binding(
            "target-host resource origin",
        ));
    }
    request
        .temporal
        .validate_integrity()
        .map_err(|error| CellSplitEvaluationErrorV1::Evidence(error.to_string()))?;
    request
        .qualification
        .validate_integrity()
        .map_err(|error| CellSplitEvaluationErrorV1::Evidence(error.to_string()))?;
    let subject_digest = split
        .evaluation_subject_digest()
        .map_err(|_| CellSplitEvaluationErrorV1::Binding("split subject"))?;
    let estimand = cell_split_bound_estimand_digest_v1(split, request.profile)?;
    if request.temporal.product_plan.base_estimand_digest != estimand
        || request.temporal.execution_digest != request.qualification.temporal_execution_digest
        || request.bundle.claim_scope != EvaluationClaimScopeV1::SystemLongitudinal
        || request.qualification.claim_scope != EvaluationClaimScopeV1::SystemLongitudinal
        || request.bundle.candidate_id != split.split_id
        || request.bundle.evaluation_id != split.evaluation.evaluation_id
        || request.bundle.baseline_id != split.evaluation.no_change_baseline_id
        || request.bundle.generator.principal_id != split.proposer_id
        || request.bundle.evaluator.principal_id != split.evaluator_id
        || request.qualification.candidate_id != split.split_id
        || request.qualification.generator.principal_id != split.proposer_id
        || request.qualification.evaluator.principal_id != split.evaluator_id
        || request.qualification.objective_digest != request.bundle.objective_digest
        || request.qualification.dataset_digest != request.bundle.dataset_digest
        || request.bundle.metrics != request.temporal.metrics
        || request.bundle.frozen_plan != request.temporal.product_plan.frozen_plan
    {
        return Err(CellSplitEvaluationErrorV1::Binding("product evaluation"));
    }
    let metric = |id: &StableId| {
        request
            .bundle
            .metrics
            .iter()
            .find(|row| &row.metric_id == id)
            .ok_or(CellSplitEvaluationErrorV1::Binding("required metric"))
    };
    for (id, direction) in request.profile.metrics() {
        let row = metric(id)?;
        if row.direction != direction || row.support_digest.is_zero() {
            return Err(CellSplitEvaluationErrorV1::Binding(
                "metric direction or support",
            ));
        }
        if !request.roles.iter().any(|role| &role.metric_id == id) {
            return Err(CellSplitEvaluationErrorV1::Binding("metric role coverage"));
        }
    }
    if !request.roles.iter().any(|row| {
        row.metric_id == request.profile.utility
            && matches!(row.role, MetricRoleV2::PrimarySuperiority { .. })
    }) {
        return Err(CellSplitEvaluationErrorV1::Binding("utility superiority"));
    }
    let retention_support_digest = metric(&request.profile.retention)?.support_digest;
    let retention_digest = *request
        .bundle
        .retention_receipt_digests
        .first()
        .ok_or(CellSplitEvaluationErrorV1::Binding("retention receipt"))?;
    if retention_digest.is_zero() {
        return Err(CellSplitEvaluationErrorV1::Binding("retention receipt"));
    }
    let negative_transfer_digest = metric(&request.profile.negative_transfer)?.support_digest;
    request
        .resources
        .validate_for(split, request.timing)
        .map_err(CellSplitEvaluationErrorV1::Binding)?;
    let resource_payload = request.resources.signing_payload();
    let cost_digest = Digest32::of_bytes(&resource_payload);
    for id in [
        &request.profile.latency,
        &request.profile.memory,
        &request.profile.communication,
        &request.profile.training_cost,
        &request.profile.failure_rate,
        &request.profile.rollback_rate,
    ] {
        if metric(id)?.support_digest != cost_digest {
            return Err(CellSplitEvaluationErrorV1::Binding(
                "measured resource support",
            ));
        }
    }
    let resource_observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            request.resource_evidence,
            &resource_payload,
            now_unix_micros,
        )
        .map_err(|error| CellSplitEvaluationErrorV1::Evidence(error.to_string()))?;
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &request.evidence.generator_plan,
            request.bundle.frozen_plan.plan_digest.as_array(),
            now_unix_micros,
        )
        .map_err(|error| CellSplitEvaluationErrorV1::Evidence(error.to_string()))?;
    verify_verified_role_separation(&resource_observer, &generator, now_unix_micros)
        .map_err(|error| CellSplitEvaluationErrorV1::Evidence(error.to_string()))?;
    let evaluation_payload = crate::longitudinal_evaluation_signing_payload_v3(
        &request.bundle,
        &request.roles,
        request.timing,
        request.profile.minimum_future_window_micros,
    )
    .map_err(|error| CellSplitEvaluationErrorV1::Evidence(error.to_string()))?;
    let evaluator = verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &request.evidence.evaluator_bundle,
            &evaluation_payload,
            now_unix_micros,
        )
        .map_err(|error| CellSplitEvaluationErrorV1::Evidence(error.to_string()))?;
    verify_verified_role_separation(&resource_observer, &evaluator, now_unix_micros)
        .map_err(|error| CellSplitEvaluationErrorV1::Evidence(error.to_string()))?;
    let timing_payload = crate::future_window_signing_payload_v1(
        &request.bundle,
        request.timing,
        request.profile.minimum_future_window_micros,
    )
    .map_err(|error| CellSplitEvaluationErrorV1::Evidence(error.to_string()))?;
    let timing_observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &request.timing.observer,
            &timing_payload,
            now_unix_micros,
        )
        .map_err(|error| CellSplitEvaluationErrorV1::Evidence(error.to_string()))?;
    verify_verified_role_separation(&resource_observer, &timing_observer, now_unix_micros)
        .map_err(|error| CellSplitEvaluationErrorV1::Evidence(error.to_string()))?;
    let decision = decide_with_signed_longitudinal_evidence_v3(
        request.bundle.clone(),
        request.roles,
        request.evidence,
        request.timing,
        request.profile.minimum_future_window_micros,
        verifier,
        now_unix_micros,
    )
    .map_err(|error| CellSplitEvaluationErrorV1::Evidence(error.to_string()))?;
    if decision != request.qualification.decision {
        return Err(CellSplitEvaluationErrorV1::Binding(
            "qualification decision",
        ));
    }
    let mut receipt_bytes = b"hepta.learning.cell-split.evaluation-receipt.v1".to_vec();
    for digest in [
        subject_digest,
        estimand,
        decision.decision.evidence_digest,
        decision.authentication_digest,
        request.qualification.publication_digest,
        retention_digest,
        retention_support_digest,
        negative_transfer_digest,
        cost_digest,
    ] {
        receipt_bytes.extend_from_slice(digest.as_array());
    }
    receipt_bytes.extend_from_slice(&request.resource_evidence.signature);
    let binding = CellSplitEvaluationBindingV1 {
        no_change_baseline_id: request.bundle.baseline_id.clone(),
        evaluation_id: request.bundle.evaluation_id.clone(),
        evaluator_id: split.evaluator_id.clone(),
        evaluation_receipt_digest: Digest32::of_bytes(&receipt_bytes),
        retention_receipt_digest: retention_digest,
        negative_transfer_receipt_digest: negative_transfer_digest,
        cost_receipt_digest: cost_digest,
    };
    Ok(CellSplitLongHorizonEvaluationReceiptV1 {
        split_id: split.split_id.clone(),
        subject_digest,
        binding,
        decision,
        publication_digest: request.qualification.publication_digest,
        resource_authentication_digest: Digest32::of_bytes(
            &request.resource_evidence.signing_bytes(),
        ),
        metrics: request.bundle.metrics.clone(),
    })
}

pub(crate) fn disposition_allows_canary(receipt: &CellSplitLongHorizonEvaluationReceiptV1) -> bool {
    receipt.decision.decision.disposition
        == IndependentEvaluationDispositionV1::EligibleForIndependentSelection
}

#[cfg(test)]
pub(crate) fn test_receipt_for_lifecycle(
    split: &CellSplitV1,
    disposition: CellSplitEvaluationDispositionV1,
) -> CellSplitLongHorizonEvaluationReceiptV1 {
    use codex_hepta_types::AuthorityPosture;

    let subject_digest = split
        .evaluation_subject_digest()
        .expect("test split subject");
    let decision_disposition = match disposition {
        CellSplitEvaluationDispositionV1::EligibleForCanary => {
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        }
        CellSplitEvaluationDispositionV1::InsufficientEvidence => {
            IndependentEvaluationDispositionV1::InsufficientEvidence
        }
        CellSplitEvaluationDispositionV1::Quarantine => {
            IndependentEvaluationDispositionV1::Ineligible
        }
    };
    let decision = SignedEvaluationDecisionV1 {
        decision: crate::IndependentEvaluationDecisionV1 {
            evaluation_id: split.evaluation.evaluation_id.clone(),
            candidate_id: split.split_id.clone(),
            baseline_id: split.evaluation.no_change_baseline_id.clone(),
            disposition: decision_disposition,
            failed_metrics: Vec::new(),
            evidence_digest: Digest32::from_array([21; 32]),
            authority: AuthorityPosture::DENY_ALL,
        },
        trust_digest: Digest32::from_array([22; 32]),
        authentication_digest: Digest32::from_array([23; 32]),
    };
    CellSplitLongHorizonEvaluationReceiptV1 {
        split_id: split.split_id.clone(),
        subject_digest,
        binding: CellSplitEvaluationBindingV1 {
            no_change_baseline_id: split.evaluation.no_change_baseline_id.clone(),
            evaluation_id: split.evaluation.evaluation_id.clone(),
            evaluator_id: split.evaluator_id.clone(),
            evaluation_receipt_digest: Digest32::from_array([24; 32]),
            retention_receipt_digest: Digest32::from_array([25; 32]),
            negative_transfer_receipt_digest: Digest32::from_array([26; 32]),
            cost_receipt_digest: Digest32::from_array([27; 32]),
        },
        decision,
        publication_digest: Digest32::from_array([28; 32]),
        resource_authentication_digest: Digest32::from_array([29; 32]),
        metrics: Vec::new(),
    }
}

pub(crate) fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let value = id.as_str().as_bytes();
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value);
}
