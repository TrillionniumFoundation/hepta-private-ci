//! Resume the publication boundary known not to have been invoked.
//!
//! QualificationDecided is durable before PublicationPending; the underlying
//! sink is invoked only after Pending is acknowledged. Pending attempts may
//! have unknown writes and are never passed back to the sink here. Public
//! recovery reconstructs the decision from sealed results and current verified
//! evidence; a caller-supplied SignedEvaluationDecision is not a public ingress.

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::DurableProductEvaluationAttemptJournalV1;
use crate::EvaluationClaimScopeV1;
use crate::FinalHoldoutCasStoreV1;
use crate::IndependentEvaluationBundleV1;
use crate::MetricRoleContractV2;
use crate::ProductEvaluationAttemptPhaseV1;
use crate::ProductEvaluationAttemptReceiptV1;
use crate::ProductEvaluationError;
use crate::ProductOutcomeEvaluationReceiptV1;
use crate::ProductQualificationContextV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::ProductQualificationPublicationRequestV1;
use crate::ProductTemporalEvaluationReceiptV1;
use crate::ProductTimingEvidenceV1;
use crate::RecordedProductEvaluationErrorV1;
use crate::RecordedProductEvaluationRunnerV1;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationEvidenceV1;
use crate::attempt_recovery::validated_history;
use crate::decide_with_signed_evidence_v2;
use crate::decide_with_signed_longitudinal_evidence_v3;
use crate::recorded_publication::RecordedPublicationSinkV1;

fn verify_decision(
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    evidence: &SignedEvaluationEvidenceV1,
    timing: ProductTimingEvidenceV1<'_>,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<SignedEvaluationDecisionV1, RecordedProductEvaluationErrorV1> {
    let result = match timing {
        ProductTimingEvidenceV1::Qualification => {
            if bundle.claim_scope != EvaluationClaimScopeV1::Qualification {
                return Err(RecordedProductEvaluationErrorV1::Evaluation(
                    ProductEvaluationError::Binding("recovery qualification scope"),
                ));
            }
            decide_with_signed_evidence_v2(bundle, roles, evidence, verifier, now)
        }
        ProductTimingEvidenceV1::SystemLongitudinal {
            timing,
            minimum_window_micros,
        } => {
            if bundle.claim_scope != EvaluationClaimScopeV1::SystemLongitudinal {
                return Err(RecordedProductEvaluationErrorV1::Evaluation(
                    ProductEvaluationError::Binding("recovery longitudinal scope"),
                ));
            }
            decide_with_signed_longitudinal_evidence_v3(
                bundle,
                roles,
                evidence,
                timing,
                minimum_window_micros,
                verifier,
                now,
            )
        }
    };
    result.map_err(|error| {
        RecordedProductEvaluationErrorV1::Evaluation(ProductEvaluationError::Signed(error))
    })
}

fn bind_execution<J: DurableProductEvaluationAttemptJournalV1>(
    journal: &mut J,
    attempt: &StableId,
    plan: Digest32,
    holdout: Digest32,
    execution: Digest32,
) -> Result<(), RecordedProductEvaluationErrorV1> {
    let history = validated_history(journal, attempt).map_err(|error| match error {
        crate::ProductAttemptRecoveryErrorV1::Journal(error) => {
            RecordedProductEvaluationErrorV1::Journal(error)
        }
        _ => RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
            attempt_id: attempt.clone(),
        },
    })?;
    if !history.last().is_some_and(|receipt| {
        receipt.transition.phase == ProductEvaluationAttemptPhaseV1::QualificationDecided
    }) || !history.iter().any(|receipt| {
        receipt.transition.phase == ProductEvaluationAttemptPhaseV1::ComparisonSealed
            && receipt.transition.plan_digest == plan
            && receipt.transition.holdout_record_digest == holdout
            && receipt.transition.terminal_digest == execution
    }) {
        return Err(RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
            attempt_id: attempt.clone(),
        });
    }
    Ok(())
}

impl<S: FinalHoldoutCasStoreV1> RecordedProductEvaluationRunnerV1<S> {
    /// Resume a prewrite single-outcome qualification from the original complete
    /// sealed receipt and signed evidence. Current trust/expiry/revocation checks
    /// still apply; recovery does not extend a signature's validity period.
    #[allow(clippy::too_many_arguments)]
    pub fn resume_decided_qualification<J: DurableProductEvaluationAttemptJournalV1>(
        &self,
        journal: &mut J,
        attempt_id: &StableId,
        temporal: &ProductTemporalEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, RecordedProductEvaluationErrorV1> {
        bind_execution(
            journal,
            attempt_id,
            temporal.product_plan.frozen_plan.plan_digest,
            temporal.holdout.record_digest,
            temporal.execution_digest,
        )?;
        let bundle = self
            .qualification_bundle(temporal, context)
            .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
        let decision = verify_decision(
            bundle,
            temporal.product_plan.metric_roles.clone(),
            evidence,
            timing,
            verifier,
            now,
        )?;
        Self::resume_decided_publication(journal, attempt_id, &decision, sink)
    }

    /// Equivalent resume for the sealed multi-outcome receipt. Its execution
    /// digest, not the internal single-stream carrier, must match the journal.
    #[allow(clippy::too_many_arguments)]
    pub fn resume_decided_outcome_qualification<J: DurableProductEvaluationAttemptJournalV1>(
        &self,
        journal: &mut J,
        attempt_id: &StableId,
        temporal: &ProductOutcomeEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, RecordedProductEvaluationErrorV1> {
        bind_execution(
            journal,
            attempt_id,
            temporal.carrier.product_plan.frozen_plan.plan_digest,
            temporal.carrier.holdout.record_digest,
            temporal.execution_digest(),
        )?;
        let bundle = self
            .outcome_qualification_bundle(temporal, context)
            .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
        let decision = verify_decision(
            bundle,
            temporal.carrier.product_plan.metric_roles.clone(),
            evidence,
            timing,
            verifier,
            now,
        )?;
        Self::resume_decided_publication(journal, attempt_id, &decision, sink)
    }

    /// Internal post-verification boundary, also exercised by isolated process
    /// fixtures. This is deliberately not callable by another crate.
    pub(crate) fn resume_decided_publication<J: DurableProductEvaluationAttemptJournalV1>(
        journal: &mut J,
        attempt_id: &StableId,
        decision: &SignedEvaluationDecisionV1,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, RecordedProductEvaluationErrorV1> {
        let rejected = || RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
            attempt_id: attempt_id.clone(),
        };
        let history = validated_history(journal, attempt_id).map_err(|error| match error {
            crate::ProductAttemptRecoveryErrorV1::Journal(error) => {
                RecordedProductEvaluationErrorV1::Journal(error)
            }
            _ => rejected(),
        })?;
        let latest = history.last().ok_or_else(rejected)?;
        if latest.transition.phase != ProductEvaluationAttemptPhaseV1::QualificationDecided {
            return Err(rejected());
        }
        let sealed = history
            .iter()
            .find(|receipt| {
                receipt.transition.phase == ProductEvaluationAttemptPhaseV1::ComparisonSealed
            })
            .ok_or_else(rejected)?;
        let execution = sealed.transition.terminal_digest;
        let request = ProductQualificationPublicationRequestV1::new(execution, decision).map_err(
            |error| {
                RecordedProductEvaluationErrorV1::Evaluation(ProductEvaluationError::Sink(error))
            },
        )?;
        if request.request_digest != latest.transition.terminal_digest {
            return Err(rejected());
        }
        let mut recorded = RecordedPublicationSinkV1 {
            attempt_id: attempt_id.clone(),
            plan_digest: latest.transition.plan_digest,
            holdout_record_digest: latest.transition.holdout_record_digest,
            journal,
            inner: sink,
            journal_error: None,
        };
        let result = recorded.persist(execution, decision);
        if let Some(error) = recorded.journal_error {
            return Err(RecordedProductEvaluationErrorV1::Journal(error));
        }
        result.map_err(|error| {
            RecordedProductEvaluationErrorV1::Evaluation(ProductEvaluationError::Sink(error))
        })?;
        let receipt = recorded.journal.latest(attempt_id)?.ok_or_else(rejected)?;
        if receipt.transition.phase != ProductEvaluationAttemptPhaseV1::Published {
            return Err(rejected());
        }
        receipt.validate_integrity()?;
        Ok(receipt)
    }
}
