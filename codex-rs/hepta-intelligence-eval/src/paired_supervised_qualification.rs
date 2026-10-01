//! Independent Evaluator signs this profile's original execution and common
//! strict metric roles. Eligibility still grants no selection or model authority.

use std::collections::BTreeSet;

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::FinalHoldoutCasStoreV1;
use crate::IndependentEvaluationBundleV1;
use crate::MetricRoleContractV2;
use crate::PairedSupervisedErrorV1;
use crate::ProductEvaluationError;
use crate::ProductPairedEvaluationReceiptV1;
use crate::ProductQualificationContextV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationError;
use crate::SignedEvaluationEvidenceV1;
use crate::decide_independently_v2;
use crate::evaluation_signing_payload_v2;
use crate::paired_supervised_host_clock::PairedHostClockV1;
use crate::product_runner::ProductEvaluationRunnerV1;

/// This domain binds the distinct profile and original paired execution. Old
/// temporal/OPE Evaluator signatures cannot be reused as paired signatures.
pub fn paired_evaluation_signing_payload_v1(
    execution: &ProductPairedEvaluationReceiptV1,
    context: &ProductQualificationContextV1,
) -> Result<Vec<u8>, PairedSupervisedErrorV1> {
    let bundle = paired_bundle(execution, context)?;
    let roles = roles(execution);
    let mut bytes = b"hepta.eval.paired-supervised.independent-review.v1".to_vec();
    bytes.extend_from_slice(execution.registration.plan.profile_digest().as_array());
    bytes.extend_from_slice(execution.execution_digest.as_array());
    bytes.extend_from_slice(&evaluation_signing_payload_v2(&bundle, &roles)?);
    Ok(bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductPairedQualificationReceiptV1 {
    pub paired_execution_digest: Digest32,
    pub paired_profile_digest: Digest32,
    pub decision: SignedEvaluationDecisionV1,
    pub publication_digest: Digest32,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
    receipt_seal: Digest32,
}

impl ProductPairedQualificationReceiptV1 {
    pub fn validate_integrity(&self) -> Result<(), PairedSupervisedErrorV1> {
        if [
            self.paired_execution_digest,
            self.paired_profile_digest,
            self.publication_digest,
            self.decision.trust_digest,
            self.decision.authentication_digest,
            self.decision.decision.evidence_digest,
        ]
        .into_iter()
        .any(Digest32::is_zero)
            || self.authority.grants_any()
            || self.decision.decision.authority.grants_any()
            || self.evidence_digest != self.seal()
            || self.receipt_seal != self.evidence_digest
        {
            return Err(PairedSupervisedErrorV1::Binding(
                "paired qualification integrity",
            ));
        }
        Ok(())
    }

    fn seal(&self) -> Digest32 {
        let mut bytes = b"hepta.eval.paired-supervised.qualification-receipt.v1".to_vec();
        for digest in [
            self.paired_execution_digest,
            self.paired_profile_digest,
            self.decision.decision.evidence_digest,
            self.decision.trust_digest,
            self.decision.authentication_digest,
            self.publication_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        crate::push_id(&mut bytes, &self.decision.decision.evaluation_id);
        crate::push_id(&mut bytes, &self.decision.decision.candidate_id);
        crate::push_id(&mut bytes, &self.decision.decision.baseline_id);
        bytes.push(match self.decision.decision.disposition {
            crate::IndependentEvaluationDispositionV1::EligibleForIndependentSelection => 0,
            crate::IndependentEvaluationDispositionV1::Ineligible => 1,
            crate::IndependentEvaluationDispositionV1::InsufficientEvidence => 2,
        });
        bytes
            .extend_from_slice(&(self.decision.decision.failed_metrics.len() as u64).to_be_bytes());
        for metric in &self.decision.decision.failed_metrics {
            crate::push_id(&mut bytes, metric);
        }
        Digest32::of_bytes(&bytes)
    }
}

impl<S: FinalHoldoutCasStoreV1> ProductEvaluationRunnerV1<S> {
    pub fn paired_qualification_bundle(
        &self,
        execution: &ProductPairedEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
    ) -> Result<IndependentEvaluationBundleV1, PairedSupervisedErrorV1> {
        paired_bundle(execution, context)
    }

    pub fn qualify_paired_and_persist<E: ProductQualificationEvidenceSinkV1>(
        &self,
        execution: &ProductPairedEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        trust: &ActivatedLearningTrustV1,
        sink: &mut E,
    ) -> Result<ProductPairedQualificationReceiptV1, PairedSupervisedErrorV1> {
        self.qualify_paired_with_clock(
            execution,
            context,
            evidence,
            trust,
            sink,
            &mut PairedHostClockV1::system(),
        )
    }

    pub(crate) fn qualify_paired_with_clock<E: ProductQualificationEvidenceSinkV1>(
        &self,
        execution: &ProductPairedEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        trust: &ActivatedLearningTrustV1,
        sink: &mut E,
        clock: &mut PairedHostClockV1,
    ) -> Result<ProductPairedQualificationReceiptV1, PairedSupervisedErrorV1> {
        let now = clock.sample_registered(trust, &execution.registration)?;
        let verifier = trust.verifier();
        execution.verify_current(verifier, now)?;
        if evidence.generator_plan != execution.registration.generator_evidence
            || evidence.evaluator_bundle.issued_at
                < execution.observations.cut.finished_at_unix_micros / 1_000
        {
            return Err(PairedSupervisedErrorV1::Binding(
                "paired original generator/review clock",
            ));
        }
        let bundle = paired_bundle(execution, context)?;
        let payload = paired_evaluation_signing_payload_v1(execution, context)?;
        let authentication_digest =
            crate::signed_evaluation::authenticate(&bundle, evidence, verifier, &payload, now)?;
        let evaluator = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &evidence.evaluator_bundle,
                &payload,
                now,
            )
            .map_err(SignedEvaluationError::from)?;
        let observer = verifier
            .verify(
                LearningEvidenceRoleV1::Observer,
                &execution.observations.observer_evidence,
                &crate::paired_observation_cut_signing_payload_v1(&execution.observations.cut)?,
                now,
            )
            .map_err(SignedEvaluationError::from)?;
        verify_signed_independent_roles_v1(&observer, &evaluator, now)
            .map_err(SignedEvaluationError::from)?;
        // Hashing and independent signature checks may cross an expiry. The
        // sink is an actual effect, so sample the owner clock again and recheck
        // all original execution/registration/Evaluator evidence before it.
        let now = clock.sample_registered(trust, &execution.registration)?;
        execution.verify_current(verifier, now)?;
        let current_authentication =
            crate::signed_evaluation::authenticate(&bundle, evidence, verifier, &payload, now)?;
        if current_authentication != authentication_digest {
            return Err(PairedSupervisedErrorV1::Binding(
                "paired authentication changed before publication",
            ));
        }
        let decision = SignedEvaluationDecisionV1 {
            decision: decide_independently_v2(bundle, roles(execution), now)?,
            trust_digest: verifier.trust_digest(),
            authentication_digest,
        };
        let publication_digest = sink
            .persist(execution.execution_digest, &decision)
            .map_err(ProductEvaluationError::from)?;
        if publication_digest.is_zero() {
            return Err(PairedSupervisedErrorV1::Binding(
                "paired publication not durable",
            ));
        }
        let mut receipt = ProductPairedQualificationReceiptV1 {
            paired_execution_digest: execution.execution_digest,
            paired_profile_digest: execution.registration.plan.profile_digest(),
            decision,
            publication_digest,
            evidence_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
            receipt_seal: Digest32::ZERO,
        };
        receipt.evidence_digest = receipt.seal();
        receipt.receipt_seal = receipt.evidence_digest;
        receipt.validate_integrity()?;
        Ok(receipt)
    }
}

fn roles(execution: &ProductPairedEvaluationReceiptV1) -> Vec<MetricRoleContractV2> {
    execution
        .registration
        .plan
        .metrics
        .iter()
        .map(|metric| MetricRoleContractV2 {
            metric_id: metric.contract.metric_id.clone(),
            role: metric.role,
        })
        .collect()
}

fn paired_bundle(
    execution: &ProductPairedEvaluationReceiptV1,
    context: &ProductQualificationContextV1,
) -> Result<IndependentEvaluationBundleV1, PairedSupervisedErrorV1> {
    execution.validate()?;
    let frozen = &execution.registration.plan.frozen;
    let cut = &execution.observations.cut;
    let unique: BTreeSet<_> = context.retention_receipt_digests.iter().copied().collect();
    if context.generator != execution.registration.generator
        || context.retention_receipt_digests.is_empty()
        || context.retention_receipt_digests.len() > 128
        || unique.len() != context.retention_receipt_digests.len()
        || unique.iter().copied().any(Digest32::is_zero)
        || unique != cut.retention_receipt_digests.iter().copied().collect()
        || cut.retention_receipt_digests.len() != unique.len()
        || context.unlearning_receipt_digest.is_zero()
        || context.unlearning_receipt_digest != cut.unlearning_receipt_digest
    {
        return Err(PairedSupervisedErrorV1::Binding(
            "paired original retention/unlearning evidence",
        ));
    }
    Ok(IndependentEvaluationBundleV1 {
        evaluation_id: frozen.plan_id.clone(),
        candidate_id: frozen.candidate_id.clone(),
        baseline_id: frozen.baseline_id.clone(),
        claim_scope: frozen.claim_scope,
        generator: context.generator.clone(),
        evaluator: context.evaluator.clone(),
        frozen_plan: frozen.clone(),
        holdout_use: execution.holdout.use_receipt.clone(),
        objective_digest: frozen.objective_digest,
        dataset_digest: frozen.dataset_digest,
        estimand_digest: frozen.estimand_digest,
        estimate_receipt_digest: execution.estimate.evidence_digest,
        support_audit_digest: execution.support_digest,
        confidence_receipt_digest: execution.confidence_digest,
        retention_receipt_digests: context.retention_receipt_digests.clone(),
        unlearning_receipt_digest: context.unlearning_receipt_digest,
        snapshot_ids: vec![frozen.plan_id.clone()],
        future_window_ids: vec![frozen.final_holdout_window_id.clone()],
        family_alpha_ppm: frozen.family_alpha_ppm,
        simultaneous_comparisons: frozen.simultaneous_comparisons,
        metrics: execution.estimate.metrics.clone(),
    })
}
