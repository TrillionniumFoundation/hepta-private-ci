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
use codex_hepta_intuition::OodArtifactV1;
use codex_hepta_intuition::RiskClass;
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::qualified::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

struct CountingAllocator;

static ALLOCATION_COUNT: AtomicU64 = AtomicU64::new(0);
static ALLOCATION_BYTES: AtomicU64 = AtomicU64::new(0);

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        // SAFETY: delegation preserves the exact `GlobalAlloc` contract of `System`.
        let pointer = unsafe { System.alloc(layout) };
        if !pointer.is_null() {
            ALLOCATION_COUNT.fetch_add(1, Ordering::Relaxed);
            ALLOCATION_BYTES.fetch_add(layout.size() as u64, Ordering::Relaxed);
        }
        pointer
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        // SAFETY: the pointer/layout pair came from the delegated `System` allocator.
        unsafe { System.dealloc(pointer, layout) };
    }

    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        // SAFETY: delegation preserves the original allocation and requested size.
        let resized = unsafe { System.realloc(pointer, layout, new_size) };
        if !resized.is_null() {
            ALLOCATION_COUNT.fetch_add(1, Ordering::Relaxed);
            ALLOCATION_BYTES.fetch_add(new_size as u64, Ordering::Relaxed);
        }
        resized
    }
}

#[global_allocator]
static GLOBAL: CountingAllocator = CountingAllocator;

struct BenchmarkFixture {
    artifact_key: QualificationMacKeyV1,
    scorer_key: QualificationMacKeyV1,
    assignment_key: QualificationMacKeyV1,
    subject_id: StableId,
    request: CalibratedDecisionRequestV1,
    profile: CanonicalPolicyProfileV1,
    scorer_contract: LearnedScorerContractV1,
    evidence: Vec<LearnedScoreEvidenceV1>,
    profile_mac: QualificationMacV1,
    calibration_mac: QualificationMacV1,
    ood_mac: QualificationMacV1,
    completeness_mac: QualificationMacV1,
    scorer_mac: QualificationMacV1,
    assignment_mac: QualificationMacV1,
}

#[derive(Clone, Copy)]
struct Budget {
    candidates: usize,
    p99_ns: u128,
    minimum_throughput_per_second: u128,
    maximum_allocations: u64,
    maximum_allocation_bytes: u64,
}

const BUDGETS: [Budget; 4] = [
    Budget {
        candidates: 1,
        p99_ns: 5_000_000,
        minimum_throughput_per_second: 200,
        maximum_allocations: 64,
        maximum_allocation_bytes: 64 * 1024,
    },
    Budget {
        candidates: 16,
        p99_ns: 8_000_000,
        minimum_throughput_per_second: 100,
        maximum_allocations: 96,
        maximum_allocation_bytes: 192 * 1024,
    },
    Budget {
        candidates: 64,
        p99_ns: 15_000_000,
        minimum_throughput_per_second: 50,
        maximum_allocations: 160,
        maximum_allocation_bytes: 512 * 1024,
    },
    Budget {
        candidates: 128,
        p99_ns: 25_000_000,
        minimum_throughput_per_second: 25,
        maximum_allocations: 240,
        maximum_allocation_bytes: 1024 * 1024,
    },
];

const ITERATIONS: usize = 400;

#[test]
#[ignore = "release-only latency, throughput and allocation qualification"]
fn qualified_fast_path_meets_1_16_64_128_candidate_budgets() {
    for budget in BUDGETS {
        benchmark_budget(budget);
    }
}

fn benchmark_budget(budget: Budget) {
    let fixture = BenchmarkFixture::new(budget.candidates);
    for _ in 0..20 {
        let receipt = fixture.execute();
        black_box(receipt);
    }

    let mut latencies = Vec::with_capacity(ITERATIONS);
    let mut maximum_allocations = 0_u64;
    let mut maximum_allocation_bytes = 0_u64;
    for _ in 0..ITERATIONS {
        let request = fixture.request.clone();
        let profile = fixture.profile.clone();
        let scorer_contract = fixture.scorer_contract.clone();
        let evidence = fixture.evidence.clone();
        reset_allocations();
        let started = Instant::now();
        let receipt = fixture.execute_owned(request, profile, scorer_contract, evidence);
        let elapsed = started.elapsed().as_nanos();
        let allocations = ALLOCATION_COUNT.load(Ordering::Relaxed);
        let bytes = ALLOCATION_BYTES.load(Ordering::Relaxed);
        black_box(&receipt);
        latencies.push(elapsed);
        maximum_allocations = maximum_allocations.max(allocations);
        maximum_allocation_bytes = maximum_allocation_bytes.max(bytes);
    }

    let total_ns = latencies.iter().copied().sum::<u128>();
    latencies.sort_unstable();
    let p50 = percentile(&latencies, 50);
    let p95 = percentile(&latencies, 95);
    let p99 = percentile(&latencies, 99);
    let throughput = (ITERATIONS as u128)
        .saturating_mul(1_000_000_000)
        .checked_div(total_ns.max(1))
        .unwrap_or(0);

    println!(
        "FAST_BENCH candidates={} p50_ns={} p95_ns={} p99_ns={} throughput_per_s={} max_allocations={} max_allocation_bytes={}",
        budget.candidates,
        p50,
        p95,
        p99,
        throughput,
        maximum_allocations,
        maximum_allocation_bytes,
    );

    assert!(
        p99 <= budget.p99_ns,
        "{} candidates p99 {}ns exceeds {}ns",
        budget.candidates,
        p99,
        budget.p99_ns,
    );
    assert!(
        throughput >= budget.minimum_throughput_per_second,
        "{} candidates throughput {} /s below {} /s",
        budget.candidates,
        throughput,
        budget.minimum_throughput_per_second,
    );
    assert!(
        maximum_allocations <= budget.maximum_allocations,
        "{} candidates allocations {} exceed {}",
        budget.candidates,
        maximum_allocations,
        budget.maximum_allocations,
    );
    assert!(
        maximum_allocation_bytes <= budget.maximum_allocation_bytes,
        "{} candidates allocation bytes {} exceed {}",
        budget.candidates,
        maximum_allocation_bytes,
        budget.maximum_allocation_bytes,
    );
}

impl BenchmarkFixture {
    fn new(candidate_count: usize) -> Self {
        let generation = 11;
        let sequence = 77;
        let policy_digest = digest(b"benchmark-policy");
        let objective_class_digest = digest(b"benchmark-objective-class");
        let state_digest = digest(b"benchmark-state");
        let candidates = (0..candidate_count)
            .map(benchmark_candidate)
            .collect::<Vec<_>>();
        let evidence = candidates
            .iter()
            .enumerate()
            .map(|(index, candidate)| LearnedScoreEvidenceV1 {
                candidate_id: candidate.candidate_id.clone(),
                feature_digest: digest(format!("feature:{index:03}").as_bytes()),
                utility: candidate.utility,
                calibrated_confidence: candidate.calibrated_confidence,
                ood_score: candidate.ood_score,
                support_digest: candidate.support_digest,
            })
            .collect::<Vec<_>>();
        let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates)
            .unwrap_or_else(|error| panic!("candidate set digest: {error:?}"));
        let canonical_order_digest = canonical_candidate_order_digest_v1(&candidates)
            .unwrap_or_else(|error| panic!("candidate order digest: {error:?}"));

        let mut calibration = CalibrationArtifactV1 {
            artifact_digest: Digest32::ZERO,
            policy_digest,
            objective_class_digest,
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            measured_ece_ppm: 25_000,
            subgroup_audit_digest: digest(b"benchmark-calibration-audit"),
        };
        calibration.artifact_digest = canonical_calibration_artifact_digest_v1(&calibration);
        let mut ood = OodArtifactV1 {
            artifact_digest: Digest32::ZERO,
            policy_digest,
            detector_digest: digest(b"benchmark-ood-detector"),
            support_digest: digest(b"benchmark-ood-support"),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            maximum_in_domain_score: probability_ppm(250_000),
            measured_false_acceptance_ppm: 500,
        };
        ood.artifact_digest = canonical_ood_artifact_digest_v1(&ood);

        let mut completeness = CandidateSetCompletenessBindingV1 {
            receipt_digest: Digest32::ZERO,
            generator_digest: digest(b"benchmark-generator"),
            grammar_digest: digest(b"benchmark-grammar"),
            hard_filter_digest: digest(b"benchmark-hard-filter"),
            truncation_digest: digest(b"benchmark-no-truncation"),
            candidate_set_digest,
            canonical_order_digest,
            candidate_count: u32::try_from(candidate_count)
                .unwrap_or_else(|error| panic!("candidate count: {error:?}")),
            omitted_count_bound: 0,
        };
        completeness.receipt_digest = canonical_completeness_receipt_digest_v1(
            &completeness,
            state_digest,
            policy_digest,
            generation,
            sequence,
        );

        let mut scorer_contract = LearnedScorerContractV1 {
            contract_digest: Digest32::ZERO,
            policy_digest,
            objective_class_digest,
            model_artifact_digest: digest(b"benchmark-model-artifact"),
            feature_schema_digest: digest(b"benchmark-feature-schema"),
            utility_semantics_digest: digest(b"benchmark-utility-semantics"),
            confidence_semantics_digest: digest(b"benchmark-confidence-semantics"),
            ood_semantics_digest: digest(b"benchmark-ood-semantics"),
            calibration_artifact_digest: calibration.artifact_digest,
            ood_artifact_digest: ood.artifact_digest,
            ood_detector_digest: ood.detector_digest,
            generation,
        };
        scorer_contract.contract_digest = canonical_scorer_contract_digest_v1(&scorer_contract);
        let mut profile = CanonicalPolicyProfileV1 {
            profile_digest: Digest32::ZERO,
            policy_digest,
            objective_class_digest,
            scorer_contract_digest: scorer_contract.contract_digest,
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            minimum_confidence: probability_ppm(700_000),
            maximum_ece_ppm: 50_000,
            maximum_ood_false_acceptance_ppm: 5_000,
            risk_policy: RiskPolicyV1::HighAlwaysSlowPath,
            require_zero_omissions: true,
        };
        profile.profile_digest = canonical_policy_profile_digest_v1(&profile)
            .unwrap_or_else(|error| panic!("profile digest: {error:?}"));

        let request = CalibratedDecisionRequestV1 {
            decision_id: id("decision:benchmark"),
            objective_digest: digest(b"benchmark-objective"),
            objective_class_digest,
            state_digest,
            policy_digest,
            policy_generation: generation,
            sequence,
            minimum_confidence: profile.minimum_confidence,
            maximum_ece_ppm: profile.maximum_ece_ppm,
            maximum_ood_false_acceptance_ppm: profile.maximum_ood_false_acceptance_ppm,
            risk_class: RiskClass::Low,
            completeness,
            calibration,
            ood,
            assignment: AssignmentModeV1::Deterministic,
            candidates,
        };
        let scorer_output_digest = canonical_scorer_output_digest_v1(
            &request.decision_id,
            request.state_digest,
            scorer_contract.contract_digest,
            scorer_contract.model_artifact_digest,
            &evidence,
        )
        .unwrap_or_else(|error| panic!("scorer output digest: {error:?}"));
        let assignment_digest = canonical_assignment_digest_v1(
            &request,
            profile.profile_digest,
            scorer_output_digest,
        )
        .unwrap_or_else(|error| panic!("assignment digest: {error:?}"));

        let artifact_key = QualificationMacKeyV1::from_trusted_bytes(
            id("qualification:key:benchmark-artifacts"),
            1,
            [0x61; 32],
            false,
        );
        let scorer_key = QualificationMacKeyV1::from_trusted_bytes(
            id("qualification:key:benchmark-scorer"),
            1,
            [0x72; 32],
            false,
        );
        let assignment_key = QualificationMacKeyV1::from_trusted_bytes(
            id("qualification:key:benchmark-assignment"),
            1,
            [0x83; 32],
            false,
        );
        let subject_id = id("intuition:policy:benchmark");
        let profile_mac = issue_qualification_mac_v1(
            &artifact_key,
            subject_id.clone(),
            policy_profile_scope_digest_v1(),
            profile.profile_digest,
            generation,
            1,
            100,
        )
        .unwrap_or_else(|error| panic!("profile mac: {error:?}"));
        let calibration_mac = issue_qualification_mac_v1(
            &artifact_key,
            subject_id.clone(),
            calibration_scope_digest_v1(),
            request.calibration.artifact_digest,
            generation,
            1,
            100,
        )
        .unwrap_or_else(|error| panic!("calibration mac: {error:?}"));
        let ood_mac = issue_qualification_mac_v1(
            &artifact_key,
            subject_id.clone(),
            ood_scope_digest_v1(),
            request.ood.artifact_digest,
            generation,
            1,
            100,
        )
        .unwrap_or_else(|error| panic!("ood mac: {error:?}"));
        let completeness_mac = issue_qualification_mac_v1(
            &artifact_key,
            subject_id.clone(),
            completeness_scope_digest_v1(),
            request.completeness.receipt_digest,
            generation,
            sequence,
            sequence,
        )
        .unwrap_or_else(|error| panic!("completeness mac: {error:?}"));
        let scorer_mac = issue_qualification_mac_v1(
            &scorer_key,
            subject_id.clone(),
            scorer_output_scope_digest_v1(),
            scorer_output_digest,
            generation,
            sequence,
            sequence,
        )
        .unwrap_or_else(|error| panic!("scorer mac: {error:?}"));
        let assignment_mac = issue_qualification_mac_v1(
            &assignment_key,
            subject_id.clone(),
            assignment_scope_digest_v1(),
            assignment_digest,
            generation,
            sequence,
            sequence,
        )
        .unwrap_or_else(|error| panic!("assignment mac: {error:?}"));

        Self {
            artifact_key,
            scorer_key,
            assignment_key,
            subject_id,
            request,
            profile,
            scorer_contract,
            evidence,
            profile_mac,
            calibration_mac,
            ood_mac,
            completeness_mac,
            scorer_mac,
            assignment_mac,
        }
    }

    fn execute(&self) -> QualifiedIntuitionReceiptV1 {
        self.execute_owned(
            self.request.clone(),
            self.profile.clone(),
            self.scorer_contract.clone(),
            self.evidence.clone(),
        )
    }

    fn execute_owned(
        &self,
        request: CalibratedDecisionRequestV1,
        profile: CanonicalPolicyProfileV1,
        scorer_contract: LearnedScorerContractV1,
        evidence: Vec<LearnedScoreEvidenceV1>,
    ) -> QualifiedIntuitionReceiptV1 {
        decide_qualified_v1(
            QualifiedDecisionRequestV1 {
                request,
                profile,
                scorer_contract,
                score_evidence: evidence,
                artifacts: QualifiedArtifactsV1 {
                    profile: &self.profile_mac,
                    calibration: &self.calibration_mac,
                    ood: &self.ood_mac,
                    completeness: &self.completeness_mac,
                    scorer_output: &self.scorer_mac,
                    assignment: &self.assignment_mac,
                },
            },
            QualificationTrustV1 {
                artifact_key: &self.artifact_key,
                scorer_key: &self.scorer_key,
                assignment_key: &self.assignment_key,
                subject_id: &self.subject_id,
                expected_generation: self.request.policy_generation,
            },
        )
        .unwrap_or_else(|error| panic!("benchmark decision: {error:?}"))
    }
}

fn benchmark_candidate(index: usize) -> CalibratedActionCandidateV1 {
    let candidate_id = id(&format!("candidate:{index:03}"));
    CalibratedActionCandidateV1 {
        candidate_id: candidate_id.clone(),
        legal: true,
        hard_veto: false,
        utility: FixedQ32::from_raw(
            i64::try_from(index).unwrap_or_else(|error| panic!("utility index: {error:?}")),
        ),
        calibrated_confidence: probability_ppm(900_000),
        ood_score: ProbabilityQ32::ZERO,
        assignment_probability: ProbabilityQ32::ZERO,
        support_digest: digest(candidate_id.as_str().as_bytes()),
    }
}

fn percentile(values: &[u128], percentile: usize) -> u128 {
    assert!(!values.is_empty());
    let index = (values.len() - 1).saturating_mul(percentile) / 100;
    values[index]
}

fn reset_allocations() {
    ALLOCATION_COUNT.store(0, Ordering::Relaxed);
    ALLOCATION_BYTES.store(0, Ordering::Relaxed);
}

fn probability_ppm(ppm: u64) -> ProbabilityQ32 {
    let raw = (u128::from(ProbabilityQ32::ONE.raw()) * u128::from(ppm) / 1_000_000) as u64;
    ProbabilityQ32::from_raw(raw)
        .unwrap_or_else(|error| panic!("valid probability: {error:?}"))
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id {value}: {error:?}"))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}
