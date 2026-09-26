use std::time::Duration;
use std::time::Instant;

use codex_hepta_intelligence::IntuitionQualificationEvidenceV2;
use codex_hepta_intelligence::decide_authenticated_intuition_v3;
use codex_hepta_intuition::AssignmentCommitmentV1;
use codex_hepta_intuition::AssignmentModeV1;
use codex_hepta_intuition::CalibratedActionCandidateV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibrationArtifactV1;
use codex_hepta_intuition::CandidateSetCompletenessBindingV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::CanonicalRiskRuleV1;
use codex_hepta_intuition::LearnedScorerContractV1;
use codex_hepta_intuition::OodArtifactV1;
use codex_hepta_intuition::RiskClass;
use codex_hepta_intuition::ScoringCommitmentV2;
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::canonical_completeness_evidence_payload_v1;
use codex_hepta_intuition::canonical_profile_qualification_payload_v1;
use codex_hepta_intuition::canonical_runtime_commitment_payload_v2;
use codex_hepta_intuition::canonical_scored_outputs_digest_v2;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

const SAMPLES: usize = 200;
const P99_BUDGET: Duration = Duration::from_millis(50);
const MIN_THROUGHPUT_PER_SEC: f64 = 20.0;

fn id(value: &str) -> StableId {
    StableId::new(value)
        .unwrap_or_else(|error| panic!("invalid benchmark fixture identity: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    evidence_id: &str,
    objective_digest: Digest32,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(evidence_id),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest,
        authority_epoch: principal.authority_epoch,
        issued_at: 100,
        expires_at: 200,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

struct Fixture {
    request: CalibratedDecisionRequestV1,
    profile: CanonicalPolicyProfileV1,
    scoring: ScoringCommitmentV2,
    assignment: AssignmentCommitmentV1,
    verifier: LearningEvidenceVerifierV1,
    completeness: SignedLearningEvidenceV1,
    profile_qualification: SignedLearningEvidenceV1,
    runtime: SignedLearningEvidenceV1,
}

fn fixture(candidate_count: usize) -> Result<Fixture, Box<dyn std::error::Error>> {
    let policy_digest = digest("policy:intuition-fast-v1");
    let model_digest = digest("model:intuition-fast-v1");
    let objective_digest = digest("objective:intuition-auth-fast-gate");
    let objective_class_digest = digest("objective-class:fast-gate");
    let candidates = (0..candidate_count)
        .map(|index| CalibratedActionCandidateV1 {
            candidate_id: id(&format!("candidate:{index:03}")),
            legal: true,
            hard_veto: false,
            utility: FixedQ32::from_raw(index as i64 + 1),
            calibrated_confidence: ProbabilityQ32::ONE,
            ood_score: ProbabilityQ32::ZERO,
            assignment_probability: ProbabilityQ32::ZERO,
            support_digest: digest(&format!("support:{index:03}")),
        })
        .collect::<Vec<_>>();
    let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates)?;
    let canonical_order_digest = canonical_candidate_order_digest_v1(&candidates)?;
    let calibration_artifact_digest = digest("calibration:fast-gate");
    let ood_artifact_digest = digest("ood:fast-gate");
    let request = CalibratedDecisionRequestV1 {
        decision_id: id("decision:auth-fast-gate"),
        objective_digest,
        objective_class_digest,
        state_digest: digest("state:auth-fast-gate"),
        policy_digest,
        policy_generation: 1,
        sequence: 7,
        minimum_confidence: ProbabilityQ32::ZERO,
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest("complete:fast-gate"),
            generator_digest: digest("generator:fast-gate"),
            grammar_digest: digest("grammar:fast-gate"),
            hard_filter_digest: digest("filter:fast-gate"),
            truncation_digest: digest("truncation:fast-gate"),
            candidate_set_digest,
            canonical_order_digest,
            candidate_count: u32::try_from(candidate_count)?,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: calibration_artifact_digest,
            policy_digest,
            objective_class_digest,
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            measured_ece_ppm: 0,
            subgroup_audit_digest: digest("subgroup:fast-gate"),
        },
        ood: OodArtifactV1 {
            artifact_digest: ood_artifact_digest,
            policy_digest,
            detector_digest: digest("detector:fast-gate"),
            support_digest: digest("ood-support:fast-gate"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            maximum_in_domain_score: ProbabilityQ32::ONE,
            measured_false_acceptance_ppm: 0,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    };
    let profile = CanonicalPolicyProfileV1 {
        profile_id: id("profile:auth-fast-gate"),
        policy_digest,
        objective_class_digest,
        generation: 1,
        valid_from_sequence: 1,
        expires_after_sequence: 100,
        minimum_confidence: ProbabilityQ32::ZERO,
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        maximum_in_domain_score: ProbabilityQ32::ONE,
        risk_rule: CanonicalRiskRuleV1::HighOnlySlowPath,
        scorer: LearnedScorerContractV1 {
            model_digest,
            feature_schema_digest: digest("features:fast-gate"),
            output_schema_digest: digest("outputs:fast-gate"),
            score_semantics_digest: digest("semantics:fast-gate"),
            scorer_contract_digest: digest("scorer-contract:fast-gate"),
        },
        calibration_dataset_digest: digest("cal-data:fast-gate"),
        ood_dataset_digest: digest("ood-data:fast-gate"),
        calibration_artifact_digest,
        ood_artifact_digest,
    };
    let scoring = ScoringCommitmentV2 {
        model_artifact_digest: model_digest,
        feature_snapshot_digest: digest("feature-snapshot:fast-gate"),
        feature_schema_digest: profile.scorer.feature_schema_digest,
        scorer_contract_digest: profile.scorer.scorer_contract_digest,
        scored_outputs_digest: canonical_scored_outputs_digest_v2(&request)?,
        policy_digest,
        policy_generation: 1,
    };
    let assignment = AssignmentCommitmentV1::Deterministic;

    let keys = [
        SigningKey::from_bytes(&[11; 32]),
        SigningKey::from_bytes(&[23; 32]),
        SigningKey::from_bytes(&[37; 32]),
    ];
    let scope_digest = digest("scope:intuition-auth-fast-gate");
    let principals = [
        AuthenticatedPrincipalV1 {
            principal_id: id("generator"),
            credential_chain_digest: digest("generator-credential"),
            signing_key_digest: Digest32::of_bytes(&keys[0].verifying_key().to_bytes()),
            scope_digest,
            authority_epoch: 1,
            authenticated_at: 1,
            expires_at: 1_000,
        },
        AuthenticatedPrincipalV1 {
            principal_id: id("evaluator"),
            credential_chain_digest: digest("evaluator-credential"),
            signing_key_digest: Digest32::of_bytes(&keys[1].verifying_key().to_bytes()),
            scope_digest,
            authority_epoch: 1,
            authenticated_at: 1,
            expires_at: 1_000,
        },
        AuthenticatedPrincipalV1 {
            principal_id: id("observer"),
            credential_chain_digest: digest("observer-credential"),
            signing_key_digest: Digest32::of_bytes(&keys[2].verifying_key().to_bytes()),
            scope_digest,
            authority_epoch: 1,
            authenticated_at: 1,
            expires_at: 1_000,
        },
    ];
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest,
        objective_digest,
        authority_epoch: 1,
        signers: vec![
            TrustedLearningSignerV1 {
                principal: principals[0].clone(),
                controller_id: id("controller:generator"),
                verifying_key: keys[0].verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Generator],
                revoked_at: None,
            },
            TrustedLearningSignerV1 {
                principal: principals[1].clone(),
                controller_id: id("controller:evaluator"),
                verifying_key: keys[1].verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Evaluator],
                revoked_at: None,
            },
            TrustedLearningSignerV1 {
                principal: principals[2].clone(),
                controller_id: id("controller:observer"),
                verifying_key: keys[2].verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Observer],
                revoked_at: None,
            },
        ],
    })?;

    let completeness_payload = canonical_completeness_evidence_payload_v1(&request)?;
    let profile_payload = canonical_profile_qualification_payload_v1(&profile)?;
    let runtime_payload =
        canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)?;
    let completeness = sign(
        &verifier,
        &principals[0],
        &keys[0],
        LearningEvidenceRoleV1::Generator,
        "evidence:complete",
        objective_digest,
        &completeness_payload,
    );
    let profile_qualification = sign(
        &verifier,
        &principals[1],
        &keys[1],
        LearningEvidenceRoleV1::Evaluator,
        "evidence:profile",
        objective_digest,
        &profile_payload,
    );
    let runtime = sign(
        &verifier,
        &principals[2],
        &keys[2],
        LearningEvidenceRoleV1::Observer,
        "evidence:runtime",
        objective_digest,
        &runtime_payload,
    );

    Ok(Fixture {
        request,
        profile,
        scoring,
        assignment,
        verifier,
        completeness,
        profile_qualification,
        runtime,
    })
}

fn percentile(sorted: &[Duration], numerator: usize) -> Duration {
    let index = ((sorted.len() - 1) * numerator) / 100;
    sorted[index]
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("path,candidates,p50_us,p95_us,p99_us,throughput_per_sec");
    for count in [1usize, 16, 64, 128] {
        let fixture = fixture(count)?;
        for _ in 0..16 {
            let _ = decide_authenticated_intuition_v3(
                fixture.request.clone(),
                fixture.profile.clone(),
                fixture.scoring.clone(),
                fixture.assignment.clone(),
                IntuitionQualificationEvidenceV2 {
                    completeness: &fixture.completeness,
                    profile_qualification: &fixture.profile_qualification,
                    runtime: &fixture.runtime,
                },
                &fixture.verifier,
                150,
            )?;
        }

        let wall_start = Instant::now();
        let mut samples = Vec::with_capacity(SAMPLES);
        for _ in 0..SAMPLES {
            let start = Instant::now();
            let receipt = decide_authenticated_intuition_v3(
                fixture.request.clone(),
                fixture.profile.clone(),
                fixture.scoring.clone(),
                fixture.assignment.clone(),
                IntuitionQualificationEvidenceV2 {
                    completeness: &fixture.completeness,
                    profile_qualification: &fixture.profile_qualification,
                    runtime: &fixture.runtime,
                },
                &fixture.verifier,
                150,
            )?;
            std::hint::black_box(receipt);
            samples.push(start.elapsed());
        }
        let wall = wall_start.elapsed();
        samples.sort_unstable();
        let p50 = percentile(&samples, 50);
        let p95 = percentile(&samples, 95);
        let p99 = percentile(&samples, 99);
        let throughput = SAMPLES as f64 / wall.as_secs_f64();
        println!(
            "authenticated,{count},{},{},{},{throughput:.2}",
            p50.as_micros(),
            p95.as_micros(),
            p99.as_micros()
        );
        assert!(
            p99 <= P99_BUDGET,
            "candidate_count={count} authenticated p99={p99:?} exceeds {P99_BUDGET:?}"
        );
        assert!(
            throughput >= MIN_THROUGHPUT_PER_SEC,
            "candidate_count={count} authenticated throughput={throughput}"
        );
    }
    Ok(())
}
