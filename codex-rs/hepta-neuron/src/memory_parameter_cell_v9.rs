//! Internal compatibility adapter for catalog and byte-output parameter cells.

use std::collections::BTreeMap;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;

use crate::ASSOCIATIVE_MEMORY_NUMERIC_PROFILE_V1;
use crate::AssociativeMemoryCellV1;
use crate::AssociativeMemoryError;
use crate::AssociativeMemoryPredictionV1;
use crate::memory_byte_cell_v9::MEMORY_BYTE_NUMERIC_PROFILE_V9;
use crate::memory_byte_cell_v9::MemoryByteCellV9;
use crate::memory_population_cost::ShardCost;

pub(super) enum MemoryParameterCellV9 {
    Catalog(AssociativeMemoryCellV1),
    Bytes(MemoryByteCellV9),
}

impl MemoryParameterCellV9 {
    pub fn from_bytes(bytes: &[u8], expected: Digest32) -> Result<Self, AssociativeMemoryError> {
        #[derive(Deserialize)]
        struct Header { schema: String }
        let header: Header = serde_json::from_slice(bytes)
            .map_err(|_| AssociativeMemoryError::InvalidArtifact)?;
        if header.schema == crate::memory_byte_cell_v9::SCHEMA {
            Ok(Self::Bytes(MemoryByteCellV9::from_bytes(bytes, expected)?))
        } else {
            Ok(Self::Catalog(AssociativeMemoryCellV1::from_bytes(bytes, expected)?))
        }
    }

    pub fn kind(&self) -> MemoryCellKindV1 {
        match self { Self::Catalog(cell) => cell.kind(), Self::Bytes(cell) => cell.kind() }
    }
    pub fn parameters_digest(&self) -> Digest32 {
        match self { Self::Catalog(cell) => cell.parameters_digest(), Self::Bytes(cell) => cell.parameters_digest() }
    }
    pub fn head_digest(&self) -> Digest32 {
        match self { Self::Catalog(cell) => cell.head_digest(), Self::Bytes(cell) => cell.head_digest() }
    }
    pub fn supports(&self) -> &BTreeMap<String, Vec<String>> {
        match self { Self::Catalog(cell) => cell.supports(), Self::Bytes(cell) => cell.supports() }
    }
    pub fn lineage_sources(&self) -> &[String] {
        match self { Self::Catalog(cell) => cell.lineage_sources(), Self::Bytes(cell) => cell.lineage_sources() }
    }
    pub fn numeric_profile(&self) -> &'static str {
        match self { Self::Catalog(_) => ASSOCIATIVE_MEMORY_NUMERIC_PROFILE_V1, Self::Bytes(_) => MEMORY_BYTE_NUMERIC_PROFILE_V9 }
    }
    pub fn cost(&self) -> Result<ShardCost, AssociativeMemoryError> {
        match self { Self::Catalog(cell) => ShardCost::of_catalog(cell), Self::Bytes(cell) => cell.cost() }
    }
    pub fn predict(&self, key: &str) -> Result<AssociativeMemoryPredictionV1, AssociativeMemoryError> {
        match self { Self::Catalog(cell) => cell.predict(key), Self::Bytes(cell) => cell.predict(key) }
    }
}
