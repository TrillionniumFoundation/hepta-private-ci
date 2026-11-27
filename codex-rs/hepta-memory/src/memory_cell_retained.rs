//! Closed decoding of retained claims, not source admission. Callers must still
//! use the live writer's authorize/admit APIs to check the actual durable owner.

use codex_hepta_cognitive_types::hnmf::MemoryEventV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Deserializer;
use serde::de::Error;

use super::MemoryCellSourceClaimV1;
use super::MemoryCellSourceError;
use super::ProductionCognitiveMutationReceiptV1;
use crate::CognitiveProjectionReceipt;
use crate::CognitiveScope;
use crate::CognitiveWriteReceipt;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionId;
use crate::MemoryRevisionRecord;
use crate::MemoryVerification;
use crate::ProjectionGeneration;
use crate::SourceEventId;
use crate::SourceRevisionId;
use crate::StableMemoryId;

/// Decode at most 1 MiB using owner-local validated constructors. A successful
/// round trip proves a bounded, self-consistent claim, never authorization.
pub fn decode_retained_memory_cell_source_claim_v1(
    input: &[u8],
) -> Result<MemoryCellSourceClaimV1, MemoryCellSourceError> {
    let invalid = MemoryCellSourceError::Invalid;
    if input.len() > 1_048_576 {
        return Err(invalid("retained claim exceeds bound"));
    }
    let wire: ClaimWire =
        serde_json::from_slice(input).map_err(|_| invalid("retained claim schema"))?;
    let claim = MemoryCellSourceClaimV1 {
        event: wire.event,
        production: wire.production,
    };
    let r = &claim.production;
    let m = &r.write.memory;
    let p = &r.write.projection;
    if [
        r.authority_epoch,
        r.owner_epoch,
        r.generation,
        m.id.revision,
        r.write.source.revision,
    ]
    .iter()
    .any(|v| *v == 0 || *v > i64::MAX as u64)
        || r.source_observed_at_unix_seconds < 0
        || m.valid_from_unix_seconds < 0
        || m.valid_to_unix_seconds
            .is_some_and(|v| v <= m.valid_from_unix_seconds)
        || m.supersedes_revision
            .is_some_and(|v| v == 0 || v >= m.id.revision)
        || r.expected_predecessor_revision
            .is_some_and(|v| v == 0 || v >= m.id.revision)
        || m.content.len() > 65_536
        || m.citations.len() != 1
        || [p.entity_count, p.relation_count, p.node_count, p.edge_count]
            .iter()
            .any(|v| *v > i64::MAX as u64)
        || r.mutation_kind.is_empty()
        || r.mutation_kind.len() > 128
        || [
            &r.lease_id,
            &r.provenance_event_id,
            &r.provenance_outbox_id,
            &r.provenance_commit_event_id,
        ]
        .iter()
        .any(|v| v.is_empty() || v.len() > 256 || v.chars().any(char::is_control))
    {
        return Err(invalid("retained claim field bounds"));
    }
    claim
        .event
        .validate()
        .map_err(|_| invalid("retained HNMF event"))?;
    r.validate()?;
    let original: serde_json::Value =
        serde_json::from_slice(input).map_err(|_| invalid("retained claim JSON"))?;
    let reconstructed = serde_json::json!({"event": claim.event, "production": claim.production});
    if original != reconstructed {
        return Err(invalid("retained claim does not round trip exactly"));
    }
    Ok(claim)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ClaimWire {
    event: MemoryEventV1,
    #[serde(with = "ReceiptWire")]
    production: ProductionCognitiveMutationReceiptV1,
}

#[derive(Deserialize)]
#[serde(remote = "ProductionCognitiveMutationReceiptV1", deny_unknown_fields)]
struct ReceiptWire {
    schema_version: u32,
    namespace: String,
    mutation_kind: String,
    operation_digest: Sha256Digest,
    input_payload_sha256: Sha256Digest,
    source_content_sha256: Sha256Digest,
    source_observed_at_unix_seconds: i64,
    expected_predecessor_revision: Option<u64>,
    owner_agent_id: AgentId,
    authority_grant_digest: Sha256Digest,
    authority_epoch: u64,
    owner_epoch: u64,
    lease_id: String,
    generation: u64,
    provenance_event_id: String,
    provenance_outbox_id: String,
    provenance_commit_event_id: String,
    write_digest: Sha256Digest,
    #[serde(with = "WriteWire")]
    write: CognitiveWriteReceipt,
    receipt_sha256: Sha256Digest,
    external_effect: bool,
}

#[derive(Deserialize)]
#[serde(remote = "CognitiveWriteReceipt", deny_unknown_fields)]
struct WriteWire {
    #[serde(with = "MemoryWire")]
    memory: MemoryRevisionRecord,
    #[serde(with = "SourceWire")]
    source: SourceRevisionId,
    #[serde(with = "ProjectionWire")]
    projection: CognitiveProjectionReceipt,
}

#[derive(Deserialize)]
#[serde(remote = "MemoryRevisionRecord", deny_unknown_fields)]
struct MemoryWire {
    #[serde(with = "MemoryIdWire")]
    id: MemoryRevisionId,
    #[serde(with = "ScopeWire")]
    scope: CognitiveScope,
    content: String,
    content_sha256: Sha256Digest,
    #[serde(deserialize_with = "verification")]
    verification: MemoryVerification,
    #[serde(with = "LifecycleWire")]
    lifecycle: MemoryLifecycleState,
    valid_from_unix_seconds: i64,
    valid_to_unix_seconds: Option<i64>,
    supersedes_revision: Option<u64>,
    #[serde(deserialize_with = "citations")]
    citations: Vec<SourceRevisionId>,
}

#[derive(Deserialize)]
#[serde(remote = "MemoryRevisionId", deny_unknown_fields)]
struct MemoryIdWire {
    #[serde(deserialize_with = "memory_id")]
    memory_id: StableMemoryId,
    revision: u64,
}

#[derive(Deserialize)]
#[serde(remote = "SourceRevisionId", deny_unknown_fields)]
struct SourceWire {
    #[serde(deserialize_with = "source_id")]
    source_id: SourceEventId,
    #[serde(deserialize_with = "positive_counter")]
    revision: u64,
}

#[derive(Deserialize)]
#[serde(remote = "CognitiveProjectionReceipt", deny_unknown_fields)]
struct ProjectionWire {
    #[serde(deserialize_with = "generation")]
    generation: ProjectionGeneration,
    fact_set_sha256: Sha256Digest,
    input_heads_sha256: Sha256Digest,
    output_sha256: Sha256Digest,
    generation_sha256: Sha256Digest,
    publication_sha256: Sha256Digest,
    entity_count: u64,
    relation_count: u64,
    node_count: u64,
    edge_count: u64,
}

#[derive(Deserialize)]
#[serde(
    remote = "CognitiveScope",
    tag = "scope",
    rename_all = "snake_case",
    deny_unknown_fields
)]
enum ScopeWire {
    AgentPrivate,
    WorkspacePrivate { workspace_sha256: Sha256Digest },
}

#[derive(Deserialize)]
#[serde(
    remote = "MemoryLifecycleState",
    tag = "state",
    rename_all = "snake_case",
    deny_unknown_fields
)]
enum LifecycleWire {
    Active,
    Tombstoned { reason: String },
}

fn positive_counter<'de, D: Deserializer<'de>>(d: D) -> Result<u64, D::Error> {
    let value = u64::deserialize(d)?;
    if value == 0 || value > i64::MAX as u64 {
        return Err(D::Error::custom("invalid retained counter"));
    }
    Ok(value)
}

fn generation<'de, D: Deserializer<'de>>(d: D) -> Result<ProjectionGeneration, D::Error> {
    positive_counter(d).map(ProjectionGeneration)
}

fn source_id<'de, D: Deserializer<'de>>(d: D) -> Result<SourceEventId, D::Error> {
    SourceEventId::parse(String::deserialize(d)?).map_err(D::Error::custom)
}

fn memory_id<'de, D: Deserializer<'de>>(d: D) -> Result<StableMemoryId, D::Error> {
    StableMemoryId::parse(String::deserialize(d)?).map_err(D::Error::custom)
}

fn verification<'de, D: Deserializer<'de>>(d: D) -> Result<MemoryVerification, D::Error> {
    MemoryVerification::parse(&String::deserialize(d)?).map_err(D::Error::custom)
}

fn citations<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<SourceRevisionId>, D::Error> {
    #[derive(Deserialize)]
    struct Source(#[serde(with = "SourceWire")] SourceRevisionId);
    let values = Vec::<Source>::deserialize(d)?;
    if values.len() != 1 {
        return Err(D::Error::custom("one retained citation required"));
    }
    Ok(values.into_iter().map(|v| v.0).collect())
}

#[cfg(test)]
#[path = "memory_cell_retained_tests.rs"]
mod tests;
