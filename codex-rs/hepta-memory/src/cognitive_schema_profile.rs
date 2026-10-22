//! Compiled historical schema profiles; no caller-supplied oracle or SQL.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::SqlitePool;

use super::super::CognitiveRecoveryAnchor;
use super::super::CognitiveRecoveryError;
use super::super::PROFILE;
use super::super::capture_profile;
use crate::cognitive_store::MIGRATOR;
use crate::cognitive_store::REQUIRED_SCHEMA_OBJECTS;
use crate::cognitive_store::REQUIRED_SCHEMA_ORACLE_SHA256;
use crate::framing::frame_part;

const ORACLE_15: &str = "046f23bab5d4c779735c762159c79e61cfe3a6a8a35e18ff8ec4f40e5c4e2be2";
const ORACLE_16: &str = "58b210d8065a05856a1e18ad37342a7b65b0f542909b85b1a7683c78e72db1e5";
// Immutable snapshot of the schema object registry at 935aaaff, migration 0015.
const OBJECTS_15: &[(&str, &str)] = &[
    ("shared_experience_use_events", "table"),
    ("shared_experience_use_no_update", "trigger"),
    ("shared_experience_use_no_delete", "trigger"),
    ("shared_experience_use_consumer_lookup", "index"),
    ("cognitive_meta", "table"),
    ("cognitive_meta_no_update", "trigger"),
    ("cognitive_meta_no_delete", "trigger"),
    ("source_ledger", "table"),
    ("source_ledger_no_update", "trigger"),
    ("source_ledger_no_delete", "trigger"),
    ("memory_revisions", "table"),
    ("memory_revisions_no_update", "trigger"),
    ("memory_revisions_no_delete", "trigger"),
    ("memory_citations", "table"),
    ("memory_citations_no_update", "trigger"),
    ("memory_citations_no_delete", "trigger"),
    ("memory_heads", "table"),
    ("memory_fts", "table"),
    ("kg_projection", "table"),
    ("kg_nodes", "table"),
    ("kg_edges", "table"),
    ("kg_entity_fts", "table"),
    ("memory_federation_events", "table"),
    ("memory_federation_events_no_update", "trigger"),
    ("memory_federation_events_no_delete", "trigger"),
    ("memory_federation_heads", "table"),
    ("memory_federation_consumer_heads", "index"),
    ("kg_revision_fact_sets", "table"),
    ("kg_revision_fact_sets_no_update", "trigger"),
    ("kg_revision_fact_sets_no_delete", "trigger"),
    ("kg_revision_entities", "table"),
    ("kg_revision_entities_declared_count", "trigger"),
    ("kg_revision_entities_no_update", "trigger"),
    ("kg_revision_entities_no_delete", "trigger"),
    ("kg_revision_entities_canonical_lookup", "index"),
    ("kg_revision_entities_citation_lookup", "index"),
    ("kg_revision_relations", "table"),
    ("kg_revision_relations_declared_count", "trigger"),
    ("kg_revision_relations_no_update", "trigger"),
    ("kg_revision_relations_no_delete", "trigger"),
    ("kg_revision_relations_from_entity_lookup", "index"),
    ("kg_revision_relations_to_entity_lookup", "index"),
    ("kg_revision_relations_canonical_lookup", "index"),
    ("kg_revision_relations_citation_lookup", "index"),
    ("kg_projection_generation_receipts", "table"),
    ("kg_projection_generation_receipts_scope_match", "trigger"),
    (
        "kg_projection_generation_receipts_fact_counts_match",
        "trigger",
    ),
    ("kg_projection_generation_receipts_no_update", "trigger"),
    ("kg_projection_generation_receipts_no_delete", "trigger"),
    ("kg_projection_generation_receipts_trigger_lookup", "index"),
    (
        "kg_projection_generation_receipts_scope_memory_generation",
        "index",
    ),
    ("kg_projection_generation_semantics", "table"),
    ("kg_projection_generation_semantics_no_update", "trigger"),
    ("kg_projection_generation_semantics_no_delete", "trigger"),
    ("kg_projection_generation_semantics_digest_lookup", "index"),
    ("kg_projection_current_semantics_on_update", "trigger"),
    ("kg_projection_generation_storage", "table"),
    ("kg_projection_generation_storage_no_update", "trigger"),
    ("kg_projection_generation_storage_no_delete", "trigger"),
    ("kg_projection_generation_storage_counts_match", "trigger"),
    ("kg_revision_entity_fts", "table"),
    ("kg_projection_node_entities", "table"),
    ("kg_projection_node_entities_no_update", "trigger"),
    ("kg_projection_node_entities_no_delete", "trigger"),
    ("kg_projection_node_entities_canonical_lookup", "index"),
    ("kg_nodes_no_update", "trigger"),
    ("kg_nodes_no_delete", "trigger"),
    ("kg_edges_no_update", "trigger"),
    ("kg_edges_no_delete", "trigger"),
    ("kg_projection_no_delete", "trigger"),
    ("kg_projection_scope_no_update", "trigger"),
    ("kg_projection_generation_monotonic", "trigger"),
    ("kg_projection_current_receipt_on_insert", "trigger"),
    ("kg_projection_current_receipt_on_update", "trigger"),
    ("cognitive_compact_events", "table"),
    ("cognitive_compact_events_no_update", "trigger"),
    ("cognitive_compact_events_no_delete", "trigger"),
    ("cognitive_compact_events_owner_lookup", "index"),
    ("cognitive_compact_events_lease_binding", "index"),
    ("cognitive_local_leases", "table"),
    ("cognitive_local_leases_no_update", "trigger"),
    ("cognitive_local_leases_no_delete", "trigger"),
    ("cognitive_local_leases_one_active", "index"),
    ("cognitive_local_leases_owner_lookup", "index"),
    ("cognitive_local_events", "table"),
    ("cognitive_local_events_no_update", "trigger"),
    ("cognitive_local_events_no_delete", "trigger"),
    ("cognitive_local_events_admission_occurrence", "index"),
    ("cognitive_local_events_transition_kind", "index"),
    ("cognitive_local_events_owner_lookup", "index"),
    ("cognitive_local_outbox", "table"),
    ("cognitive_local_outbox_no_update", "trigger"),
    ("cognitive_local_outbox_no_delete", "trigger"),
    ("cognitive_local_outbox_owner_lookup", "index"),
    ("cognitive_local_outbox_occurrence_lookup", "index"),
    ("cognitive_h7_trajectory_events", "table"),
    ("cognitive_h7_trajectory_events_no_update", "trigger"),
    ("cognitive_h7_trajectory_events_no_delete", "trigger"),
    (
        "cognitive_h7_trajectory_events_observation_guard",
        "trigger",
    ),
    ("cognitive_h7_trajectory_events_trajectory_lookup", "index"),
    ("cognitive_h7_trajectory_events_turn_lookup", "index"),
    ("cognitive_h7_trajectory_events_lease_binding", "index"),
    ("cognitive_h7_trajectory_events_causal_lookup", "index"),
    ("cognitive_h7_trajectory_events_occurrence_lookup", "index"),
    ("cognitive_h7_trajectory_events_receipt_lookup", "index"),
    ("cognitive_h7_trajectory_events_kind_lookup", "index"),
    ("cognitive_logical_turns", "table"),
    ("cognitive_logical_turns_no_update", "trigger"),
    ("cognitive_logical_turns_no_delete", "trigger"),
    ("cognitive_logical_turn_attempts", "table"),
    ("cognitive_logical_turn_attempts_no_update", "trigger"),
    ("cognitive_logical_turn_attempts_no_delete", "trigger"),
    ("cognitive_logical_turn_attempts_record_digest", "index"),
    ("cognitive_logical_turn_attempts_lookup", "index"),
    ("cognitive_logical_turn_attempts_attempt_lookup", "index"),
    ("cognitive_logical_turn_attempts_lease_lookup", "index"),
    ("cognitive_logical_turn_attempts_journal_lookup", "index"),
    ("cognitive_logical_turn_attempts_trajectory_lookup", "index"),
    ("cognitive_operation_ledger", "table"),
    ("cognitive_operation_ledger_no_update", "trigger"),
    ("cognitive_operation_ledger_no_delete", "trigger"),
    ("cognitive_operation_ledger_destination_lookup", "index"),
    ("cognitive_operation_ledger_lease_lookup", "index"),
    ("cognitive_operation_dispatch_claims", "table"),
    ("cognitive_operation_dispatch_claims_no_update", "trigger"),
    ("cognitive_operation_dispatch_claims_no_delete", "trigger"),
    ("cognitive_operation_dispatch_claims_active_lookup", "index"),
    ("cognitive_operation_dispatch_claims_expiry_lookup", "index"),
];
const OBJECTS_16_ADDITIONS: &[(&str, &str)] = &[
    ("cognitive_memory_cell_checkpoints", "table"),
    ("cognitive_memory_cell_checkpoints_no_update", "trigger"),
    ("cognitive_memory_cell_checkpoints_no_delete", "trigger"),
    ("cognitive_memory_cell_heads", "table"),
    ("cognitive_memory_cell_heads_no_delete", "trigger"),
    ("cognitive_memory_cell_heads_monotonic", "trigger"),
];

pub(super) struct SchemaProfile {
    pub(super) version: i64,
    pub(super) oracle: &'static str,
    pub(super) objects: Vec<(&'static str, &'static str)>,
}

pub(super) fn historical(
    anchor: &CognitiveRecoveryAnchor,
) -> Result<SchemaProfile, CognitiveRecoveryError> {
    if anchor.profile != PROFILE {
        return Err(CognitiveRecoveryError::Invalid(
            "unsupported historical recovery profile".into(),
        ));
    }
    let mut objects = OBJECTS_15.to_vec();
    let (version, oracle) = match anchor.schema_digest.as_str() {
        ORACLE_15 => (15, ORACLE_15),
        ORACLE_16 => {
            objects.extend_from_slice(OBJECTS_16_ADDITIONS);
            (16, ORACLE_16)
        }
        _ => {
            return Err(CognitiveRecoveryError::Invalid(
                "schema is not an approved upgrade predecessor".into(),
            ));
        }
    };
    Ok(SchemaProfile {
        version,
        oracle,
        objects,
    })
}

pub(super) fn current() -> Result<SchemaProfile, CognitiveRecoveryError> {
    let version = MIGRATOR.iter().last().map(|migration| migration.version);
    // Future migrations require an explicit upgrade-policy review.
    let Some(version @ (16 | 17)) = version else {
        return Err(CognitiveRecoveryError::Invalid(
            "compiled upgrade target is not approved".into(),
        ));
    };
    Ok(SchemaProfile {
        version,
        oracle: REQUIRED_SCHEMA_ORACLE_SHA256,
        objects: REQUIRED_SCHEMA_OBJECTS.to_vec(),
    })
}

pub(super) fn plan_digest(
    old: &SchemaProfile,
    new: &SchemaProfile,
) -> Result<Sha256Digest, CognitiveRecoveryError> {
    if old.version >= new.version {
        return Err(CognitiveRecoveryError::Invalid(
            "upgrade must advance an approved schema version".into(),
        ));
    }
    let mut hash = Sha256::new();
    frame_part(&mut hash, b"hepta:cognitive:schema-upgrade-plan:v1");
    for profile in [old, new] {
        frame_part(&mut hash, &profile.version.to_be_bytes());
        frame_part(&mut hash, profile.oracle.as_bytes());
    }
    // Bind the entire compiled lineage, not only the newly applied suffix.
    for migration in MIGRATOR
        .iter()
        .filter(|migration| migration.version <= new.version)
    {
        frame_part(&mut hash, &migration.version.to_be_bytes());
        frame_part(&mut hash, migration.description.as_bytes());
        frame_part(&mut hash, &migration.checksum);
    }
    Ok(Sha256Digest::from_sha256_output(hash.finalize()))
}

pub(super) async fn capture_verified(
    pool: &SqlitePool,
    owner: &AgentId,
    profile: &SchemaProfile,
) -> Result<CognitiveRecoveryAnchor, CognitiveRecoveryError> {
    let mut tx = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(indeterminate)?;
    // The shared bounded capture checks every table (including the ledger),
    // complete logical schema, current tombstones, quick_check and foreign keys.
    let anchor = capture_profile(&mut tx, owner, &profile.objects, profile.oracle)
        .await
        .map_err(indeterminate)?;
    let rows = sqlx::query("SELECT version, description, success, checksum FROM _sqlx_migrations ORDER BY version LIMIT 18")
        .fetch_all(&mut *tx).await.map_err(indeterminate)?;
    let compiled: Vec<_> = MIGRATOR
        .iter()
        .filter(|migration| migration.version <= profile.version)
        .collect();
    if rows.len() != compiled.len() || compiled.len() != profile.version as usize {
        return Err(CognitiveRecoveryError::Indeterminate(
            "historical migration ledger is not the exact compiled prefix".into(),
        ));
    }
    for (row, migration) in rows.iter().zip(compiled) {
        if row.try_get::<i64, _>("version").map_err(indeterminate)? != migration.version
            || row
                .try_get::<String, _>("description")
                .map_err(indeterminate)?
                != migration.description.as_ref()
            || !row.try_get::<bool, _>("success").map_err(indeterminate)?
            || row
                .try_get::<Vec<u8>, _>("checksum")
                .map_err(indeterminate)?
                .as_slice()
                != migration.checksum.as_ref()
        {
            return Err(CognitiveRecoveryError::Indeterminate(
                "historical migration ledger checksum or identity differs".into(),
            ));
        }
    }
    let integrity: Vec<String> = sqlx::query_scalar("PRAGMA integrity_check(1)")
        .fetch_all(&mut *tx)
        .await
        .map_err(indeterminate)?;
    if integrity != ["ok"] {
        return Err(CognitiveRecoveryError::Indeterminate(
            "schema upgrade image failed SQLite integrity_check".into(),
        ));
    }
    tx.commit().await.map_err(indeterminate)?;
    Ok(anchor)
}

pub(super) fn indeterminate(error: impl std::fmt::Display) -> CognitiveRecoveryError {
    CognitiveRecoveryError::Indeterminate(error.to_string())
}
