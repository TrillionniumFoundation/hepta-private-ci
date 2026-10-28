//! A distinct V3 profile for partitions learned from completed co-access traces.
//!
//! Recomputing the bounded trace and routing protects artifact integrity. It
//! does not authenticate observations or establish that a future task was
//! unseen: the signed host and its prospective receipt retain those duties.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;

use crate::AssociativeMemoryError;
use crate::memory_population::ShardPayload;

pub(super) const SCHEMA: &str = "hepta.memory.population.native.v3";
const PARTITION: &str = "hepta.memory.causal-coaccess-greedy.v1";
const TRACE_SCHEMA: &str = "hepta.memory.causal-coaccess-trace.v1";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Observation {
    sequence: u64,
    request_digest: String,
    readout_digest: String,
    addresses: Vec<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RoutingTrace {
    schema: String,
    source_cut_digest: String,
    prefix_end_sequence: u64,
    observations: Vec<Observation>,
    trace_digest: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct LearnedPopulationWire {
    schema: String,
    pub kind: MemoryCellKindV1,
    partition_profile: String,
    pub shards: Vec<ShardPayload>,
    pub routes: BTreeMap<String, usize>,
    pub lineage_sources: Vec<String>,
    routing_trace: RoutingTrace,
}

impl LearnedPopulationWire {
    pub fn validate(&self) -> Result<Digest32, AssociativeMemoryError> {
        if self.schema != SCHEMA || self.partition_profile != PARTITION
            || self.kind == MemoryCellKindV1::Event || !(1..=8).contains(&self.shards.len())
            || !(1..=512).contains(&self.routes.len()) || self.shards.len() > self.routes.len() {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        let (source_cut, frequency, edges) = self.routing_trace.counts(&self.routes)?;
        let count = self.shards.len();
        let mut capacity = vec![0_usize; count];
        for rank in 0..self.routes.len() { capacity[rank * count / self.routes.len()] += 1; }
        let mut order: Vec<_> = self.routes.keys().cloned().collect();
        order.sort_by(|left, right| frequency[right].cmp(&frequency[left]).then(left.cmp(right)));
        let mut learned: BTreeMap<String, usize> = BTreeMap::new();
        let mut sizes = vec![0_usize; count];
        let mut loads = vec![0_u64; count];
        for address in order {
            let mut affinities = vec![0_u64; count];
            for (previous, shard) in &learned {
                let pair = if address.as_str() < previous.as_str() { (address.clone(), previous.clone()) }
                    else { (previous.clone(), address.clone()) };
                affinities[*shard] += edges.get(&pair).copied().unwrap_or_default();
            }
            let selected = (0..count).filter(|index| sizes[*index] < capacity[*index])
                .max_by(|left, right| affinities[*left].cmp(&affinities[*right])
                    .then(loads[*right].cmp(&loads[*left]))
                    .then(sizes[*right].cmp(&sizes[*left]))
                    .then(right.cmp(left)))
                .ok_or(AssociativeMemoryError::InvalidArtifact)?;
            sizes[selected] += 1;
            loads[selected] += frequency[&address];
            learned.insert(address, selected);
        }
        if learned != self.routes { return Err(AssociativeMemoryError::InvalidArtifact); }
        Ok(source_cut)
    }
}

type Frequency = BTreeMap<String, u64>;
type Affinities = BTreeMap<(String, String), u64>;

impl RoutingTrace {
    fn counts(&self, routes: &BTreeMap<String, usize>) -> Result<(Digest32, Frequency, Affinities), AssociativeMemoryError> {
        if self.schema != TRACE_SCHEMA || !(1..(1_u64 << 53)).contains(&self.prefix_end_sequence)
            || !(1..=1024).contains(&self.observations.len()) {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        let source_cut = canonical_digest(&self.source_cut_digest)?;
        let mut bytes = b"hepta.memory.causal-coaccess-trace.v1\0".to_vec();
        bytes.extend_from_slice(source_cut.as_array());
        bytes.extend_from_slice(&self.prefix_end_sequence.to_be_bytes());
        bytes.extend_from_slice(&(self.observations.len() as u64).to_be_bytes());
        let mut frequency: Frequency = routes.keys().map(|address| (address.clone(), 0)).collect();
        for address in routes.keys() { canonical_digest(address)?; }
        let mut edges = Affinities::new();
        let mut requests = BTreeSet::new();
        let mut previous_sequence = 0;
        for observation in &self.observations {
            if observation.sequence <= previous_sequence || observation.sequence > self.prefix_end_sequence
                || !(1..=8).contains(&observation.addresses.len())
                || observation.addresses.windows(2).any(|pair| pair[0] >= pair[1])
                || !requests.insert(observation.request_digest.clone()) {
                return Err(AssociativeMemoryError::InvalidArtifact);
            }
            previous_sequence = observation.sequence;
            bytes.extend_from_slice(&observation.sequence.to_be_bytes());
            bytes.extend_from_slice(canonical_digest(&observation.request_digest)?.as_array());
            bytes.extend_from_slice(canonical_digest(&observation.readout_digest)?.as_array());
            bytes.extend_from_slice(&(observation.addresses.len() as u64).to_be_bytes());
            for address in &observation.addresses {
                bytes.extend_from_slice(canonical_digest(address)?.as_array());
                *frequency.get_mut(address).ok_or(AssociativeMemoryError::InvalidArtifact)? += 1;
            }
            for (index, left) in observation.addresses.iter().enumerate() {
                for right in observation.addresses.iter().skip(index + 1) {
                    *edges.entry((left.clone(), right.clone())).or_default() += 1;
                }
            }
        }
        if previous_sequence != self.prefix_end_sequence
            || Digest32::of_bytes(&bytes) != canonical_digest(&self.trace_digest)? {
            return Err(AssociativeMemoryError::BindingMismatch);
        }
        Ok((source_cut, frequency, edges))
    }
}

fn canonical_digest(value: &str) -> Result<Digest32, AssociativeMemoryError> {
    let digest: Digest32 = value.parse().map_err(|_| AssociativeMemoryError::InvalidArtifact)?;
    if digest.is_zero() || digest.to_string() != value { return Err(AssociativeMemoryError::InvalidArtifact); }
    Ok(digest)
}

#[cfg(test)]
#[path = "memory_population_learned_tests.rs"]
mod tests;
