//! Adversarial controls reuse genuine runner receipts and actual role signatures.
use super::support::Fitted;
use super::support::Roles;
use super::support::micros;
use super::support::save;
use super::*;
use codex_hepta_intelligence_eval as eval;

#[allow(clippy::too_many_arguments)]
pub(super) fn canonical_controls(
    root: &std::path::Path,
    qualification: &eval::ProductQualificationReceiptV1,
    binding: &codex_hepta_learning_ledger::SignedLearningEvidenceV1,
    policy: &eval::SelfEvolutionSelectionPolicyV1,
    request: &eval::SelfEvolutionSelectionRequestV1,
    bundle: &eval::IndependentEvaluationBundleV1,
    metric_roles: &[eval::MetricRoleContractV2],
    evidence: &eval::SignedEvaluationEvidenceV1,
    timing: &eval::LongitudinalTimeEvidenceV1,
    candidate: &Fitted,
    roles: &mut Roles,
) -> VerifiedSelfEvolutionSelectionV1 {
    let mut seal_denials = Vec::new();
    for label in ["publication", "qualification-evidence"] {
        let mut changed = qualification.clone();
        if label == "publication" {
            changed.publication_digest = hash("substituted-product-publication");
        } else {
            changed.evidence_digest = hash("substituted-product-qualification");
        }
        let error = changed.validate_integrity().unwrap_err();
        seal_denials.push(json!({"control":label,"error":error.to_string()}));
    }
    let mut byte_denials = Vec::new();
    for label in ["candidate", "predecessor"] {
        let mut changed = request.clone();
        if label == "candidate" {
            changed.candidate_artifact_digest = hash("substituted-candidate-bytes");
        } else {
            changed.predecessor_artifact_digest = hash("substituted-predecessor-bytes");
        }
        let error = eval::prepare_self_evolution_product_selection_v1(
            qualification,
            binding,
            policy,
            changed,
            bundle.clone(),
            metric_roles.to_vec(),
            evidence,
            timing,
            &candidate.dataset,
            &candidate.snapshot,
            &roles.verifier,
            micros(),
        )
        .unwrap_err();
        byte_denials.push(json!({"control":label,"error":error.to_string()}));
    }
    let lifetime_control = if qualification.decision.decision.disposition
        == eval::IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    {
        let issued = micros();
        let mut short = binding.clone();
        short.evidence_id = id(&format!("short-product-binding-{issued}"));
        short.issued_at = issued;
        short.expires_at = issued + 60_000_000;
        short.signature = roles.processes[1].sign(&short.signing_bytes());
        let prepared = eval::prepare_self_evolution_product_selection_v1(
            qualification,
            &short,
            policy,
            request.clone(),
            bundle.clone(),
            metric_roles.to_vec(),
            evidence,
            timing,
            &candidate.dataset,
            &candidate.snapshot,
            &roles.verifier,
            micros(),
        )
        .unwrap();
        let selector = roles.evidence(
            /*index*/ 3,
            &eval::selection_signing_payload_v1(prepared.receipt()).unwrap(),
            micros(),
        );
        let early = eval::admit_self_evolution_selection_v1(
            prepared.clone(),
            &selector,
            &roles.verifier,
            micros(),
        )
        .unwrap();
        let delayed = short.expires_at + 1;
        let late_error =
            eval::admit_self_evolution_selection_v1(prepared, &selector, &roles.verifier, delayed)
                .unwrap_err();
        let expected = eval::SelfEvolutionSelectionError::Evidence(
            codex_hepta_learning_ledger::SignedEvidenceError::ValidityWindow,
        );
        assert_eq!(late_error, expected);
        assert_eq!(early.validate_at(delayed), Err(expected));
        json!({"prepared_during_binding_validity":true,"early_admission_succeeded":true,
            "binding_expires_at":short.expires_at,"delayed_verification_at":delayed,
            "late_admission_error":late_error.to_string(),"early_token_revalidation_refused":true,
            "scope":"expiry boundary control with advanced verification clock, not a future task observation"})
    } else {
        json!({"scope":"no-update has no eligible original qualification to prepare"})
    };
    // A fully signed caller metric can satisfy the compatibility comparator.
    // The same signed statement must not impersonate the sealed estimator result.
    let mut substituted = bundle.clone();
    substituted.metrics[0].candidate = eval::EvaluationIntervalV1 {
        lower: FixedQ32::from_raw(2_i64 << 32),
        upper: FixedQ32::from_raw(2_i64 << 32),
    };
    let mut changed_timing = timing.clone();
    changed_timing.observer = roles.evidence(
        /*index*/ 2,
        &eval::future_window_signing_payload_v1(&substituted, &changed_timing, 1).unwrap(),
        micros(),
    );
    let changed_evidence = eval::SignedEvaluationEvidenceV1 {
        generator_plan: evidence.generator_plan.clone(),
        evaluator_bundle: roles.evidence(
            /*index*/ 1,
            &eval::longitudinal_evaluation_signing_payload_v3(
                &substituted,
                metric_roles,
                &changed_timing,
                1,
            )
            .unwrap(),
            micros(),
        ),
    };
    let raw = eval::prepare_self_evolution_selection_v1(
        policy,
        request.clone(),
        substituted.clone(),
        metric_roles.to_vec(),
        &changed_evidence,
        &changed_timing,
        &candidate.dataset,
        &candidate.snapshot,
        &roles.verifier,
        micros(),
    )
    .unwrap();
    let error = eval::prepare_self_evolution_product_selection_v1(
        qualification,
        binding,
        policy,
        request.clone(),
        substituted,
        metric_roles.to_vec(),
        &changed_evidence,
        &changed_timing,
        &candidate.dataset,
        &candidate.snapshot,
        &roles.verifier,
        micros(),
    )
    .unwrap_err();
    assert_eq!(error, eval::SelfEvolutionSelectionError::BindingMismatch);
    let selector = roles.evidence(
        /*index*/ 3,
        &eval::selection_signing_payload_v1(raw.receipt()).unwrap(),
        micros(),
    );
    let compatibility =
        eval::admit_self_evolution_selection_v1(raw, &selector, &roles.verifier, micros()).unwrap();
    assert_eq!(
        compatibility.require_product_qualification(),
        Err(eval::SelfEvolutionSelectionError::CanonicalQualificationRequired)
    );
    save(
        &root.join("canonical-qualification-controls.json"),
        &json!({
        "seal_denials":seal_denials,"byte_binding_denials":byte_denials,"binding_lifetime":lifetime_control,
        "signed_metric_compatibility_eligible":true,"canonical_metric_substitution_error":error.to_string(),
        "compatibility_cannot_claim_product_qualification":true,
        "qualification_evidence_digest":qualification.evidence_digest.to_string(),
        "qualification_publication_digest":qualification.publication_digest.to_string()}),
    );
    compatibility
}
