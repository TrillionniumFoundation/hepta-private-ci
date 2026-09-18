use std::alloc::GlobalAlloc;
use std::alloc::Layout;
use std::alloc::System;
use std::hint::black_box;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;

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
use codex_hepta_intuition::decide_calibrated_v3;
use codex_hepta_intuition::scoring_commitment_for_request_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

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
        // SAFETY: `ptr`, `layout`, and `new_size` are passed through unchanged.
        unsafe { System.realloc(ptr, layout, new_size) }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        // SAFETY: `ptr` and `layout` originate from the delegated system allocator.
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
        iterations: 2_000,
        p99_ns: 2_000_000,
        min_throughput_per_second: 500,
        max_allocations: 128,
        max_allocation_bytes: 64 * 1024,
    },
    Gate {
        candidates: 16,
        iterations: 1_000,
        p99_ns: 4_000_000,
        min_throughput_per_second: 250,
        max_allocations: 512,
        max_allocation_bytes: 256 * 1024,
    },
    Gate {
        candidates: 64,
        iterations: 500,
        p99_ns: 8_000_000,
        min_throughput_per_second: 100,
        max_allocations: 2_048,
        max_allocation_bytes: 1024 * 1024,
    },
    Gate {
        candidates: 128,
        iterations: 300,
        p99_ns: 15_000_000,
        min_throughput_per_second: 50,
        max_allocations: 4_096,
        max_allocation_bytes: 2 * 1024 * 1024,
    },
];

fn main() {
    println!(
        "candidates,iterations,p50_ns,p95_ns,p99_ns,throughput_per_s,allocations_per_decision,allocation_bytes_per_decision"
    );
    for gate in GATES {
        run_gate(gate);
    }
}

fn run_gate(gate: Gate) {
    let (template, profile, scoring) = fixture(gate.candidates);
    for _ in 0..100 {
        let receipt =
            decide_calibrated_v3(template.clone(), &profile, &scoring).expect("warmup decision");
        black_box(receipt.receipt_digest);
    }

    let mut latencies = Vec::with_capacity(gate.iterations);
    let mut allocation_count = 0_u64;
    let mut allocation_bytes = 0_u64;
    for _ in 0..gate.iterations {
        let request = template.clone();
        let count_before = ALLOCATION_COUNT.load(Ordering::Relaxed);
        let bytes_before = ALLOCATION_BYTES.load(Ordering::Relaxed);
        let started = Instant::now();
        let receipt = decide_calibrated_v3(black_box(request), &profile, &scoring)
            .expect("qualified decision");
        let elapsed = started.elapsed();
        let count_after = ALLOCATION_COUNT.load(Ordering::Relaxed);
        let bytes_after = ALLOCATION_BYTES.load(Ordering::Relaxed);
        allocation_count += count_after - count_before;
        allocation_bytes += bytes_after - bytes_before;
        black_box(receipt.receipt_digest);
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
        "{} candidates p99={}ns exceeds {}ns",
        gate.candidates,
        p99,
        gate.p99_ns
    );
    assert!(
        throughput >= gate.min_throughput_per_second,
        "{} candidates throughput={} below {}",
        gate.candidates,
        throughput,
        gate.min_throughput_per_second
    );
    assert!(
        allocations_per_decision <= gate.max_allocations,
        "{} candidates allocations={} exceeds {}",
        gate.candidates,
        allocations_per_decision,
        gate.max_allocations
    );
    assert!(
        allocation_bytes_per_decision <= gate.max_allocation_bytes,
        "{} candidates allocation bytes={} exceeds {}",
        gate.candidates,
        allocation_bytes_per_decision,
        gate.max_allocation_bytes
    );
}

fn percentile(values: &[u64], percentile: usize) -> u64 {
    let index = ((values.len() - 1) * percentile + 99) / 100;
    values[index.min(values.len() - 1)]
}

fn fixture(
    candidate_count: usize,
) -> (
    CalibratedDecisionRequestV1,
    CanonicalPolicyProfileV1,
    codex_hepta_intuition::ScoringCommitmentV1,
) {
    let policy_digest = digest("benchmark-policy");
    let model_artifact_digest = digest("benchmark-model-artifact");
    let calibration_artifact_digest = digest("benchmark-calibration");
    let ood_artifact_digest = digest("benchmark-ood");
    let candidates = (0..candidate_count)
        .map(|index| CalibratedActionCandidateV1 {
            candidate_id: id(&format!("candidate:{index:03}")),
            legal: true,
            hard_veto: false,
            utility: FixedQ32::from_raw(index as i64),
            calibrated_confidence: ProbabilityQ32::ONE,
            ood_score: ProbabilityQ32::ZERO,
            assignment_probability: ProbabilityQ32::ZERO,
            support_digest: digest(&format!("support:{index:03}")),
        })
        .collect::<Vec<_>>();
    let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates).unwrap();
    let canonical_order_digest = canonical_candidate_order_digest_v1(&candidates).unwrap();
    let request = CalibratedDecisionRequestV1 {
        decision_id: id("benchmark-decision"),
        objective_digest: digest("benchmark-objective"),
        objective_class_digest: digest("benchmark-class"),
        state_digest: digest("benchmark-state"),
        policy_digest,
        policy_generation: 1,
        sequence: 1,
        minimum_confidence: probability_ppm(500_000),
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest("benchmark-completeness"),
            generator_digest: digest("benchmark-generator"),
            grammar_digest: digest("benchmark-grammar"),
            hard_filter_digest: digest("benchmark-filter"),
            truncation_digest: digest("benchmark-truncation"),
            candidate_set_digest,
            canonical_order_digest,
            candidate_count: candidate_count as u32,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: calibration_artifact_digest,
            policy_digest,
            objective_class_digest: digest("benchmark-class"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 1,
            measured_ece_ppm: 0,
            subgroup_audit_digest: digest("benchmark-subgroup"),
        },
        ood: OodArtifactV1 {
            artifact_digest: ood_artifact_digest,
            policy_digest,
            detector_digest: digest("benchmark-detector"),
            support_digest: digest("benchmark-ood-support"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 1,
            maximum_in_domain_score: probability_ppm(250_000),
            measured_false_acceptance_ppm: 0,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    };
    let profile = CanonicalPolicyProfileV1 {
        profile_id: id("benchmark-profile"),
        policy_digest,
        objective_class_digest: digest("benchmark-class"),
        generation: 1,
        valid_from_sequence: 1,
        expires_after_sequence: 1,
        minimum_confidence: probability_ppm(500_000),
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        maximum_in_domain_score: probability_ppm(250_000),
        risk_rule: CanonicalRiskRuleV1::HighOnlySlowPath,
        scorer: LearnedScorerContractV1 {
            model_artifact_digest,
            feature_schema_digest: digest("benchmark-features"),
            output_schema_digest: digest("benchmark-outputs"),
            score_semantics_digest: digest("benchmark-semantics"),
            scorer_contract_digest: digest("benchmark-scorer-contract"),
        },
        calibration_dataset_digest: digest("benchmark-calibration-data"),
        ood_dataset_digest: digest("benchmark-ood-data"),
        calibration_artifact_digest,
        calibration_measured_ece_ppm: 0,
        calibration_subgroup_audit_digest: digest("benchmark-subgroup"),
        calibration_valid_from_sequence: 1,
        calibration_expires_after_sequence: 1,
        ood_artifact_digest,
        ood_measured_false_acceptance_ppm: 0,
        ood_detector_digest: digest("benchmark-detector"),
        ood_support_digest: digest("benchmark-ood-support"),
        ood_valid_from_sequence: 1,
        ood_expires_after_sequence: 1,
    };
    let scoring =
        scoring_commitment_for_request_v1(&request, &profile, digest("benchmark-feature-snapshot"))
            .unwrap();
    (request, profile, scoring)
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn probability_ppm(ppm: u32) -> ProbabilityQ32 {
    let raw = (u128::from(ProbabilityQ32::ONE.raw()) * u128::from(ppm)) / 1_000_000;
    ProbabilityQ32::from_raw(raw as u64).unwrap()
}
