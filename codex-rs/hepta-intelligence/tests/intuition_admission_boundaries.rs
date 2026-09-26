use codex_hepta_intelligence::AuthenticatedIntuitionDecisionV2;
use codex_hepta_intelligence::IntuitionQualificationError;
use codex_hepta_intelligence::IntuitionQualificationEvidenceV2;
use codex_hepta_intelligence::decide_authenticated_intuition_v2;
use codex_hepta_intuition::AssignmentCommitmentV1;
use codex_hepta_intuition::AssignmentModeV1;
use codex_hepta_intuition::CalibratedActionCandidateV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedError;
use codex_hepta_intuition::CalibrationArtifactV1;
use codex_hepta_intuition::CandidateSetCompletenessBindingV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::CanonicalRiskRuleV1;
use codex_hepta_intuition::LearnedScorerContractV1;
use codex_hepta_intuition::OodArtifactV1;
use codex_hepta_intuition::QualifiedCalibratedError;
use codex_hepta_intuition::RiskClass;
use codex_hepta_intuition::ScoringCommitmentV1;
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::canonical_completeness_evidence_payload_v1;
use codex_hepta_intuition::canonical_profile_qualification_payload_v1;
use codex_hepta_intuition::canonical_runtime_commitment_payload_v1;
use codex_hepta_intuition::canonical_scored_outputs_digest_v1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::error::Error;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

fn id(value: &str) -> TestResult<StableId> {
    Ok(StableId::new(value)?)
}

fn d(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct Fixture {
    request: CalibratedDecisionRequestV1,
    profile: CanonicalPolicyProfileV1,
    scoring: ScoringCommitmentV1,
    verifier: LearningEvidenceVerifierV1,
    signed: [SignedLearningEvidenceV1; 3],
}

impl Fixture {
    fn decide(self) -> Result<AuthenticatedIntuitionDecisionV2, IntuitionQualificationError> {
        decide_authenticated_intuition_v2(
            self.request,
            self.profile,
            self.scoring,
            AssignmentCommitmentV1::Deterministic,
            IntuitionQualificationEvidenceV2 {
                completeness: &self.signed[0],
                profile_qualification: &self.signed[1],
                runtime: &self.signed[2],
            },
            &self.verifier,
            150,
        )
    }
}

fn fixture(evidence_objective: Digest32, observer_controller: &str) -> TestResult<Fixture> {
    let candidates = vec![CalibratedActionCandidateV1 {
        candidate_id: id("candidate")?,
        legal: true,
        hard_veto: false,
        utility: FixedQ32::ONE,
        calibrated_confidence: ProbabilityQ32::ONE,
        ood_score: ProbabilityQ32::ZERO,
        assignment_probability: ProbabilityQ32::ZERO,
        support_digest: d("support"),
    }];
    let set = canonical_candidate_set_digest_v1(&candidates)?;
    let order = canonical_candidate_order_digest_v1(&candidates)?;
    let request = CalibratedDecisionRequestV1 {
        decision_id: id("decision")?,
        objective_digest: d("objective"),
        objective_class_digest: d("class"),
        state_digest: d("state"),
        policy_digest: d("policy"),
        policy_generation: 1,
        sequence: 1,
        minimum_confidence: ProbabilityQ32::ZERO,
        maximum_ece_ppm: 0,
        maximum_ood_false_acceptance_ppm: 0,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: d("complete"),
            generator_digest: d("generator"),
            grammar_digest: d("grammar"),
            hard_filter_digest: d("filter"),
            truncation_digest: d("truncation"),
            candidate_set_digest: set,
            canonical_order_digest: order,
            candidate_count: 1,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: d("calibration"),
            policy_digest: d("policy"),
            objective_class_digest: d("class"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 10,
            measured_ece_ppm: 0,
            subgroup_audit_digest: d("audit"),
        },
        ood: OodArtifactV1 {
            artifact_digest: d("ood"),
            policy_digest: d("policy"),
            detector_digest: d("detector"),
            support_digest: d("support"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 10,
            maximum_in_domain_score: ProbabilityQ32::ONE,
            measured_false_acceptance_ppm: 0,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    };
    let profile = CanonicalPolicyProfileV1 {
        profile_id: id("profile")?,
        policy_digest: d("policy"),
        objective_class_digest: d("class"),
        generation: 1,
        valid_from_sequence: 1,
        expires_after_sequence: 10,
        minimum_confidence: ProbabilityQ32::ZERO,
        maximum_ece_ppm: 0,
        maximum_ood_false_acceptance_ppm: 0,
        maximum_in_domain_score: ProbabilityQ32::ONE,
        risk_rule: CanonicalRiskRuleV1::HighOnlySlowPath,
        scorer: LearnedScorerContractV1 {
            model_digest: d("model"),
            feature_schema_digest: d("features"),
            output_schema_digest: d("outputs"),
            score_semantics_digest: d("semantics"),
            scorer_contract_digest: d("scorer"),
        },
        calibration_dataset_digest: d("calibration-data"),
        ood_dataset_digest: d("ood-data"),
        calibration_artifact_digest: d("calibration"),
        ood_artifact_digest: d("ood"),
    };
    let scoring = ScoringCommitmentV1 {
        model_artifact_digest: profile.scorer.model_digest,
        feature_snapshot_digest: d("feature-snapshot"),
        feature_schema_digest: profile.scorer.feature_schema_digest,
        scorer_contract_digest: profile.scorer.scorer_contract_digest,
        candidate_set_digest: set,
        scored_outputs_digest: canonical_scored_outputs_digest_v1(&request)?,
        policy_digest: request.policy_digest,
        policy_generation: request.policy_generation,
    };
    let keys = [
        SigningKey::from_bytes(&[31; 32]),
        SigningKey::from_bytes(&[47; 32]),
        SigningKey::from_bytes(&[59; 32]),
    ];
    let roles = [
        LearningEvidenceRoleV1::Generator,
        LearningEvidenceRoleV1::Evaluator,
        LearningEvidenceRoleV1::Observer,
    ];
    let controllers = [
        id("generator-controller")?,
        id("evaluator-controller")?,
        id(observer_controller)?,
    ];
    let principal_ids = [id("principal-0")?, id("principal-1")?, id("principal-2")?];
    let evidence_ids = [id("evidence-0")?, id("evidence-1")?, id("evidence-2")?];
    let principals: [AuthenticatedPrincipalV1; 3] =
        std::array::from_fn(|index| AuthenticatedPrincipalV1 {
            principal_id: principal_ids[index].clone(),
            credential_chain_digest: d(&format!("chain-{index}")),
            signing_key_digest: Digest32::of_bytes(&keys[index].verifying_key().to_bytes()),
            scope_digest: d("scope"),
            authority_epoch: 1,
            authenticated_at: 50,
            expires_at: 250,
        });
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: d("scope"),
        objective_digest: evidence_objective,
        authority_epoch: 1,
        signers: (0..3)
            .map(|index| TrustedLearningSignerV1 {
                principal: principals[index].clone(),
                controller_id: controllers[index].clone(),
                verifying_key: keys[index].verifying_key().to_bytes(),
                roles: vec![roles[index]],
                revoked_at: None,
            })
            .collect(),
    })?;
    let payloads = [
        canonical_completeness_evidence_payload_v1(&request)?,
        canonical_profile_qualification_payload_v1(&profile)?,
        canonical_runtime_commitment_payload_v1(
            &request,
            &profile,
            &scoring,
            &AssignmentCommitmentV1::Deterministic,
        )?,
    ];
    let signed = std::array::from_fn(|index| {
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: evidence_ids[index].clone(),
            principal_id: principals[index].principal_id.clone(),
            role: roles[index],
            trust_digest: verifier.trust_digest(),
            scope_digest: d("scope"),
            objective_digest: evidence_objective,
            authority_epoch: 1,
            issued_at: 100,
            expires_at: 200,
            payload_digest: Digest32::of_bytes(&payloads[index]),
            signature: [0; 64],
        };
        evidence.signature = keys[index].sign(&evidence.signing_bytes()).to_bytes();
        evidence
    });
    // Fixture failures fail the test. Negative cases must reach admission with
    // independently verified signatures, not accidentally invalid evidence.
    for (index, evidence) in signed.iter().enumerate() {
        verifier.verify(roles[index], evidence, &payloads[index], 150)?;
    }
    Ok(Fixture {
        request,
        profile,
        scoring,
        verifier,
        signed,
    })
}

#[test]
fn independent_same_objective_evidence_still_succeeds() -> TestResult {
    assert!(
        fixture(d("objective"), "observer-controller")?
            .decide()
            .is_ok()
    );
    Ok(())
}

#[test]
fn valid_signatures_for_another_objective_are_rejected() -> TestResult {
    assert_eq!(
        fixture(d("different-objective"), "observer-controller")?.decide(),
        Err(IntuitionQualificationError::Evidence(
            SignedEvidenceError::ContextMismatch
        ))
    );
    Ok(())
}

#[test]
fn distinct_evaluator_observer_keys_do_not_hide_controller_collision() -> TestResult {
    assert_eq!(
        fixture(d("objective"), "evaluator-controller")?.decide(),
        Err(IntuitionQualificationError::Evidence(
            SignedEvidenceError::ControllerCollision
        ))
    );
    Ok(())
}

#[test]
fn candidate_limit_is_checked_before_signature_or_payload_work() -> TestResult {
    let mut value = fixture(d("objective"), "observer-controller")?;
    value.request.candidates = vec![value.request.candidates[0].clone(); 129];
    value.signed[0].signature = [0; 64];
    assert_eq!(
        value.decide(),
        Err(IntuitionQualificationError::Policy(
            QualifiedCalibratedError::Policy(CalibratedError::CandidateCountOutOfRange)
        ))
    );
    Ok(())
}
