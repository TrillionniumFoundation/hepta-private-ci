//! Explicit payload accounting. Encoded metadata bytes are not process RSS.

use std::collections::BTreeMap;

use serde::Serialize;

use crate::AssociativeMemoryCellV1;
use crate::AssociativeMemoryError;
use crate::memory_population::ShardPayload;

#[derive(Clone, Copy)]
pub(super) struct ShardCost {
    pub parameters: u64,
    pub catalog: u64,
    pub support: u64,
    pub lineage: u64,
}

impl ShardCost {
    pub fn of(model: &AssociativeMemoryCellV1) -> Result<Self, AssociativeMemoryError> {
        let arrays = &model.model.arrays;
        Ok(Self {
            parameters: (arrays.input_weights.len()
                + arrays.hidden_bias.len()
                + arrays.output_weights.len()
                + arrays.output_bias.len()) as u64
                * 4,
            catalog: encoded_len(&model.model.catalog)?,
            support: encoded_len(model.supports())?,
            lineage: encoded_len(model.lineage_sources())?,
        })
    }
    pub fn resident_bytes(&self) -> u64 {
        self.parameters + self.catalog + self.support + self.lineage
    }
}

/// Serialized/raw/metadata categories overlap and must not be blindly summed.
/// Resident payload = f32 tensor bytes plus encoded catalog/support bytes;
/// allocator, JSON tree, lock and map overhead is explicitly not measured RSS.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
pub struct MemoryPopulationCostV2 {
    pub serialized_bytes: u64,
    pub raw_payload_bytes: u64,
    pub parameter_bytes: u64,
    pub catalog_bytes: u64,
    pub shard_support_bytes: u64,
    pub shard_lineage_bytes: u64,
    pub aggregate_support_bytes: u64,
    pub route_bytes: u64,
    pub lineage_bytes: u64,
    pub resident_parameter_bytes: u64,
    pub resident_catalog_bytes: u64,
    pub resident_support_bytes: u64,
    pub resident_lineage_bytes: u64,
    pub resident_budget_bytes: u64,
    pub resident_shards: usize,
    pub wake_count: u64,
    pub eviction_count: u64,
    pub read_count: u64,
    pub artifact_load_wall_ns: u64,
    pub read_wall_ns: u64,
    pub wake_wall_ns: u64,
}

impl MemoryPopulationCostV2 {
    pub(super) fn new(
        serialized: usize,
        shards: &[ShardPayload],
        costs: &[ShardCost],
        routes: &BTreeMap<String, usize>,
        supports: &BTreeMap<String, Vec<String>>,
        lineage: &[String],
        artifact_load_wall_ns: u64,
    ) -> Result<Self, AssociativeMemoryError> {
        Ok(Self {
            serialized_bytes: serialized as u64,
            raw_payload_bytes: shards.iter().map(|shard| shard.payload.len() as u64).sum(),
            parameter_bytes: costs.iter().map(|cost| cost.parameters).sum(),
            catalog_bytes: costs.iter().map(|cost| cost.catalog).sum(),
            shard_support_bytes: costs.iter().map(|cost| cost.support).sum(),
            shard_lineage_bytes: costs.iter().map(|cost| cost.lineage).sum(),
            aggregate_support_bytes: encoded_len(supports)?,
            route_bytes: encoded_len(routes)?,
            lineage_bytes: encoded_len(lineage)?,
            artifact_load_wall_ns,
            ..Self::default()
        })
    }
}

fn encoded_len<T: Serialize + ?Sized>(value: &T) -> Result<u64, AssociativeMemoryError> {
    serde_json::to_vec(value)
        .map(|bytes| bytes.len() as u64)
        .map_err(|_| AssociativeMemoryError::InvalidArtifact)
}
