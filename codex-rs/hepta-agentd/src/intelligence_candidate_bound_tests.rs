//! Raw candidate bounds precede signed-owner reads and worker admission.

use super::*;
use codex_hepta_intuition::CanonicalRiskRuleV1;
use codex_hepta_intuition::LearnedScorerContractV1;

#[derive(Clone, Copy)]
enum CandidateOwner {
    Canonical,
    Intuition,
}

fn invalid_profile(request: &CalibratedDecisionRequestV1) -> CanonicalPolicyProfileV1 {
    CanonicalPolicyProfileV1 {
        profile_id: request.decision_id.clone(),
        policy_digest: Digest32::ZERO,
        objective_class_digest: Digest32::ZERO,
        generation: 0,
        valid_from_sequence: 0,
        expires_after_sequence: 0,
        minimum_confidence: request.minimum_confidence,
        maximum_ece_ppm: 0,
        maximum_ood_false_acceptance_ppm: 0,
        maximum_in_domain_score: request.ood.maximum_in_domain_score,
        risk_rule: CanonicalRiskRuleV1::AlwaysSlowPath,
        scorer: LearnedScorerContractV1 {
            model_digest: Digest32::ZERO,
            feature_schema_digest: Digest32::ZERO,
            output_schema_digest: Digest32::ZERO,
            score_semantics_digest: Digest32::ZERO,
            scorer_contract_digest: Digest32::ZERO,
        },
        calibration_dataset_digest: Digest32::ZERO,
        ood_dataset_digest: Digest32::ZERO,
        calibration_artifact_digest: Digest32::ZERO,
        ood_artifact_digest: Digest32::ZERO,
    }
}

#[tokio::test]
#[allow(
    clippy::expect_used,
    reason = "Oversized raw input must reject before missing authority or invalid profile data."
)]
async fn oversized_owner_candidates_reject_before_signed_inputs_or_worker_use() {
    let directory = tempfile::tempdir().expect("directory");
    let runner = AgentdIntelligenceProductRunnerV1::new(
        directory.path().join("missing-authority"),
        authority_verifier(),
    )
    .expect("runner");
    for maximum in [
        crate::intelligence_ingress::MAX_COMPATIBILITY_INTUITION_CANDIDATES,
        crate::MAX_PRODUCT_INTUITION_CANDIDATES,
    ] {
        for owner in [CandidateOwner::Canonical, CandidateOwner::Intuition] {
            let mut value = fixture();
            match owner {
                CandidateOwner::Canonical => {
                    let candidate = value.request.legal_candidates.candidates[0].clone();
                    value
                        .request
                        .legal_candidates
                        .candidates
                        .resize(maximum + 1, candidate);
                }
                CandidateOwner::Intuition => {
                    let candidate = value.inputs.intuition_request.candidates[0].clone();
                    value
                        .inputs
                        .intuition_request
                        .candidates
                        .resize(maximum + 1, candidate);
                }
            }
            let mode = if maximum == crate::MAX_PRODUCT_INTUITION_CANDIDATES {
                AgentdIntuitionComputationV1::Product(Box::new(invalid_profile(
                    &value.inputs.intuition_request,
                )))
            } else {
                AgentdIntuitionComputationV1::Compatibility
            };
            assert!(matches!(
                runner
                    .prepare_for_composition_with_intuition(
                        product_test_coordinator().composition(),
                        value.request,
                        value.inputs,
                        mode,
                    )
                    .await,
                Err(AgentdIntelligenceProductError::Canonical(
                    CanonicalIntelligenceError::InvalidCandidateSet("candidate count")
                ))
            ));
        }
    }
}

#[tokio::test]
#[allow(
    clippy::expect_used,
    reason = "Maximum valid counts must reach the existing worker-capacity gate."
)]
async fn maximum_candidate_counts_preserve_compatibility_and_product_capacity() {
    let directory = tempfile::tempdir().expect("directory");
    let runner = AgentdIntelligenceProductRunnerV1::new(
        directory.path().join("missing-authority"),
        authority_verifier(),
    )
    .expect("runner");
    let _occupied = runner
        .worker_slots
        .clone()
        .acquire_many_owned(MAX_CANONICAL_OWNER_WORKERS as u32)
        .await
        .expect("reserve all worker capacity");
    for maximum in [
        crate::intelligence_ingress::MAX_COMPATIBILITY_INTUITION_CANDIDATES,
        crate::MAX_PRODUCT_INTUITION_CANDIDATES,
    ] {
        let mut value = fixture();
        let legal = value.request.legal_candidates.candidates[0].clone();
        let intuition = value.inputs.intuition_request.candidates[0].clone();
        value
            .request
            .legal_candidates
            .candidates
            .resize(maximum, legal);
        value
            .inputs
            .intuition_request
            .candidates
            .resize(maximum, intuition);
        let mode = if maximum == crate::MAX_PRODUCT_INTUITION_CANDIDATES {
            AgentdIntuitionComputationV1::Product(Box::new(invalid_profile(
                &value.inputs.intuition_request,
            )))
        } else {
            AgentdIntuitionComputationV1::Compatibility
        };
        assert!(matches!(
            runner
                .prepare_for_composition_with_intuition(
                    product_test_coordinator().composition(),
                    value.request,
                    value.inputs,
                    mode,
                )
                .await,
            Err(AgentdIntelligenceProductError::Busy)
        ));
    }
}
