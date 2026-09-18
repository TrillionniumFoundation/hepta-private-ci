//! Deterministic qualification helpers for memory.retrieval.
//!
//! The code aggregates observed samples; it does not claim that a target host
//! met a latency or memory threshold merely because this helper compiled.

use codex_hepta_types::Digest32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalLatencySummaryV1 {
    pub sample_count: u32,
    pub p50_nanos: u64,
    pub p95_nanos: u64,
    pub p99_nanos: u64,
    pub maximum_nanos: u64,
    pub sample_digest: Digest32,
}

impl RetrievalLatencySummaryV1 {
    pub fn from_samples(samples: &[u64]) -> Option<Self> {
        if samples.is_empty() || samples.len() > 1_000_000 {
            return None;
        }
        let mut sorted = samples.to_vec();
        sorted.sort_unstable();
        let mut bytes = b"hepta.retrieval-latency-samples.v1".to_vec();
        bytes.extend_from_slice(
            &u64::try_from(sorted.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        for sample in &sorted {
            bytes.extend_from_slice(&sample.to_be_bytes());
        }
        Some(Self {
            sample_count: u32::try_from(sorted.len()).unwrap_or(u32::MAX),
            p50_nanos: percentile(&sorted, 50),
            p95_nanos: percentile(&sorted, 95),
            p99_nanos: percentile(&sorted, 99),
            maximum_nanos: *sorted.last().unwrap_or(&0),
            sample_digest: Digest32::of_bytes(&bytes),
        })
    }
}

fn percentile(sorted: &[u64], percentile: usize) -> u64 {
    let numerator = percentile
        .saturating_mul(sorted.len().saturating_sub(1));
    let index = numerator.saturating_add(99) / 100;
    sorted[index.min(sorted.len().saturating_sub(1))]
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalStructuralCapacityV1 {
    pub candidate_count: u32,
    pub node_count: u32,
    pub synapse_count: u32,
    pub returned_count: u32,
    pub recurrent_steps: u8,
    pub active_units_per_population: u16,
}

impl RetrievalStructuralCapacityV1 {
    pub fn validate(&self) -> bool {
        usize::try_from(self.candidate_count).is_ok_and(|value| {
            value <= crate::MAX_GENERATION_BOUND_CANDIDATES
        }) && usize::try_from(self.node_count)
            .is_ok_and(|value| value <= crate::MAX_ENGRAM_NODES)
            && usize::try_from(self.synapse_count)
                .is_ok_and(|value| value <= crate::MAX_ENGRAM_SYNAPSES)
            && usize::try_from(self.returned_count)
                .is_ok_and(|value| value <= crate::MAX_GENERATION_BOUND_RESULTS)
            && self.recurrent_steps <= crate::MAX_RECURRENT_STEPS
            && self.active_units_per_population <= crate::MAX_ACTIVE_UNITS_PER_POPULATION
    }
}

#[cfg(test)]
#[path = "qualification_tests.rs"]
mod tests;
