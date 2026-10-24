//! Typed memory keys and value-free, owner-derived query bindings.

use codex_hepta_cognitive_types::hnmf::MemoryEventV1;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::ProductionCognitiveMutationReceiptV1;
use super::ProductionWriterError;
use crate::CognitiveStoreError;
use crate::MemoryRevisionId;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryCellRoleV1 {
    Semantic,
    Procedural,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryCellKeyV1 {
    pub role: MemoryCellRoleV1,
    pub entity: String,
    pub relation: String,
}

impl MemoryCellKeyV1 {
    pub fn validate(&self) -> Result<(), MemoryCellSourceError> {
        for (value, limit) in [(&self.entity, 256), (&self.relation, 128)] {
            if value.trim() != value
                || value.is_empty()
                || value.len() > limit
                || value.chars().any(char::is_control)
                || value.contains("<|")
            {
                return Err(MemoryCellSourceError::Invalid("typed key"));
            }
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Digest32, MemoryCellSourceError> {
        self.validate()?;
        let bytes = serde_json::to_vec(&("hepta.memory-cell.key.v1", self))
            .map_err(|_| MemoryCellSourceError::Invalid("key encoding"))?;
        Ok(Digest32::of_bytes(&bytes))
    }

    pub fn question(&self) -> Result<String, MemoryCellSourceError> {
        self.validate()?;
        Ok(format!(
            "What is the {} for {}?",
            self.relation, self.entity
        ))
    }

    pub fn stable_key(&self) -> Result<String, MemoryCellSourceError> {
        Ok(format!("memory-cell:{}", self.digest()?))
    }
}

/// The durable memory revision stores this closed structured document. Its
/// value is checked by the source owner and never copied into a read prompt.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryCellDocumentV1 {
    pub schema_version: u32,
    pub key: MemoryCellKeyV1,
    pub value: String,
}

impl MemoryCellDocumentV1 {
    pub fn validate(&self) -> Result<(), MemoryCellSourceError> {
        self.key.validate()?;
        if self.schema_version != 1
            || self.value.is_empty()
            || self.value.len() > 512
            || self.value.chars().any(char::is_control)
        {
            return Err(MemoryCellSourceError::Invalid("source document"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryCellQueryV1 {
    #[serde(serialize_with = "serialize_id", deserialize_with = "deserialize_id")]
    pub request_id: StableId,
    pub key: MemoryCellKeyV1,
    pub deadline_unix_ms: u64,
}

impl MemoryCellQueryV1 {
    pub fn digest(&self) -> Result<Digest32, MemoryCellSourceError> {
        self.key.validate()?;
        let bytes = serde_json::to_vec(&("hepta.memory-cell.query.v1", self))
            .map_err(|_| MemoryCellSourceError::Invalid("query encoding"))?;
        Ok(Digest32::of_bytes(&bytes))
    }

    pub(crate) fn validate_at(&self, now_unix_ms: u64) -> Result<(), MemoryCellSourceError> {
        self.key.validate()?;
        if self.deadline_unix_ms <= now_unix_ms
            || self.deadline_unix_ms.saturating_sub(now_unix_ms) > 300_000
        {
            return Err(MemoryCellSourceError::Invalid("query deadline"));
        }
        Ok(())
    }
}

/// These public source claims carry no authority. Admission verifies the
/// referenced immutable source, current head and production journal in SQLite.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCellSourceClaimV1 {
    pub event: MemoryEventV1,
    pub production: ProductionCognitiveMutationReceiptV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryCellSourceBindingV1 {
    pub memory: MemoryRevisionId,
    pub memory_content_sha256: Sha256Digest,
    pub source_content_sha256: Sha256Digest,
    #[serde(serialize_with = "serialize_digest")]
    pub event_digest: Digest32,
    pub production_receipt_digest: Sha256Digest,
    #[serde(serialize_with = "serialize_digest")]
    pub query_digest: Digest32,
    #[serde(serialize_with = "serialize_digest")]
    pub binding_digest: Digest32,
}

pub(super) fn serialize_digest<S: serde::Serializer>(
    value: &Digest32,
    serializer: S,
) -> Result<S::Ok, S::Error> {
    serializer.serialize_str(&value.to_string())
}

fn serialize_id<S: serde::Serializer>(value: &StableId, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_str(value.as_str())
}

fn deserialize_id<'de, D: serde::Deserializer<'de>>(deserializer: D) -> Result<StableId, D::Error> {
    StableId::new(String::deserialize(deserializer)?).map_err(serde::de::Error::custom)
}

impl MemoryCellSourceBindingV1 {
    pub(crate) fn bind(&mut self) -> Result<(), MemoryCellSourceError> {
        self.binding_digest = Digest32::ZERO;
        let bytes = serde_json::to_vec(&("hepta.memory-cell.owner-binding.v1", &self))
            .map_err(|_| MemoryCellSourceError::Invalid("binding encoding"))?;
        self.binding_digest = Digest32::of_bytes(&bytes);
        Ok(())
    }
}

#[derive(Debug, thiserror::Error)]
pub enum MemoryCellSourceError {
    #[error("memory cell rejected: {0}")]
    Invalid(&'static str),
    #[error("memory cell invocation was already admitted")]
    Replay,
    #[error(transparent)]
    Store(#[from] CognitiveStoreError),
    #[error(transparent)]
    Authority(#[from] ProductionWriterError),
}
