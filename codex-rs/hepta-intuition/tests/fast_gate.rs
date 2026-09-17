use std::time::{Duration, Instant};

use codex_hepta_intuition::{
    AssignmentModeV1, CalibratedActionCandidateV1, CalibratedDecisionRequestV1,
    CalibrationArtifactV1, CandidateSetCompletenessBindingV1, OodArtifactV1, RiskClass,
    canonical_candidate_order_digest_v1, canonical_candidate_set_digest_v1, decide_calibrated_v2,
};
use codex_hepta_types::{Digest32, FixedQ32, ProbabilityQ32, StableId};

fn digest(value: &str) -> Digest32 { Digest32::of_bytes(value.as_bytes()) }
fn id(value: &str) -> StableId { StableId::new(value).expect("gate id") }

fn request(count: usize) -> CalibratedDecisionRequestV1 {
    let candidates = (0..count)
        .map(|index| CalibratedActionCandidateV1 {
            candidate_id: id(&format!("candidate:{index:03}")),
            legal: true,
            hard_veto: false,
            utility: FixedQ32::from_raw(i64::try_from(index).expect("bounded")),
            calibrated_confidence: ProbabilityQ32::ONE,
            ood_score: ProbabilityQ32::ZERO,
            assignment_probability: ProbabilityQ32::ZERO,
            support_digest: digest(&format!("support:{index:03}")),
        })
        .collect::<Vec<_>>();
    CalibratedDecisionRequestV1 {
        decision_id: id("decision:fast-gate"),
        objective_digest: digest("objective"),
        objective_class_digest: digest("objective-class"),
        state_digest: digest("state"),
        policy_digest: digest("policy"),
        policy_generation: 1,
        sequence: 10,
        minimum_confidence: ProbabilityQ32::ZERO,
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest("complete"), generator_digest: digest("generator"),
            grammar_digest: digest("grammar"), hard_filter_digest: digest("filter"),
            truncation_digest: digest("truncation"),
            candidate_set_digest: canonical_candidate_set_digest_v1(&candidates).expect("set"),
            canonical_order_digest: canonical_candidate_order_digest_v1(&candidates).expect("order"),
            candidate_count: u32::try_from(count).expect("bounded"), omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: digest("calibration"), policy_digest: digest("policy"),
            objective_class_digest: digest("objective-class"), generation: 1,
            valid_from_sequence: 1, expires_after_sequence: 100, measured_ece_ppm: 10_000,
            subgroup_audit_digest: digest("audit"),
        },
        ood: OodArtifactV1 {
            artifact_digest: digest("ood"), policy_digest: digest("policy"),
            detector_digest: digest("detector"), support_digest: digest("ood-support"), generation: 1,
            valid_from_sequence: 1, expires_after_sequence: 100,
            maximum_in_domain_score: ProbabilityQ32::ONE, measured_false_acceptance_ppm: 1_000,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    }
}

fn percentile(sorted: &[Duration], numerator: usize, denominator: usize) -> Duration {
    let index = ((sorted.len() - 1) * numerator) / denominator;
    sorted[index]
}

#[test]
fn fast_policy_latency_and_throughput_gate() {
    const SAMPLES: usize = 1_000;
    const P99_BUDGET: Duration = Duration::from_millis(20);
    const MIN_THROUGHPUT_PER_SEC: f64 = 50.0;

    for count in [1usize, 16, 64, 128] {
        let request = request(count);
        for _ in 0..32 {
            let _ = decide_calibrated_v2(request.clone()).expect("warmup decision");
        }

        let wall_start = Instant::now();
        let mut samples = Vec::with_capacity(SAMPLES);
        for _ in 0..SAMPLES {
            let start = Instant::now();
            let receipt = decide_calibrated_v2(request.clone()).expect("timed decision");
            std::hint::black_box(receipt);
            samples.push(start.elapsed());
        }
        let wall = wall_start.elapsed();
        samples.sort_unstable();
        let p50 = percentile(&samples, 50, 100);
        let p95 = percentile(&samples, 95, 100);
        let p99 = percentile(&samples, 99, 100);
        let throughput = SAMPLES as f64 / wall.as_secs_f64();

        eprintln!(
            "intuition.fast candidates={count} p50_us={} p95_us={} p99_us={} throughput_per_sec={throughput:.2}",
            p50.as_micros(), p95.as_micros(), p99.as_micros()
        );
        assert!(p99 <= P99_BUDGET, "candidate_count={count} p99={p99:?} exceeds {P99_BUDGET:?}");
        assert!(throughput >= MIN_THROUGHPUT_PER_SEC, "candidate_count={count} throughput={throughput}");
    }
}
