//! Multi-outcome methods on the existing recorded runner. One authoritative
//! consume and one provider release feed all preregistered native estimators.

use std::collections::BTreeMap;

use super::*;
use crate::EvaluationClaimScopeV1;
use crate::FinalOutcomeHoldoutProviderV1;
use crate::ProductFrozenOutcomePlanV1;
use crate::ProductOutcomeEstimateV1;
use crate::ProductOutcomeEvaluationReceiptV1;
use crate::ProductOutcomeQualificationReceiptV1;
use crate::decide_with_signed_evidence_v2;
use crate::decide_with_signed_longitudinal_evidence_v3;
use crate::evaluate_temporal_holdout;
use crate::outcome_channels::MAX_BATCH_ROWS;
use crate::outcome_channels::validate_inputs;
use crate::outcome_receipt::compose;

// Publication, typed-archive and selected-host recovery extensions are mounted
// exactly once under `recorded_publication`; duplicating those path modules here
// creates a second set of inherent methods on the same recorded runner type.

struct OutcomeProvider<'a, P> {
    plan: &'a ProductFrozenOutcomePlanV1,
    inner: &'a mut P,
    additional: Vec<ProductOutcomeEstimateV1>,
}

impl<P: FinalOutcomeHoldoutProviderV1> FinalHoldoutProviderV1 for OutcomeProvider<'_, P> {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        self.inner.manifest_digest()
    }

    fn release_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        let batch = self.inner.release_after_consumption(receipt)?;
        if batch.len() != self.plan.channels.len() {
            return Err(ProductProviderErrorV1::Rejected);
        }
        let mut total = 0usize;
        let mut frames = BTreeMap::new();
        for frame in batch {
            for length in [frame.inputs.training.len(), frame.inputs.targets.len(),
                frame.inputs.candidate_observations.len(), frame.inputs.baseline_observations.len(),
                frame.inputs.assignments.len()] {
                total = total.checked_add(length).ok_or(ProductProviderErrorV1::Rejected)?;
                if total > MAX_BATCH_ROWS {
                    return Err(ProductProviderErrorV1::Rejected);
                }
            }
            if frames.insert(frame.channel_id.clone(), frame).is_some() {
                return Err(ProductProviderErrorV1::Rejected);
            }
        }
        let mut primary = None;
        let mut snapshots = None;
        for (index, channel) in self.plan.channels.iter().enumerate() {
            let mut frame = frames.remove(&channel.channel_id).ok_or(ProductProviderErrorV1::Rejected)?;
            if frame.contract_digest != self.plan.channel_digests[index] {
                return Err(ProductProviderErrorV1::Rejected);
            }
            validate_inputs(channel, &frame.inputs).map_err(|_| ProductProviderErrorV1::Rejected)?;
            frame.inputs.snapshot_ids.sort();
            if frame.inputs.snapshot_ids.is_empty()
                || snapshots.as_ref().is_some_and(|value| value != &frame.inputs.snapshot_ids) {
                return Err(ProductProviderErrorV1::Rejected);
            }
            snapshots = Some(frame.inputs.snapshot_ids.clone());
            if index == 0 {
                primary = Some(frame.inputs);
            } else {
                let evaluate = |plan: &TemporalEvaluationPlan, rows: &[crate::OpeRow]| {
                    evaluate_temporal_holdout(plan, &frame.inputs.training, &frame.inputs.targets,
                        rows, &frame.inputs.assignments).map_err(|_| ProductProviderErrorV1::Rejected)
                };
                self.additional.push(ProductOutcomeEstimateV1 {
                    channel_id: channel.channel_id.clone(), contract_digest: frame.contract_digest,
                    candidate: evaluate(&channel.candidate_plan, &frame.inputs.candidate_observations)?,
                    baseline: evaluate(&channel.baseline_plan, &frame.inputs.baseline_observations)?,
                });
            }
        }
        primary.ok_or(ProductProviderErrorV1::Rejected)
    }
}

impl<S: FinalHoldoutCasStoreV1> RecordedProductEvaluationRunnerV1<S> {
    pub fn evaluate_outcome_comparison<P, J>(
        &mut self,
        attempt_id: StableId,
        plan: &ProductFrozenOutcomePlanV1,
        provider: &mut P,
        journal: &mut J,
    ) -> Result<ProductOutcomeEvaluationReceiptV1, RecordedProductEvaluationErrorV1>
    where
        P: FinalOutcomeHoldoutProviderV1,
        J: DurableProductEvaluationAttemptJournalV1,
    {
        let primary = &plan.channels[0];
        let mut measured = OutcomeProvider { plan, inner: provider, additional: Vec::new() };
        self.evaluate_recorded(attempt_id, &plan.carrier, &primary.candidate_plan,
            &primary.baseline_plan, &mut measured, journal, |carrier, measured| {
                let receipt = compose(plan, carrier, std::mem::take(&mut measured.additional))?;
                let digest = receipt.execution_digest();
                Ok((receipt, digest))
            })
    }

    pub fn outcome_qualification_bundle(
        &self,
        temporal: &ProductOutcomeEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
    ) -> Result<crate::IndependentEvaluationBundleV1, ProductEvaluationError> {
        let mut bundle = self.inner.qualification_bundle(&temporal.carrier, context)?;
        bundle.metrics = temporal.metrics.clone();
        bundle.estimate_receipt_digest = temporal.estimate_digest;
        bundle.support_audit_digest = temporal.support_digest;
        bundle.confidence_receipt_digest = temporal.confidence_digest;
        Ok(bundle)
    }

    // The unarchived multi-outcome qualification boundary is an internal helper.
    // Cross-crate callers must use the typed-archive or selected-host methods.
    #[allow(dead_code, clippy::too_many_arguments)]
    pub(crate) fn qualify_outcomes_and_persist<J: DurableProductEvaluationAttemptJournalV1>(
        &self,
        attempt_id: &StableId,
        temporal: &ProductOutcomeEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        journal: &mut J,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<ProductOutcomeQualificationReceiptV1, RecordedProductEvaluationErrorV1> {
        let latest = journal.latest(attempt_id)?.ok_or(
            RecordedProductEvaluationErrorV1::AttemptRequiresRecovery { attempt_id: attempt_id.clone() })?;
        latest.validate_integrity()?;
        if latest.transition.phase != ProductEvaluationAttemptPhaseV1::ComparisonSealed
            || latest.transition.plan_digest != temporal.carrier.product_plan.frozen_plan.plan_digest
            || latest.transition.holdout_record_digest != temporal.carrier.holdout.record_digest
            || latest.transition.terminal_digest != temporal.execution_digest
        {
            return Err(RecordedProductEvaluationErrorV1::AttemptRequiresRecovery { attempt_id: attempt_id.clone() });
        }
        let bundle = self.outcome_qualification_bundle(temporal, context)
            .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
        let roles = temporal.carrier.product_plan.metric_roles.clone();
        let decision = match timing {
            ProductTimingEvidenceV1::Qualification => {
                if bundle.claim_scope != EvaluationClaimScopeV1::Qualification {
                    return Err(RecordedProductEvaluationErrorV1::Evaluation(
                        ProductEvaluationError::Binding("outcome qualification scope")));
                }
                decide_with_signed_evidence_v2(bundle, roles, evidence, verifier, now)
            }
            ProductTimingEvidenceV1::SystemLongitudinal { timing, minimum_window_micros } => {
                if bundle.claim_scope != EvaluationClaimScopeV1::SystemLongitudinal {
                    return Err(RecordedProductEvaluationErrorV1::Evaluation(
                        ProductEvaluationError::Binding("outcome longitudinal scope")));
                }
                decide_with_signed_longitudinal_evidence_v3(bundle, roles, evidence,
                    timing, minimum_window_micros, verifier, now)
            }
        }.map_err(|error| RecordedProductEvaluationErrorV1::Evaluation(ProductEvaluationError::Signed(error)))?;
        let mut recorded = RecordedPublicationSinkV1 {
            attempt_id: attempt_id.clone(), plan_digest: latest.transition.plan_digest,
            holdout_record_digest: latest.transition.holdout_record_digest,
            journal, inner: sink, journal_error: None,
        };
        let result = recorded.persist(temporal.execution_digest, &decision);
        if let Some(error) = recorded.journal_error {
            return Err(RecordedProductEvaluationErrorV1::Journal(error));
        }
        let publication_digest = result.map_err(|error|
            RecordedProductEvaluationErrorV1::Evaluation(ProductEvaluationError::Sink(error)))?;
        if publication_digest.is_zero() || decision.decision.authority.grants_any() {
            return Err(RecordedProductEvaluationErrorV1::Evaluation(
                ProductEvaluationError::Integrity("outcome publication")));
        }
        Ok(ProductOutcomeQualificationReceiptV1 {
            decision, execution_digest: temporal.execution_digest, publication_digest,
            objective_digest: temporal.carrier.product_plan.frozen_plan.objective_digest,
            dataset_digest: temporal.carrier.product_plan.frozen_plan.dataset_digest,
            evaluator: context.evaluator.clone(),
            snapshot_ids: temporal.carrier.snapshot_ids.clone(),
        })
    }
}
