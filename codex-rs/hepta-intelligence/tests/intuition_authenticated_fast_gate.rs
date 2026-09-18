use std::hint::black_box;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_intelligence::IntuitionQualificationEvidenceV1;
use codex_hepta_intelligence::decide_authenticated_intuition_v1;
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
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::canonical_completeness_evidence_payload_v1;
use codex_hepta_intuition::canonical_profile_qualification_evidence_payload_v1;
use codex_hepta_intuition::canonical_random_assignment_evidence_payload_v1;
use codex_hepta_intuition::canonical_scoring_evidence_payload_v1;
use codex_hepta_intuition::scoring_commitment_for_request_v1;
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

struct Gate {
    candidates: usize,
    iterations: usize,
    p99_budget: Duration,
    min_throughput_per_second: f64,
}

const GATES: [Gate; 4] = [
    Gate {
        candidates: 1,
        iterations: 200,
        p99_budget: Duration::from_millis(50),
        min_throughput_per_second: 10.0,
    },
    Gate {
        candidates: 16,
        iterations: 160,
        p99_budget: Duration::from_millis(70),
        min_throughput_per_second: 10.0,
    },
    Gate {
        candidates: 64,
        iterations: 120,
        p99_budget: Duration::from_millis(100),
        min_throughput_per_second: 8.0,
    },
    Gate {
        candidates: 128,
        iterations: 80,
        p99_budget: Duration::from_millis(150),
        min_throughput_per_second: 6.0,
    },
];

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
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

#[test]
fn authenticated_fast_policy_latency_gate() {
    eprintln!("mode,candidates,iterations,p50_us,p95_us,p99_us,throughput_per_s");
    for gate in GATES {
        run_gate(gate);
    }
}

fn run_gate(gate: Gate) {
    let objective_digest = digest("benchmark:objective");
    let policy_digest = digest("benchmark:policy");
    let model_artifact_digest = digest("benchmark:model-artifact");
    let objective_class_digest = digest("benchmark:objective-class");
    let calibration_artifact_digest = digest("benchmark:calibration");
    let calibration_audit_digest = digest("benchmark:calibration-audit");
    let ood_artifact_digest = digest("benchmark:ood");
    let ood_detector_digest = digest("benchmark:ood-detector");
    let ood_support_digest = digest("benchmark:ood-support");

    let share = ProbabilityQ32::from_raw(
        ProbabilityQ32::ONE.raw() / u64::try_from(gate.candidates).unwrap(),
    )
    .unwrap();
    let candidates = (0..gate.candidates)
        .map(|index| CalibratedActionCandidateV1 {
            candidate_id: id(&format!("candidate:{index:03}")),
            legal: true,
            hard_veto: false,
            utility: FixedQ32::from_raw(i64::try_from(index).unwrap()),
            calibrated_confidence: ProbabilityQ32::ONE,
            ood_score: ProbabilityQ32::ZERO,
            assignment_probability: share,
            support_digest: digest(&format!("support:{index:03}")),
        })
        .collect::<Vec<_>>();
    let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates).unwrap();
    let canonical_order_digest = canonical_candidate_order_digest_v1(&candidates).unwrap();

    let request = CalibratedDecisionRequestV1 {
        decision_id: id("benchmark:decision"),
        objective_digest,
        objective_class_digest,
        state_digest: digest("benchmark:state"),
        policy_digest,
        policy_generation: 7,
        sequence: 11,
        minimum_confidence: ProbabilityQ32::ZERO,
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest("benchmark:complete"),
            generator_digest: digest("benchmark:generator"),
            grammar_digest: digest("benchmark:grammar"),
            hard_filter_digest: digest("benchmark:filter"),
            truncation_digest: digest("benchmark:no-truncation"),
            candidate_set_digest,
            canonical_order_digest,
            candidate_count: u32::try_from(gate.candidates).unwrap(),
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: calibration_artifact_digest,
            policy_digest,
            objective_class_digest,
            generation: 7,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            measured_ece_ppm: 0,
            subgroup_audit_digest: calibration_audit_digest,
        },
        ood: OodArtifactV1 {
            artifact_digest: ood_artifact_digest,
            policy_digest,
            detector_digest: ood_detector_digest,
            support_digest: ood_support_digest,
            generation: 7,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            maximum_in_domain_score: ProbabilityQ32::ONE,
            measured_false_acceptance_ppm: 0,
        },
        assignment: AssignmentModeV1::CounterBased {
            random_stream_digest: digest("benchmark:rng-stream"),
            draw: ProbabilityQ32::ZERO,
            abstain_probability: ProbabilityQ32::ZERO,
        },
        candidates,
    };

    let profile = CanonicalPolicyProfileV1 {
        profile_id: id("benchmark:profile"),
        policy_digest,
        objective_class_digest,
        generation: 7,
        valid_from_sequence: 1,
        expires_after_sequence: 100,
        minimum_confidence: ProbabilityQ32::ZERO,
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        maximum_in_domain_score: ProbabilityQ32::ONE,
        risk_rule: CanonicalRiskRuleV1::HighOnlySlowPath,
        scorer: LearnedScorerContractV1 {
            model_artifact_digest,
            feature_schema_digest: digest("benchmark:feature-schema"),
            output_schema_digest: digest("benchmark:output-schema"),
            score_semantics_digest: digest("benchmark:score-semantics"),
            scorer_contract_digest: digest("benchmark:scorer-contract"),
        },
        calibration_dataset_digest: digest("benchmark:calibration-data"),
        ood_dataset_digest: digest("benchmark:ood-data"),
        calibration_artifact_digest,
        calibration_measured_ece_ppm: 0,
        calibration_subgroup_audit_digest: calibration_audit_digest,
        calibration_valid_from_sequence: 1,
        calibration_expires_after_sequence: 100,
        ood_artifact_digest,
        ood_measured_false_acceptance_ppm: 0,
        ood_detector_digest,
        ood_support_digest,
        ood_valid_from_sequence: 1,
        ood_expires_after_sequence: 100,
    };
    let scoring = scoring_commitment_for_request_v1(
        &request,
        &profile,
        digest("benchmark:feature-snapshot"),
    )
    .unwrap();

    let keys = [
        SigningKey::from_bytes(&[11; 32]),
        SigningKey::from_bytes(&[13; 32]),
        SigningKey::from_bytes(&[17; 32]),
        SigningKey::from_bytes(&[19; 32]),
    ];
    let roles = [
        LearningEvidenceRoleV1::Generator,
        LearningEvidenceRoleV1::Scorer,
        LearningEvidenceRoleV1::Evaluator,
        LearningEvidenceRoleV1::RandomSource,
    ];
    let principal_names = [
        "benchmark:generator",
        "benchmark:scorer",
        "benchmark:evaluator",
        "benchmark:random-source",
    ];
    let principals = (0..4)
        .map(|index| AuthenticatedPrincipalV1 {
            principal_id: id(principal_names[index]),
            credential_chain_digest: digest(&format!("benchmark:credential:{index}")),
            signing_key_digest: Digest32::of_bytes(&keys[index].verifying_key().to_bytes()),
            scope_digest: digest("benchmark:scope"),
            authority_epoch: 3,
            authenticated_at: 50,
            expires_at: 250,
        })
        .collect::<Vec<_>>();
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("benchmark:scope"),
        objective_digest,
        authority_epoch: 3,
        signers: (0..4)
            .map(|index| TrustedLearningSignerV1 {
                principal: principals[index].clone(),
                controller_id: id(&format!("benchmark:controller:{index}")),
                verifying_key: keys[index].verifying_key().to_bytes(),
                roles: vec![roles[index]],
                revoked_at: None,
            })
            .collect(),
    })
    .unwrap();

    let completeness_payload = canonical_completeness_evidence_payload_v1(&request).unwrap();
    let scoring_payload = canonical_scoring_evidence_payload_v1(&scoring).unwrap();
    let profile_payload =
        canonical_profile_qualification_evidence_payload_v1(&profile).unwrap();
    let assignment_payload = canonical_random_assignment_evidence_payload_v1(&request)
        .unwrap()
        .unwrap();

    let signed = [
        sign(
            &verifier,
            &principals[0],
            &keys[0],
            roles[0],
            "benchmark:evidence:generator",
            objective_digest,
            &completeness_payload,
        ),
        sign(
            &verifier,
            &principals[1],
            &keys[1],
            roles[1],
            "benchmark:evidence:scorer",
            objective_digest,
            &scoring_payload,
        ),
        sign(
            &verifier,
            &principals[2],
            &keys[2],
            roles[2],
            "benchmark:evidence:evaluator",
            objective_digest,
            &profile_payload,
        ),
        sign(
            &verifier,
            &principals[3],
            &keys[3],
            roles[3],
            "benchmark:evidence:random-source",
            objective_digest,
            &assignment_payload,
        ),
    ];

    for _ in 0..16 {
        black_box(
            decide_authenticated_intuition_v1(
                request.clone(),
                profile.clone(),
                scoring.clone(),
                IntuitionQualificationEvidenceV1 {
                    completeness: &signed[0],
                    scoring: &signed[1],
                    profile_qualification: &signed[2],
                    assignment: Some(&signed[3]),
                },
                &verifier,
                150,
            )
            .unwrap(),
        );
    }

    let wall_start = Instant::now();
    let mut samples = Vec::with_capacity(gate.iterations);
    for _ in 0..gate.iterations {
        let started = Instant::now();
        let receipt = decide_authenticated_intuition_v1(
            request.clone(),
            profile.clone(),
            scoring.clone(),
            IntuitionQualificationEvidenceV1 {
                completeness: &signed[0],
                scoring: &signed[1],
                profile_qualification: &signed[2],
                assignment: Some(&signed[3]),
            },
            &verifier,
            150,
        )
        .unwrap();
        black_box(receipt.authentication_digest);
        samples.push(started.elapsed());
    }
    let wall = wall_start.elapsed();
    samples.sort_unstable();
    let p50 = percentile(&samples, 50);
    let p95 = percentile(&samples, 95);
    let p99 = percentile(&samples, 99);
    let throughput = gate.iterations as f64 / wall.as_secs_f64();

    eprintln!(
        "authenticated_e2e,{},{},{},{},{},{throughput:.2}",
        gate.candidates,
        gate.iterations,
        p50.as_micros(),
        p95.as_micros(),
        p99.as_micros()
    );
    assert!(
        p99 <= gate.p99_budget,
        "candidate_count={} authenticated p99={p99:?} exceeds {:?}",
        gate.candidates,
        gate.p99_budget
    );
    assert!(
        throughput >= gate.min_throughput_per_second,
        "candidate_count={} authenticated throughput={throughput} below {}",
        gate.candidates,
        gate.min_throughput_per_second
    );
}

fn percentile(sorted: &[Duration], percentile: usize) -> Duration {
    let index = ((sorted.len() - 1) * percentile + 99) / 100;
    sorted[index.min(sorted.len() - 1)]
}
