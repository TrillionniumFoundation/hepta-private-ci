use super::*;

#[test]
fn latency_summary_reports_stable_percentiles_and_digest() {
    let samples = (1_u64..=100).collect::<Vec<_>>();
    let summary = RetrievalLatencySummaryV1::from_samples(&samples).unwrap();
    assert_eq!(summary.sample_count, 100);
    assert_eq!(summary.p50_nanos, 51);
    assert_eq!(summary.p95_nanos, 96);
    assert_eq!(summary.p99_nanos, 100);
    assert_eq!(summary.maximum_nanos, 100);
    assert_eq!(
        summary,
        RetrievalLatencySummaryV1::from_samples(&samples).unwrap()
    );
}

#[test]
fn structural_capacity_matches_the_qualified_hnmf_profile() {
    assert!(
        RetrievalStructuralCapacityV1 {
            candidate_count: crate::MAX_GENERATION_BOUND_CANDIDATES as u32,
            node_count: crate::MAX_ENGRAM_NODES as u32,
            synapse_count: crate::MAX_ENGRAM_SYNAPSES as u32,
            returned_count: crate::MAX_GENERATION_BOUND_RESULTS as u32,
            recurrent_steps: crate::MAX_RECURRENT_STEPS,
            active_units_per_population: crate::MAX_ACTIVE_UNITS_PER_POPULATION,
        }
        .validate()
    );
    assert!(
        !RetrievalStructuralCapacityV1 {
            candidate_count: crate::MAX_GENERATION_BOUND_CANDIDATES as u32 + 1,
            node_count: 0,
            synapse_count: 0,
            returned_count: 0,
            recurrent_steps: 0,
            active_units_per_population: 0,
        }
        .validate()
    );
}
