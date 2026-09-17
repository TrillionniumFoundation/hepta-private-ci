use codex_hepta_intuition::{
    AssignmentModeV1, CalibratedActionCandidateV1, CalibratedDecisionRequestV1,
    CalibrationArtifactV1, CandidateSetCompletenessBindingV1, OodArtifactV1, RiskClass,
    canonical_candidate_order_digest_v1, canonical_candidate_set_digest_v1, decide_calibrated_v2,
};
use codex_hepta_types::{Digest32, FixedQ32, ProbabilityQ32, StableId};

#[global_allocator]
static ALLOC: divan::AllocProfiler = divan::AllocProfiler::system();

fn main() {
    divan::main();
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("benchmark id")
}

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
    let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates).expect("set digest");
    let canonical_order_digest = canonical_candidate_order_digest_v1(&candidates).expect("order digest");
    CalibratedDecisionRequestV1 {
        decision_id: id("decision:bench"),
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
            receipt_digest: digest("complete"),
            generator_digest: digest("generator"),
            grammar_digest: digest("grammar"),
            hard_filter_digest: digest("filter"),
            truncation_digest: digest("truncation"),
            candidate_set_digest,
            canonical_order_digest,
            candidate_count: u32::try_from(count).expect("bounded"),
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: digest("calibration"),
            policy_digest: digest("policy"),
            objective_class_digest: digest("objective-class"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            measured_ece_ppm: 10_000,
            subgroup_audit_digest: digest("audit"),
        },
        ood: OodArtifactV1 {
            artifact_digest: digest("ood"),
            policy_digest: digest("policy"),
            detector_digest: digest("detector"),
            support_digest: digest("ood-support"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            maximum_in_domain_score: ProbabilityQ32::ONE,
            measured_false_acceptance_ppm: 1_000,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    }
}

#[divan::bench(args = [1usize, 16, 64, 128], sample_count = 2000)]
fn calibrated_v2_fast_path(bencher: divan::Bencher, candidate_count: usize) {
    let request = request(candidate_count);
    bencher.bench(|| {
        let receipt = decide_calibrated_v2(divan::black_box(request.clone())).expect("bench decision");
        divan::black_box(receipt);
    });
}
