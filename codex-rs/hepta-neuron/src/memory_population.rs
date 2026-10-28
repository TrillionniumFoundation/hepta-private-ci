//! Bounded typed populations of independently trained associative cells.
//!
//! A population supplies address routing, never answer labels. Every shard's
//! exact support partition and complete lineage are checked before any cache
//! load. Admission, source freshness, and activation still belong to the host.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::sync::Mutex;
use std::time::Instant;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;

use crate::AssociativeMemoryCellV1;
use crate::AssociativeMemoryError;
use crate::memory_population_cache::PopulationCache;
use crate::memory_population_cost::MemoryPopulationCostV2;
use crate::memory_population_cost::ShardCost;

pub const MEMORY_POPULATION_SCHEMA_V2: &str = "hepta.memory.population.native.v2";
pub const MEMORY_POPULATION_PARTITION_V2: &str = "hepta.memory.sha256-address-rank.v1";
const MAX_POPULATION_BYTES: usize = 64 * 1024 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ShardPayload {
    pub digest: String,
    pub payload: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PopulationWire {
    schema: String,
    kind: MemoryCellKindV1,
    partition_profile: String,
    shards: Vec<ShardPayload>,
    routes: BTreeMap<String, usize>,
    lineage_sources: Vec<String>,
}

/// V1-compatible typed model or a V2 population. Prediction identity binds the
/// entire population; `shard_digests` identifies the actual parameter members.
/// Sleeping discards decoded tensors, retaining the pinned raw artifact bytes.
pub struct MemoryCellPopulationV2 {
    pub(super) kind: MemoryCellKindV1,
    pub(super) digest: Digest32,
    pub(super) parameter_digest: Digest32,
    head_digest: Digest32,
    population: bool,
    supports: BTreeMap<String, Vec<String>>,
    lineage: Vec<String>,
    pub(super) routes: BTreeMap<String, usize>,
    pub(super) shards: Vec<ShardPayload>,
    pub(super) shard_costs: Vec<ShardCost>,
    pub(super) costs: MemoryPopulationCostV2,
    pub(super) cache: Mutex<PopulationCache>,
}

impl MemoryCellPopulationV2 {
    /// V1 native bytes retain their original artifact, parameter and head
    /// digests. V2 bytes bind a checked, non-overlapping 1..=8 shard partition.
    pub fn from_bytes(bytes: &[u8], expected: Digest32) -> Result<Self, AssociativeMemoryError> {
        let started = Instant::now();
        if bytes.is_empty() || bytes.len() > MAX_POPULATION_BYTES {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        if expected.is_zero() || Digest32::of_bytes(bytes) != expected {
            return Err(AssociativeMemoryError::BindingMismatch);
        }
        #[derive(Deserialize)]
        struct Schema {
            schema: String,
        }
        let header: Schema =
            serde_json::from_slice(bytes).map_err(|_| AssociativeMemoryError::InvalidArtifact)?;
        let (kind, population, shards, routes, lineage) =
            if header.schema == "hepta.memory.associative-native.v1" {
                let model = AssociativeMemoryCellV1::from_bytes(bytes, expected)?;
                (
                    model.kind(),
                    false,
                    vec![ShardPayload {
                        digest: expected.to_string(),
                        payload: std::str::from_utf8(bytes)
                            .map_err(|_| AssociativeMemoryError::InvalidArtifact)?
                            .to_owned(),
                    }],
                    model
                        .supports()
                        .keys()
                        .map(|key| (key.clone(), 0))
                        .collect(),
                    model.lineage_sources().to_vec(),
                )
            } else {
                let wire: PopulationWire = serde_json::from_slice(bytes)
                    .map_err(|_| AssociativeMemoryError::InvalidArtifact)?;
                if wire.schema != MEMORY_POPULATION_SCHEMA_V2
                    || wire.partition_profile != MEMORY_POPULATION_PARTITION_V2
                    || !(1..=8).contains(&wire.shards.len())
                    || !(1..=4096).contains(&wire.routes.len())
                    || wire.shards.len() > wire.routes.len()
                    || wire.kind == MemoryCellKindV1::Event
                {
                    return Err(AssociativeMemoryError::InvalidArtifact);
                }
                (
                    wire.kind,
                    true,
                    wire.shards,
                    wire.routes,
                    wire.lineage_sources,
                )
            };
        let mut supports = BTreeMap::new();
        let mut sources = BTreeSet::new();
        let mut shard_costs = Vec::new();
        let mut parameter_parts = b"hepta.memory.population.parameters.v2".to_vec();
        let mut head_parts = b"hepta.memory.population.heads.v2".to_vec();
        let mut single_digests = None;
        for (index, shard) in shards.iter().enumerate() {
            let digest = shard
                .digest
                .parse()
                .map_err(|_| AssociativeMemoryError::InvalidArtifact)?;
            let model = AssociativeMemoryCellV1::from_bytes(shard.payload.as_bytes(), digest)?;
            if model.kind() != kind {
                return Err(AssociativeMemoryError::InvalidArtifact);
            }
            let declared: BTreeSet<_> = model.lineage_sources().iter().cloned().collect();
            let support_sources: BTreeSet<_> =
                model.supports().values().flatten().cloned().collect();
            if population && (declared != support_sources || !sources.is_disjoint(&declared)) {
                return Err(AssociativeMemoryError::InvalidArtifact);
            }
            for (key, support) in model.supports() {
                if routes.get(key) != Some(&index)
                    || supports.insert(key.clone(), support.clone()).is_some()
                {
                    return Err(AssociativeMemoryError::InvalidArtifact);
                }
            }
            sources.extend(declared);
            shard_costs.push(ShardCost::of(&model)?);
            parameter_parts.extend_from_slice(model.parameters_digest().as_array());
            head_parts.extend_from_slice(model.head_digest().as_array());
            single_digests = Some((model.parameters_digest(), model.head_digest()));
        }
        if routes.len() != supports.len() || lineage != sources.into_iter().collect::<Vec<_>>() {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        // Sorted SHA-256 address ranks are independent of values and training
        // labels. Reject a declared profile paired with a hand-written routing.
        if population
            && routes
                .iter()
                .enumerate()
                .any(|(rank, (_, shard))| *shard != rank * shards.len() / routes.len())
        {
            return Err(AssociativeMemoryError::InvalidArtifact);
        }
        let (parameter_digest, head_digest) = if population {
            (
                Digest32::of_bytes(&parameter_parts),
                Digest32::of_parts(&[&head_parts, expected.as_array()]),
            )
        } else {
            single_digests.ok_or(AssociativeMemoryError::InvalidArtifact)?
        };
        let costs = MemoryPopulationCostV2::new(
            bytes.len(),
            &shards,
            &shard_costs,
            &routes,
            &supports,
            &lineage,
            u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX),
        )?;
        let budget = shard_costs.iter().map(ShardCost::resident_bytes).sum();
        Ok(Self {
            kind,
            digest: expected,
            parameter_digest,
            head_digest,
            population,
            supports,
            lineage,
            routes,
            shards,
            shard_costs,
            costs,
            cache: Mutex::new(PopulationCache::new(budget)),
        })
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }
    pub fn parameters_digest(&self) -> Digest32 {
        self.parameter_digest
    }
    pub fn head_digest(&self) -> Digest32 {
        self.head_digest
    }
    pub fn kind(&self) -> MemoryCellKindV1 {
        self.kind
    }
    pub fn supports(&self) -> &BTreeMap<String, Vec<String>> {
        &self.supports
    }
    pub fn lineage_sources(&self) -> &[String] {
        &self.lineage
    }
    pub fn is_population(&self) -> bool {
        self.population
    }
    pub fn shard_count(&self) -> usize {
        self.shards.len()
    }
    pub fn serialized_bytes(&self) -> usize {
        self.costs.serialized_bytes as usize
    }
    pub fn shard_digests(&self) -> Vec<Digest32> {
        self.shards
            .iter()
            .map(|shard| Digest32::of_bytes(shard.payload.as_bytes()))
            .collect()
    }
}

#[cfg(test)]
#[path = "memory_population_tests.rs"]
mod tests;
