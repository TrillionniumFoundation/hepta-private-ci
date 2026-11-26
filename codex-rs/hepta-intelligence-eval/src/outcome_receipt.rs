//! Immutable multi-outcome receipts assembled only from native estimators.

use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::EvaluationIntervalV1;
use crate::MetricGateV1;
use crate::OpeInterval;
use crate::ProductEvaluationError;
use crate::ProductFrozenOutcomePlanV1;
use crate::ProductMetricSourceV1;
use crate::ProductTemporalEvaluationReceiptV1;
use crate::SignedEvaluationDecisionV1;
use crate::TemporalEvaluationReceipt;
use crate::push_id;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductOutcomeEstimateV1 {
    pub channel_id: StableId,
    pub contract_digest: Digest32,
    pub candidate: TemporalEvaluationReceipt,
    pub baseline: TemporalEvaluationReceipt,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductOutcomeEvaluationReceiptV1 {
    pub(crate) carrier: ProductTemporalEvaluationReceiptV1,
    pub(crate) estimates: Vec<ProductOutcomeEstimateV1>,
    pub(crate) metrics: Vec<MetricGateV1>,
    pub(crate) estimate_digest: Digest32,
    pub(crate) support_digest: Digest32,
    pub(crate) confidence_digest: Digest32,
    pub(crate) execution_digest: Digest32,
}

impl ProductOutcomeEvaluationReceiptV1 {
    #[must_use]
    pub fn execution_digest(&self) -> Digest32 {
        self.execution_digest
    }

    #[must_use]
    pub fn metric_gates(&self) -> &[MetricGateV1] {
        &self.metrics
    }

    #[must_use]
    pub fn channel_estimates(&self) -> &[ProductOutcomeEstimateV1] {
        &self.estimates
    }

    #[must_use]
    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// A signed decision and durable publication identity, not a deployment grant.
/// Its immutable semantic header comes from the actual native evaluation, not
/// from the consumer's requested destination context. Consumers must separately
/// authenticate an exact-use attestation before binding a new runtime snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductOutcomeQualificationReceiptV1 {
    pub(crate) decision: SignedEvaluationDecisionV1,
    pub(crate) execution_digest: Digest32,
    pub(crate) publication_digest: Digest32,
    pub(crate) objective_digest: Digest32,
    pub(crate) dataset_digest: Digest32,
    pub(crate) evaluator: AuthenticatedPrincipalV1,
    pub(crate) snapshot_ids: Vec<StableId>,
}

impl ProductOutcomeQualificationReceiptV1 {
    #[must_use]
    pub fn decision(&self) -> &SignedEvaluationDecisionV1 {
        &self.decision
    }

    #[must_use]
    pub fn execution_digest(&self) -> Digest32 {
        self.execution_digest
    }

    #[must_use]
    pub fn publication_digest(&self) -> Digest32 {
        self.publication_digest
    }

    #[must_use]
    pub fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub fn dataset_digest(&self) -> Digest32 {
        self.dataset_digest
    }

    #[must_use]
    pub fn evaluator(&self) -> &AuthenticatedPrincipalV1 {
        &self.evaluator
    }

    #[must_use]
    pub fn snapshot_ids(&self) -> &[StableId] {
        &self.snapshot_ids
    }

    #[must_use]
    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

pub(crate) fn compose(
    plan: &ProductFrozenOutcomePlanV1,
    carrier: ProductTemporalEvaluationReceiptV1,
    additional: Vec<ProductOutcomeEstimateV1>,
) -> Result<ProductOutcomeEvaluationReceiptV1, ProductEvaluationError> {
    if carrier.product_plan != plan.carrier || additional.len() + 1 != plan.channels.len() {
        return Err(ProductEvaluationError::Integrity(
            "outcome composition coverage",
        ));
    }
    let mut estimates = vec![ProductOutcomeEstimateV1 {
        channel_id: plan.channels[0].channel_id.clone(),
        contract_digest: plan.channel_digests[0],
        candidate: carrier.candidate.clone(),
        baseline: carrier.baseline.clone(),
    }];
    estimates.extend(additional);
    let mut metrics = Vec::with_capacity(estimates.len());
    let mut estimate_bytes = b"hepta.learning-eval.outcome-estimates.v1".to_vec();
    let mut support_bytes = b"hepta.learning-eval.outcome-support.v1".to_vec();
    let mut confidence_bytes = b"hepta.learning-eval.outcome-confidence.v1".to_vec();
    for (index, estimate) in estimates.iter().enumerate() {
        let channel = &plan.channels[index];
        let contract = &plan.carrier.metric_contracts[index];
        let source = &plan.carrier.metric_sources[index];
        if estimate.channel_id != channel.channel_id
            || estimate.contract_digest != plan.channel_digests[index]
            || contract.metric_id != channel.metric_id
            || source.metric_id != channel.metric_id
        {
            return Err(ProductEvaluationError::Integrity(
                "outcome estimator identity",
            ));
        }
        estimate.candidate.validate_integrity()?;
        estimate.baseline.validate_integrity()?;
        let interval = |receipt: &TemporalEvaluationReceipt| -> OpeInterval {
            match source.source {
                ProductMetricSourceV1::Ips => receipt.estimate.ips,
                ProductMetricSourceV1::Snips => receipt.estimate.snips,
                ProductMetricSourceV1::DoublyRobust => receipt.estimate.doubly_robust,
            }
        };
        let candidate = interval(&estimate.candidate);
        let baseline = interval(&estimate.baseline);
        let mut support = b"hepta.learning-eval.measured-metric.v1".to_vec();
        push_id(&mut support, &channel.metric_id);
        support.push(match source.source {
            ProductMetricSourceV1::Ips => 0,
            ProductMetricSourceV1::Snips => 1,
            ProductMetricSourceV1::DoublyRobust => 2,
        });
        for digest in [
            estimate.contract_digest,
            channel.inputs_digest,
            estimate.candidate.evidence_digest,
            estimate.baseline.evidence_digest,
        ] {
            support.extend_from_slice(digest.as_array());
        }
        let support_digest = Digest32::of_bytes(&support);
        metrics.push(MetricGateV1 {
            metric_id: channel.metric_id.clone(),
            direction: contract.direction,
            candidate: EvaluationIntervalV1 {
                lower: candidate.lower,
                upper: candidate.upper,
            },
            baseline: EvaluationIntervalV1 {
                lower: baseline.lower,
                upper: baseline.upper,
            },
            safety_floor: contract.safety_floor,
            support_digest,
        });
        estimate_bytes.extend_from_slice(estimate.contract_digest.as_array());
        estimate_bytes.extend_from_slice(estimate.candidate.evidence_digest.as_array());
        estimate_bytes.extend_from_slice(estimate.baseline.evidence_digest.as_array());
        support_bytes.extend_from_slice(support_digest.as_array());
        confidence_bytes.extend_from_slice(estimate.contract_digest.as_array());
        confidence_bytes.extend_from_slice(estimate.candidate.estimate.evidence_digest.as_array());
        confidence_bytes.extend_from_slice(estimate.baseline.estimate.evidence_digest.as_array());
    }
    let estimate_digest = Digest32::of_bytes(&estimate_bytes);
    let support_digest = Digest32::of_bytes(&support_bytes);
    let confidence_digest = Digest32::of_bytes(&confidence_bytes);
    let mut execution = b"hepta.learning-eval.outcome-execution.v1".to_vec();
    for digest in [
        carrier.execution_digest,
        plan.carrier.frozen_plan.plan_digest,
        estimate_digest,
        support_digest,
        confidence_digest,
    ] {
        execution.extend_from_slice(digest.as_array());
    }
    Ok(ProductOutcomeEvaluationReceiptV1 {
        carrier,
        estimates,
        metrics,
        estimate_digest,
        support_digest,
        confidence_digest,
        execution_digest: Digest32::of_bytes(&execution),
    })
}
