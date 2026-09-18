use std::alloc::GlobalAlloc;
use std::alloc::Layout;
use std::alloc::System;
use std::hint::black_box;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_intelligence::IntuitionQualificationEvidenceV2;
use codex_hepta_intelligence::decide_authenticated_intuition_v2;
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
use codex_hepta_intuition::ScoringCommitmentV1;
use codex_hepta_intuition::canonical_assignment_evidence_payload_v1;
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::canonical_completeness_evidence_payload_v1;
use codex_hepta_intuition::canonical_decision_request_evidence_payload_v1;
use codex_hepta_intuition::canonical_profile_qualification_evidence_payload_v1;
use codex_hepta_intuition::canonical_scored_candidates_digest_v1;
use codex_hepta_intuition::canonical_scoring_evidence_payload_v1;
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

struct CountingAllocator;

static ALLOCATION_COUNT: AtomicU64 = AtomicU64::new(0);
static ALLOCATION_BYTES: AtomicU64 = AtomicU64::new(0);

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        ALLOCATION_COUNT.fetch_add(1, Ordering::Relaxed);
        ALLOCATION_BYTES.fetch_add(layout.size() as u64, Ordering::Relaxed);
        // SAFETY: delegation preserves the exact layout supplied by Rust.
        unsafe { System.alloc(layout) }
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        ALLOCATION_COUNT.fetch_add(1, Ordering::Relaxed);
        ALLOCATION_BYTES.fetch_add(layout.size() as u64, Ordering::Relaxed);
        // SAFETY: delegation preserves the exact layout supplied by Rust.
        unsafe { System.alloc_zeroed(layout) }
    }

    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        ALLOCATION_COUNT.fetch_add(1, Ordering::Relaxed);
        ALLOCATION_BYTES.fetch_add(new_size as u64, Ordering::Relaxed);
        // SAFETY: arguments are delegated to the system allocator unchanged.
        unsafe { System.realloc(ptr, layout, new_size) }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        // SAFETY: arguments originate from the delegated system allocator.
        unsafe { System.dealloc(ptr, layout) }
    }
}

#[global_allocator]
static GLOBAL: CountingAllocator = CountingAllocator;

struct Gate {
    candidates: usize,
    iterations: usize,
    p99_ns: u64,
    min_throughput_per_second: u64,
    max_allocations: u64,
    max_allocation_bytes: u64,
}

const GATES: [Gate; 4] = [
    Gate {
        candidates: 1,
        iterations: 200,
        p99_ns: 50_000_000,
        min_throughput_per_second: 20,
        max_allocations: 512,
        max_allocation_bytes: 256 * 1024,
    },
    Gate {
        candidates: 16,
        iterations: 150,
        p99_ns: 60_000_000,
        min_throughput_per_second: 15,
        max_allocations: 1_024,
        max_allocation_bytes: 512 * 1024,
    },
    Gate {
        candidates: 64,
        iterations: 100,
        p99_ns: 80_000_000,
        min_throughput_per_second: 10,
        max_allocations: 4_096,
        max_allocation_bytes: 2 * 1024 * 1024,
    },
    Gate {
        candidates: 128,
        iterations: 75,
        p99_ns: 120_000_000,
        min_throughput_per_second: 5,
        max_allocations: 8_192,
        max_allocation_bytes: 4 * 1024 * 1024,
    },
];

struct Fixture {
    request: CalibratedDecisionRequestV1,
    profile: CanonicalPolicyProfileV1,
    scoring: ScoringCommitmentV1,
    verifier: LearningEvidenceVerifierV1,
    completeness: SignedLearningEvidenceV1,
    profile_qualification: SignedLearningEvidenceV1,
    decision_request: SignedLearningEvidenceV1,
    scoring_evidence: SignedLearningEvidenceV1,
    assignment: SignedLearningEvidenceV1,
}

fn main() {
    println!(
        "candidates,iterations,p50_ns,p95_ns,p99_ns,throughput_per_s,allocations_per_decision,allocation_bytes_per_decision"
    );
    for gate in GATES {
        run_gate(gate);
    }
}

fn run_gate(gate: Gate) {
    let fixture = fixture(gate.candidates);
    for _ in 0..16 {
        let receipt = decide(
            fixture.request.clone(),
            fixture.profile.clone(),
            fixture.scoring.clone(),
            &fixture,
        );
        black_box(receipt.authentication_digest);
    }

    let mut latencies = Vec::with_capacity(gate.iterations);
    let mut allocation_count = 0_u64;
    let mut allocation_bytes = 0_u64;
    for _ in 0..gate.iterations {
        let request = fixture.request.clone();
        let profile = fixture.profile.clone();
        let scoring = fixture.scoring.clone();
        let count_before = ALLOCATION_COUNT.load(Ordering::Relaxed);
        let bytes_before = ALLOCATION_BYTES.load(Ordering::Relaxed);
        let started = Instant::now();
        let receipt = decide(request, profile, scoring, &fixture);
        let elapsed = started.elapsed();
        let count_after = ALLOCATION_COUNT.load(Ordering::Relaxed);
        let bytes_after = ALLOCATION_BYTES.load(Ordering::Relaxed);
        allocation_count += count_after - count_before;
        allocation_bytes += bytes_after - bytes_before;
        black_box(receipt.authentication_digest);
        latencies.push(u64::try_from(elapsed.as_nanos()).unwrap_or(u64::MAX));
    }
    latencies.sort_unstable();
    let p50 = percentile(&latencies, 50);
    let p95 = percentile(&latencies, 95);
    let p99 = percentile(&latencies, 99);
    let total_ns = latencies.iter().map(|value| u128::from(*value)).sum::<u128>();
    let throughput = if total_ns == 0 {
        u64::MAX
    } else {
        u64::try_from((gate.iterations as u128 * 1_000_000_000) / total_ns).unwrap_or(u64::MAX)
    };
    let allocations_per_decision = allocation_count / gate.iterations as u64;
    let allocation_bytes_per_decision = allocation_bytes / gate.iterations as u64;

    println!(
        "{},{},{},{},{},{},{},{}",
        gate.candidates,
        gate.iterations,
        p50,
        p95,
        p99,
        throughput,
        allocations_per_decision,
        allocation_bytes_per_decision
    );

    assert!(
        p99 <= gate.p99_ns,
        "{} candidates authenticated p99={}ns exceeds {}ns",
        gate.candidates,
        p99,
        gate.p99_ns
    );
    assert!(
        throughput >= gate.min_throughput_per_second,
        "{} candidates authenticated throughput={} below {}",
        gate.candidates,
        throughput,
        gate.min_throughput_per_second
    );
    assert!(
        allocations_per_decision <= gate.max_allocations,
        "{} candidates authenticated allocations={} exceeds {}",
        gate.candidates,
        allocations_per_decision,
        gate.max_allocations
    );
    assert!(
        allocation_bytes_per_decision <= gate.max_allocation_bytes,
        "{} candidates authenticated allocation bytes={} exceeds {}",
        gate.candidates,
        allocation_bytes_per_decision,
        gate.max_allocation_bytes
    );
}

fn decide(
    request: CalibratedDecisionRequestV1,
    profile: CanonicalPolicyProfileV1,
    scoring: ScoringCommitmentV1,
    fixture: &Fixture,
) -> codex_hepta_intelligence::AuthenticatedIntuitionDecisionV2 {
    decide_authenticated_intuition_v2(
        request,
        profile,
        scoring,
        IntuitionQualificationEvidenceV2 {
            completeness: &fixture.completeness,
            profile_qualification: &fixture.profile_qualification,
            decision_request: &fixture.decision_request,
            scoring: &fixture.scoring_evidence,
            assignment: Some(&fixture.assignment),
        },
        &fixture.verifier,
        150,
    )
    .expect("authenticated intuition decision")
}

fn percentile(values: &[u64], percentile: usize) -> u64 {
    let index = ((values.len() - 1) * percentile + 99) / 100;
    values[index.min(values.len() - 1)]
}

fn fixture(candidate_count: usize) -> Fixture {
    let policy_digest = digest("e2e-policy");
    let model_artifact_digest = digest("e2e-model-artifact");
    let calibration_artifact_digest = digest("e2e-calibration");
    let ood_artifact_digest = digest("e2e-ood");
    let objective_digest = digest("e2e-objective");
    let objective_class_digest = digest("e2e-objective-class");
    let feature_schema_digest = digest("e2e-feature-schema");
    let scorer_contract_digest = digest("e2e-scorer-contract");

    let candidates = (0..candidate_count)
        .map(|index| CalibratedActionCandidateV1 {
            candidate_id: id(&format!("candidate:{index:03}")),
            legal: true,
            hard_veto: false,
            utility: FixedQ32::from_raw(i64::try_from(index).expect("bounded candidate index")),
            calibrated_confidence: ProbabilityQ32::ONE,
            ood_score: ProbabilityQ32::ZERO,
            assignment_probability: if index == 0 {
                ProbabilityQ32::ONE
            } else {
                ProbabilityQ32::ZERO
            },
            support_digest: digest(&format!("support:{index:03}")),
        })
        .collect::<Vec<_>>();
    let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates).expect("candidate set");
    let canonical_order_digest =
        canonical_candidate_order_digest_v1(&candidates).expect("candidate order");

    let request = CalibratedDecisionRequestV1 {
        decision_id: id("e2e-decision"),
        objective_digest,
        objective_class_digest,
        state_digest: digest("e2e-state"),
        policy_digest,
        policy_generation: 1,
        sequence: 7,
        minimum_confidence: probability_ppm(500_000),
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest("e2e-completeness"),
            generator_digest: digest("e2e-generator"),
            grammar_digest: digest("e2e-grammar"),
            hard_filter_digest: digest("e2e-filter"),
            truncation_digest: digest("e2e-truncation"),
            candidate_set_digest,
            canonical_order_digest,
            candidate_count: u32::try_from(candidate_count).expect("bounded candidates"),
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
            subgroup_audit_digest: digest("e2e-subgroup"),
        },
        ood: OodArtifactV1 {
            artifact_digest: ood_artifact_digest,
            policy_digest,
            detector_digest: digest("e2e-detector"),
            support_digest: digest("e2e-ood-support"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            maximum_in_domain_score: probability_ppm(250_000),
            measured_false_acceptance_ppm: 0,
        },
        assignment: AssignmentModeV1::CounterBased {
            random_stream_digest: digest("e2e-random-stream-manifest"),
            draw: ProbabilityQ32::ZERO,
            abstain_probability: ProbabilityQ32::ZERO,
        },
        candidates,
    };
    let profile = CanonicalPolicyProfileV1 {
        profile_id: id("e2e-profile"),
        policy_digest,
        objective_class_digest,
        generation: 1,
        valid_from_sequence: 1,
        expires_after_sequence: 100,
        minimum_confidence: probability_ppm(500_000),
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        maximum_in_domain_score: probability_ppm(250_000),
        risk_rule: CanonicalRiskRuleV1::HighOnlySlowPath,
        scorer: LearnedScorerContractV1 {
            model_digest: model_artifact_digest,
            feature_schema_digest,
            output_schema_digest: digest("e2e-output-schema"),
            score_semantics_digest: digest("e2e-score-semantics"),
            scorer_contract_digest,
        },
        calibration_dataset_digest: digest("e2e-calibration-data"),
        ood_dataset_digest: digest("e2e-ood-data"),
        calibration_artifact_digest,
        calibration_measured_ece_ppm: 0,
        calibration_subgroup_audit_digest: digest("e2e-subgroup"),
        ood_artifact_digest,
        ood_measured_false_acceptance_ppm: 0,
        ood_detector_digest: digest("e2e-detector"),
        ood_support_digest: digest("e2e-ood-support"),
    };
    let scoring = ScoringCommitmentV1 {
        decision_id: request.decision_id.clone(),
        model_artifact_digest,
        feature_schema_digest,
        feature_snapshot_digest: digest("e2e-feature-snapshot"),
        scorer_contract_digest,
        candidate_set_digest,
        scored_candidates_digest: canonical_scored_candidates_digest_v1(&request)
            .expect("scored candidates"),
        policy_digest,
        policy_generation: 1,
        sequence: 7,
    };

    let keys = [
        SigningKey::from_bytes(&[31; 32]),
        SigningKey::from_bytes(&[47; 32]),
        SigningKey::from_bytes(&[59; 32]),
        SigningKey::from_bytes(&[71; 32]),
    ];
    let scope_digest = digest("e2e-intuition-scope");
    let principals = [
        ("e2e-generator", "e2e-generator-credential"),
        ("e2e-evaluator", "e2e-evaluator-credential"),
        ("e2e-scorer", "e2e-scorer-credential"),
        ("e2e-randomizer", "e2e-randomizer-credential"),
    ]
    .into_iter()
    .enumerate()
    .map(|(index, (principal_id, credential))| AuthenticatedPrincipalV1 {
        principal_id: id(principal_id),
        credential_chain_digest: digest(credential),
        signing_key_digest: Digest32::of_bytes(&keys[index].verifying_key().to_bytes()),
        scope_digest,
        authority_epoch: 1,
        authenticated_at: 50,
        expires_at: 250,
    })
    .collect::<Vec<_>>();
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest,
        objective_digest,
        authority_epoch: 1,
        signers: vec![
            trusted(&principals[0], &keys[0], "e2e-generator-controller", LearningEvidenceRoleV1::Generator),
            trusted(&principals[1], &keys[1], "e2e-evaluator-controller", LearningEvidenceRoleV1::Evaluator),
            trusted(&principals[2], &keys[2], "e2e-scorer-controller", LearningEvidenceRoleV1::Observer),
            trusted(&principals[3], &keys[3], "e2e-randomizer-controller", LearningEvidenceRoleV1::Observer),
        ],
    })
    .expect("trust");

    let completeness_payload = canonical_completeness_evidence_payload_v1(&request).expect("completeness");
    let profile_payload =
        canonical_profile_qualification_evidence_payload_v1(&profile).expect("profile");
    let decision_request_payload =
        canonical_decision_request_evidence_payload_v1(&request, &profile, &scoring)
            .expect("decision request");
    let scoring_payload =
        canonical_scoring_evidence_payload_v1(&request, &profile, &scoring).expect("scoring");
    let assignment_payload = canonical_assignment_evidence_payload_v1(&request).expect("assignment");

    Fixture {
        completeness: sign(&verifier, &principals[0], &keys[0], LearningEvidenceRoleV1::Generator, "e2e-completeness-evidence", objective_digest, &completeness_payload),
        profile_qualification: sign(&verifier, &principals[1], &keys[1], LearningEvidenceRoleV1::Evaluator, "e2e-profile-evidence", objective_digest, &profile_payload),
        decision_request: sign(&verifier, &principals[1], &keys[1], LearningEvidenceRoleV1::Evaluator, "e2e-decision-request-evidence", objective_digest, &decision_request_payload),
        scoring_evidence: sign(&verifier, &principals[2], &keys[2], LearningEvidenceRoleV1::Observer, "e2e-scoring-evidence", objective_digest, &scoring_payload),
        assignment: sign(&verifier, &principals[3], &keys[3], LearningEvidenceRoleV1::Observer, "e2e-assignment-evidence", objective_digest, &assignment_payload),
        request,
        profile,
        scoring,
        verifier,
    }
}

fn trusted(
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    controller: &str,
    role: LearningEvidenceRoleV1,
) -> TrustedLearningSignerV1 {
    TrustedLearningSignerV1 {
        principal: principal.clone(),
        controller_id: id(controller),
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![role],
        revoked_at: None,
    }
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

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn probability_ppm(ppm: u32) -> ProbabilityQ32 {
    let raw = (u128::from(ProbabilityQ32::ONE.raw()) * u128::from(ppm)) / 1_000_000;
    ProbabilityQ32::from_raw(raw as u64).expect("bounded probability")
}
