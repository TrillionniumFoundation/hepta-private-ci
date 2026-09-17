#![allow(unsafe_code)]

use std::alloc::GlobalAlloc;
use std::alloc::Layout;
use std::alloc::System;
use std::hint::black_box;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_intuition::calibrated::AssignmentModeV1;
use codex_hepta_intuition::calibrated::CalibratedActionCandidateV1;
use codex_hepta_intuition::calibrated::CalibratedDecisionRequestV1;
use codex_hepta_intuition::calibrated::CalibrationArtifactV1;
use codex_hepta_intuition::calibrated::CandidateSetCompletenessBindingV1;
use codex_hepta_intuition::calibrated::OodArtifactV1;
use codex_hepta_intuition::calibrated::RiskClass;
use codex_hepta_intuition::calibrated::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::calibrated::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::qualification::CanonicalPolicyProfileV1;
use codex_hepta_intuition::qualification::LearnedScorerContractV1;
use codex_hepta_intuition::qualification::QualificationVerifierV1;
use codex_hepta_intuition::qualification::SignedCandidateCompletenessV1;
use codex_hepta_intuition::qualification::SignedPolicyQualificationV1;
use codex_hepta_intuition::qualification::canonical_calibration_artifact_digest_v1;
use codex_hepta_intuition::qualification::canonical_candidate_completeness_digest_v1;
use codex_hepta_intuition::qualification::canonical_ood_artifact_digest_v1;
use codex_hepta_intuition::qualification::canonical_policy_profile_digest_v1;
use codex_hepta_intuition::qualification::canonical_policy_qualification_digest_v1;
use codex_hepta_intuition::qualification::canonical_scorer_contract_digest_v1;
use codex_hepta_intuition::qualification::decide_qualified_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

static ALLOCATION_COUNT: AtomicU64 = AtomicU64::new(0);
static ALLOCATION_BYTES: AtomicU64 = AtomicU64::new(0);

struct CountingAllocator;

// SAFETY: every operation delegates to `System` with the exact layout/pointer
// contract it received. The extra atomics are observational benchmark counters
// and never alter allocation ownership or lifetimes.
unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        // SAFETY: delegated unchanged to the system allocator.
        let pointer = unsafe { System.alloc(layout) };
        if !pointer.is_null() {
            ALLOCATION_COUNT.fetch_add(1, Ordering::Relaxed);
            ALLOCATION_BYTES.fetch_add(layout.size() as u64, Ordering::Relaxed);
        }
        pointer
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        // SAFETY: delegated unchanged to the system allocator.
        unsafe { System.dealloc(pointer, layout) };
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        // SAFETY: delegated unchanged to the system allocator.
        let pointer = unsafe { System.alloc_zeroed(layout) };
        if !pointer.is_null() {
            ALLOCATION_COUNT.fetch_add(1, Ordering::Relaxed);
            ALLOCATION_BYTES.fetch_add(layout.size() as u64, Ordering::Relaxed);
        }
        pointer
    }

    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        // SAFETY: delegated unchanged to the system allocator.
        let new_pointer = unsafe { System.realloc(pointer, layout, new_size) };
        if !new_pointer.is_null() {
            ALLOCATION_COUNT.fetch_add(1, Ordering::Relaxed);
            ALLOCATION_BYTES.fetch_add(new_size as u64, Ordering::Relaxed);
        }
        new_pointer
    }
}

#[global_allocator]
static GLOBAL_ALLOCATOR: CountingAllocator = CountingAllocator;

#[derive(Clone, Copy)]
struct Budget {
    candidates: usize,
    p50_ns: u128,
    p95_ns: u128,
    p99_ns: u128,
    minimum_throughput_ops_per_second: f64,
    maximum_allocations_per_operation: u64,
    maximum_allocated_bytes_per_operation: u64,
}

const BUDGETS: [Budget; 4] = [
    Budget {
        candidates: 1,
        p50_ns: 1_000_000,
        p95_ns: 1_500_000,
        p99_ns: 2_500_000,
        minimum_throughput_ops_per_second: 250.0,
        maximum_allocations_per_operation: 256,
        maximum_allocated_bytes_per_operation: 131_072,
    },
    Budget {
        candidates: 16,
        p50_ns: 1_200_000,
        p95_ns: 2_000_000,
        p99_ns: 3_500_000,
        minimum_throughput_ops_per_second: 200.0,
        maximum_allocations_per_operation: 384,
        maximum_allocated_bytes_per_operation: 196_608,
    },
    Budget {
        candidates: 64,
        p50_ns: 2_000_000,
        p95_ns: 3_500_000,
        p99_ns: 5_500_000,
        minimum_throughput_ops_per_second: 125.0,
        maximum_allocations_per_operation: 640,
        maximum_allocated_bytes_per_operation: 262_144,
    },
    Budget {
        candidates: 128,
        p50_ns: 3_000_000,
        p95_ns: 5_000_000,
        p99_ns: 8_000_000,
        minimum_throughput_ops_per_second: 75.0,
        maximum_allocations_per_operation: 1_024,
        maximum_allocated_bytes_per_operation: 524_288,
    },
];

const WARMUP_ITERATIONS: usize = 100;
const MEASURED_ITERATIONS: usize = 1_500;

fn main() {
    let mut failures = Vec::new();
    println!("candidate_count,p50_ns,p95_ns,p99_ns,throughput_ops_s,allocations_per_op,allocated_bytes_per_op");
    for budget in BUDGETS {
        let fixture = build_fixture(budget.candidates);
        for _ in 0..WARMUP_ITERATIONS {
            let receipt = decide_qualified_v3(
                black_box(fixture.request.clone()),
                black_box(&fixture.qualification),
                black_box(&fixture.completeness),
                black_box(&fixture.verifier),
            )
            .unwrap_or_else(|error| panic!("warmup qualified decision: {error:?}"));
            black_box(receipt);
        }

        let mut latencies = Vec::with_capacity(MEASURED_ITERATIONS);
        let mut allocation_count = 0u64;
        let mut allocation_bytes = 0u64;
        let wall_start = Instant::now();
        for _ in 0..MEASURED_ITERATIONS {
            let before_count = ALLOCATION_COUNT.load(Ordering::Relaxed);
            let before_bytes = ALLOCATION_BYTES.load(Ordering::Relaxed);
            let started = Instant::now();
            let receipt = decide_qualified_v3(
                black_box(fixture.request.clone()),
                black_box(&fixture.qualification),
                black_box(&fixture.completeness),
                black_box(&fixture.verifier),
            )
            .unwrap_or_else(|error| panic!("measured qualified decision: {error:?}"));
            let elapsed = started.elapsed();
            let after_count = ALLOCATION_COUNT.load(Ordering::Relaxed);
            let after_bytes = ALLOCATION_BYTES.load(Ordering::Relaxed);
            allocation_count = allocation_count.saturating_add(after_count - before_count);
            allocation_bytes = allocation_bytes.saturating_add(after_bytes - before_bytes);
            latencies.push(elapsed.as_nanos());
            black_box(receipt);
        }
        let wall = wall_start.elapsed();
        latencies.sort_unstable();
        let p50 = percentile(&latencies, 50);
        let p95 = percentile(&latencies, 95);
        let p99 = percentile(&latencies, 99);
        let throughput = MEASURED_ITERATIONS as f64 / wall.as_secs_f64();
        let allocations_per_operation = allocation_count / MEASURED_ITERATIONS as u64;
        let allocated_bytes_per_operation = allocation_bytes / MEASURED_ITERATIONS as u64;
        println!(
            "{},{},{},{},{:.2},{},{}",
            budget.candidates,
            p50,
            p95,
            p99,
            throughput,
            allocations_per_operation,
            allocated_bytes_per_operation
        );

        if p50 > budget.p50_ns {
            failures.push(format!(
                "{} candidates p50 {}ns > {}ns",
                budget.candidates, p50, budget.p50_ns
            ));
        }
        if p95 > budget.p95_ns {
            failures.push(format!(
                "{} candidates p95 {}ns > {}ns",
                budget.candidates, p95, budget.p95_ns
            ));
        }
        if p99 > budget.p99_ns {
            failures.push(format!(
                "{} candidates p99 {}ns > {}ns",
                budget.candidates, p99, budget.p99_ns
            ));
        }
        if throughput < budget.minimum_throughput_ops_per_second {
            failures.push(format!(
                "{} candidates throughput {:.2} < {:.2} ops/s",
                budget.candidates, throughput, budget.minimum_throughput_ops_per_second
            ));
        }
        if allocations_per_operation > budget.maximum_allocations_per_operation {
            failures.push(format!(
                "{} candidates allocations/op {} > {}",
                budget.candidates,
                allocations_per_operation,
                budget.maximum_allocations_per_operation
            ));
        }
        if allocated_bytes_per_operation > budget.maximum_allocated_bytes_per_operation {
            failures.push(format!(
                "{} candidates allocated bytes/op {} > {}",
                budget.candidates,
                allocated_bytes_per_operation,
                budget.maximum_allocated_bytes_per_operation
            ));
        }
    }

    if !failures.is_empty() {
        for failure in &failures {
            eprintln!("benchmark gate failure: {failure}");
        }
        panic!("{} fast-policy benchmark budget(s) exceeded", failures.len());
    }
}

struct Fixture {
    request: CalibratedDecisionRequestV1,
    qualification: SignedPolicyQualificationV1,
    completeness: SignedCandidateCompletenessV1,
    verifier: QualificationVerifierV1,
}

fn build_fixture(candidate_count: usize) -> Fixture {
    let signer = SigningKey::from_bytes(&[0x3c; 32]);
    let issuer_id = id("qualification:fast-policy-bench");
    let policy_digest = digest(b"policy:fast-policy-bench");
    let objective_class_digest = digest(b"objective-class:fast-policy-bench");
    let support_digest = digest(b"support:fast-policy-bench");

    let mut calibration = CalibrationArtifactV1 {
        artifact_digest: digest(b"pending-calibration"),
        policy_digest,
        objective_class_digest,
        generation: 1,
        valid_from_sequence: 1,
        expires_after_sequence: 10_000,
        measured_ece_ppm: 10_000,
        subgroup_audit_digest: digest(b"subgroup-audit:bench"),
    };
    calibration.artifact_digest = canonical_calibration_artifact_digest_v1(&calibration)
        .unwrap_or_else(|error| panic!("calibration digest: {error:?}"));
    let mut ood = OodArtifactV1 {
        artifact_digest: digest(b"pending-ood"),
        policy_digest,
        detector_digest: digest(b"ood-detector:bench"),
        support_digest,
        generation: 1,
        valid_from_sequence: 1,
        expires_after_sequence: 10_000,
        maximum_in_domain_score: probability_from_ppm(250_000),
        measured_false_acceptance_ppm: 1_000,
    };
    ood.artifact_digest = canonical_ood_artifact_digest_v1(&ood)
        .unwrap_or_else(|error| panic!("OOD digest: {error:?}"));

    let scorer = LearnedScorerContractV1 {
        owner_id: id("scorer-owner:bench"),
        scorer_service_digest: digest(b"scorer-service:bench"),
        model_digest: digest(b"model:bench"),
        feature_schema_digest: digest(b"feature-schema:bench"),
        score_semantics_digest: digest(b"score-semantics:bench"),
        calibration_link_digest: calibration.artifact_digest,
        support_digest,
    };
    let scorer_contract_digest = canonical_scorer_contract_digest_v1(&scorer)
        .unwrap_or_else(|error| panic!("scorer digest: {error:?}"));
    let profile = CanonicalPolicyProfileV1 {
        policy_digest,
        objective_class_digest,
        generation: 1,
        minimum_confidence: probability_from_ppm(600_000),
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        allow_elevated_risk_direct: true,
        high_risk_forces_slow_path: true,
        scorer,
    };
    let profile_digest = canonical_policy_profile_digest_v1(&profile)
        .unwrap_or_else(|error| panic!("profile digest: {error:?}"));
    let mut qualification = SignedPolicyQualificationV1 {
        issuer_id: issuer_id.clone(),
        issuer_epoch: 1,
        profile,
        calibration: calibration.clone(),
        ood: ood.clone(),
        frozen_validation_data_digest: digest(b"frozen-data:bench"),
        qualification_report_digest: digest(b"qualification-report:bench"),
        valid_from_sequence: 1,
        expires_after_sequence: 10_000,
        signature: [0; 64],
    };
    let qualification_digest = canonical_policy_qualification_digest_v1(&qualification)
        .unwrap_or_else(|error| panic!("qualification digest: {error:?}"));
    qualification.signature = signer.sign(qualification_digest.as_array()).to_bytes();

    let candidates = (0..candidate_count)
        .map(|index| CalibratedActionCandidateV1 {
            candidate_id: id(&format!("candidate:{index:03}")),
            legal: true,
            hard_veto: false,
            utility: FixedQ32::from_raw(index as i64),
            calibrated_confidence: ProbabilityQ32::ONE,
            ood_score: ProbabilityQ32::ZERO,
            assignment_probability: ProbabilityQ32::ZERO,
            support_digest,
        })
        .collect::<Vec<_>>();
    let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates)
        .unwrap_or_else(|error| panic!("candidate set digest: {error:?}"));
    let canonical_order_digest = canonical_candidate_order_digest_v1(&candidates)
        .unwrap_or_else(|error| panic!("candidate order digest: {error:?}"));
    let decision_id = id(&format!("decision:bench:{candidate_count}"));
    let objective_digest = digest(b"objective:bench");
    let state_digest = digest(b"state:bench");
    let mut completeness = SignedCandidateCompletenessV1 {
        issuer_id: issuer_id.clone(),
        issuer_epoch: 1,
        decision_id: decision_id.clone(),
        objective_digest,
        objective_class_digest,
        state_digest,
        policy_digest,
        policy_generation: 1,
        sequence: 100,
        policy_profile_digest: profile_digest,
        scorer_contract_digest,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest(b"pending-completeness"),
            generator_digest: digest(b"generator:bench"),
            grammar_digest: digest(b"grammar:bench"),
            hard_filter_digest: digest(b"hard-filter:bench"),
            truncation_digest: digest(b"no-truncation:bench"),
            candidate_set_digest,
            canonical_order_digest,
            candidate_count: candidate_count as u32,
            omitted_count_bound: 0,
        },
        signature: [0; 64],
    };
    let completeness_digest = canonical_candidate_completeness_digest_v1(&completeness)
        .unwrap_or_else(|error| panic!("completeness digest: {error:?}"));
    completeness.completeness.receipt_digest = completeness_digest;
    completeness.signature = signer.sign(completeness_digest.as_array()).to_bytes();

    let request = CalibratedDecisionRequestV1 {
        decision_id,
        objective_digest,
        objective_class_digest,
        state_digest,
        policy_digest,
        policy_generation: 1,
        sequence: 100,
        minimum_confidence: qualification.profile.minimum_confidence,
        maximum_ece_ppm: qualification.profile.maximum_ece_ppm,
        maximum_ood_false_acceptance_ppm: qualification
            .profile
            .maximum_ood_false_acceptance_ppm,
        risk_class: RiskClass::Low,
        completeness: completeness.completeness.clone(),
        calibration,
        ood,
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    };
    let verifier = QualificationVerifierV1::from_bytes(
        issuer_id,
        1,
        signer.verifying_key().to_bytes(),
        policy_digest,
        1,
        profile_digest,
    )
    .unwrap_or_else(|error| panic!("verifier: {error:?}"));

    Fixture {
        request,
        qualification,
        completeness,
        verifier,
    }
}

fn percentile(values: &[u128], percentile: usize) -> u128 {
    let index = (values.len() - 1) * percentile / 100;
    values[index]
}

fn probability_from_ppm(ppm: u32) -> ProbabilityQ32 {
    let raw = u128::from(ProbabilityQ32::ONE.raw()) * u128::from(ppm) / 1_000_000u128;
    ProbabilityQ32::from_raw(raw as u64)
        .unwrap_or_else(|error| panic!("valid probability: {error:?}"))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id {value}: {error:?}"))
}

#[allow(dead_code)]
fn _duration_to_nanos(duration: Duration) -> u128 {
    duration.as_nanos()
}
