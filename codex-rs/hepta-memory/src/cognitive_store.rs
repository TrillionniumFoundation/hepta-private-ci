use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaAgentLayout;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

use crate::cognitive_intelligence_writer::occurrence_edge_id;
use crate::cognitive_intelligence_writer::occurrence_node_id;
use crate::cognitive_intelligence_writer::verify_revision_fact_digests;
use crate::cognitive_kg_store::MAX_PROJECTION_SCOPES;
use crate::cognitive_kg_store::MAX_SCOPE_EDGES;
use crate::cognitive_kg_store::MAX_SCOPE_HEADS;
use crate::cognitive_kg_store::MAX_SCOPE_NODES;
use crate::cognitive_kg_store::ProjectionEdge;
use crate::cognitive_kg_store::ProjectionHead;
use crate::cognitive_kg_store::ProjectionNode;
use crate::cognitive_kg_store::input_heads_digest;
use crate::cognitive_kg_store::output_digest;
use crate::cognitive_model::COGNITIVE_SCHEMA_VERSION;
use crate::cognitive_model::CognitiveAccess;
use crate::cognitive_model::CognitiveScope;
use crate::cognitive_model::MAX_SOURCE_BYTES;
use crate::cognitive_model::SourceDraft;
use crate::cognitive_model::SourceEventId;
use crate::cognitive_model::SourceRevisionId;
use crate::framing::frame_part;

#[path = "cognitive_store_recovery.rs"]
mod recovery;
pub use recovery::CognitiveRecoveryAnchor;
pub use recovery::CognitiveRecoveryRequirement;

const COGNITIVE_DB_FILENAME: &str = "cognitive_1.sqlite3";
static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

const REQUIRED_SCHEMA_OBJECTS: &[(&str, &str)] = &[
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
];
const REQUIRED_SCHEMA_ORACLE_SHA256: &str =
    "ae52b47126c510d36e89cf378a9df11f985527cea24111da7b2cf38b020cab6c";

#[derive(Debug, thiserror::Error)]
pub enum CognitiveStoreError {
    #[error("invalid cognitive record: {0}")]
    Invalid(String),
    #[error("cognitive scope denied: {0}")]
    AccessDenied(String),
    #[error("cognitive revision conflict: {0}")]
    Conflict(String),
    #[error("cognitive store is corrupt: {0}")]
    Corrupt(String),
    #[error("cognitive store is unavailable: {0}")]
    Unavailable(String),
}

#[derive(Clone)]
pub struct CognitiveStore {
    pub(crate) pool: SqlitePool,
    pub(crate) owner_agent_id: AgentId,
    path: PathBuf,
}

impl CognitiveStore {
    pub(crate) fn from_read_only_pool(
        pool: SqlitePool,
        owner_agent_id: AgentId,
        path: PathBuf,
    ) -> Self {
        Self {
            pool,
            owner_agent_id,
            path,
        }
    }

    /// Initialize or migrate the legacy store and verify its internal integrity.
    /// This entry point has no independent current-cut witness and cannot detect
    /// rollback to an internally valid old backup. Hosts requiring that guarantee
    /// must use `open_with_recovery` and never fall back here on recovery failure.
    pub async fn open(layout: &HeptaAgentLayout) -> Result<Self, CognitiveStoreError> {
        let root = layout.cognitive_root();
        create_private_directory(root)?;
        let path = root.join(COGNITIVE_DB_FILENAME);
        let sqlite_home = AbsolutePathBuf::try_from(root.to_path_buf())
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        let pool = SqliteConfig::from_sqlite_home(sqlite_home)
            .open_durable_evidence_pool(&path)
            .await
            .map_err(unavailable)?;
        MIGRATOR.run(&pool).await.map_err(classify_migrate_error)?;
        protect_database_file(&path)?;
        sqlx::query(
            "INSERT INTO cognitive_meta (singleton, schema_version, owner_agent_id)
             VALUES (1, ?, ?) ON CONFLICT(singleton) DO NOTHING",
        )
        .bind(i64::from(COGNITIVE_SCHEMA_VERSION))
        .bind(layout.agent_id().as_str())
        .execute(&pool)
        .await
        .map_err(unavailable)?;
        verify_store(&pool, layout.agent_id()).await?;
        Ok(Self {
            pool,
            owner_agent_id: layout.agent_id().clone(),
            path,
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn owner_agent_id(&self) -> &AgentId {
        &self.owner_agent_id
    }

    /// Returns whether two handles refer to the same Agent-local database and
    /// owner.  This is crate-private so composite local writers can reject a
    /// lease/executor assembled from different stores before opening a
    /// transaction.  It is not an authority or capability check.
    pub(crate) fn is_same_local_store(&self, other: &Self) -> bool {
        self.owner_agent_id == other.owner_agent_id && self.path == other.path
    }

    pub async fn append_source(
        &self,
        access: &CognitiveAccess,
        draft: &SourceDraft,
    ) -> Result<SourceRevisionId, CognitiveStoreError> {
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let source = self
            .append_source_tx(&mut transaction, access, draft)
            .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(source)
    }

    pub(crate) async fn append_source_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        draft: &SourceDraft,
    ) -> Result<SourceRevisionId, CognitiveStoreError> {
        self.authorize(access, &draft.scope)?;
        validate_key(&draft.event_key, "source event key")?;
        if draft.content.is_empty() || draft.content.len() > MAX_SOURCE_BYTES {
            return Err(CognitiveStoreError::Invalid(format!(
                "source content must contain 1..={MAX_SOURCE_BYTES} bytes"
            )));
        }
        let source_id = SourceEventId::for_event(
            &self.owner_agent_id,
            &draft.scope,
            draft.kind,
            &draft.event_key,
        );
        let content_sha256 = Sha256Digest::for_bytes(&draft.content);
        let (scope_kind, workspace_sha256) = draft.scope.database_parts();
        let recorded_at = now_unix_seconds()?;
        let insert = sqlx::query(
            "INSERT INTO source_ledger (
                source_id, source_revision, owner_agent_id, scope_kind, workspace_sha256,
                source_kind, content, content_sha256, observed_at_unix_seconds,
                recorded_at_unix_seconds
             ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(source_id, source_revision) DO NOTHING",
        )
        .bind(source_id.as_str())
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace_sha256)
        .bind(draft.kind.as_str())
        .bind(&draft.content)
        .bind(content_sha256.as_str())
        .bind(draft.observed_at_unix_seconds)
        .bind(recorded_at)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if insert.rows_affected() == 0 {
            let exact: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM source_ledger
                 WHERE source_id = ? AND source_revision = 1 AND owner_agent_id = ?
                   AND scope_kind = ? AND workspace_sha256 IS ? AND source_kind = ?
                   AND content = ? AND content_sha256 = ? AND observed_at_unix_seconds = ?",
            )
            .bind(source_id.as_str())
            .bind(self.owner_agent_id.as_str())
            .bind(scope_kind)
            .bind(workspace_sha256)
            .bind(draft.kind.as_str())
            .bind(&draft.content)
            .bind(content_sha256.as_str())
            .bind(draft.observed_at_unix_seconds)
            .fetch_one(&mut **transaction)
            .await
            .map_err(unavailable)?;
            if exact != 1 {
                return Err(CognitiveStoreError::Conflict(format!(
                    "source event {} was replayed with different content",
                    source_id.as_str()
                )));
            }
        }
        Ok(SourceRevisionId::new(source_id))
    }

    pub(crate) fn authorize(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
    ) -> Result<(), CognitiveStoreError> {
        if access.agent_id() != &self.owner_agent_id {
            return Err(CognitiveStoreError::AccessDenied(
                "cross-agent cognitive access requires an executable federation capability"
                    .to_string(),
            ));
        }
        if !scope.permits(access) {
            return Err(CognitiveStoreError::AccessDenied(
                "workspace-private cognitive record does not match the caller workspace"
                    .to_string(),
            ));
        }
        Ok(())
    }
}

pub(crate) fn validate_key(value: &str, label: &str) -> Result<(), CognitiveStoreError> {
    if value.trim().is_empty() || value.len() > 512 || value.as_bytes().contains(&0) {
        return Err(CognitiveStoreError::Invalid(format!(
            "{label} must contain 1..=512 non-NUL bytes"
        )));
    }
    Ok(())
}

pub(crate) fn decode_scope(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<CognitiveScope, CognitiveStoreError> {
    CognitiveScope::parse(
        row.try_get("scope_kind").map_err(unavailable)?,
        row.try_get("workspace_sha256").map_err(unavailable)?,
    )
    .map_err(CognitiveStoreError::Corrupt)
}

#[cfg(test)]
pub(crate) async fn open_v2_test_pool(
    layout: &HeptaAgentLayout,
) -> Result<SqlitePool, CognitiveStoreError> {
    let root = layout.cognitive_root();
    create_private_directory(root)?;
    let path = root.join(COGNITIVE_DB_FILENAME);
    let sqlite_home = AbsolutePathBuf::try_from(root.to_path_buf())
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&path)
        .await
        .map_err(unavailable)?;
    MIGRATOR
        .run_to(2, &pool)
        .await
        .map_err(classify_migrate_error)?;
    protect_database_file(&path)?;
    sqlx::query(
        "INSERT INTO cognitive_meta (singleton, schema_version, owner_agent_id)
         VALUES (1, ?, ?)",
    )
    .bind(i64::from(COGNITIVE_SCHEMA_VERSION))
    .bind(layout.agent_id().as_str())
    .execute(&pool)
    .await
    .map_err(unavailable)?;
    Ok(pool)
}

pub(crate) fn unavailable(error: impl std::fmt::Display) -> CognitiveStoreError {
    CognitiveStoreError::Unavailable(error.to_string())
}

fn classify_migrate_error(error: sqlx::migrate::MigrateError) -> CognitiveStoreError {
    let detail = error.to_string();
    match error {
        sqlx::migrate::MigrateError::VersionMissing(_)
        | sqlx::migrate::MigrateError::VersionMismatch(_)
        | sqlx::migrate::MigrateError::VersionNotPresent(_)
        | sqlx::migrate::MigrateError::Dirty(_) => CognitiveStoreError::Corrupt(detail),
        _ => CognitiveStoreError::Unavailable(detail),
    }
}

fn now_unix_seconds() -> Result<i64, CognitiveStoreError> {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
        .as_secs();
    i64::try_from(seconds)
        .map_err(|_| CognitiveStoreError::Unavailable("system clock overflow".to_string()))
}

async fn verify_store(pool: &SqlitePool, owner: &AgentId) -> Result<(), CognitiveStoreError> {
    let quick_check = sqlx::query_scalar::<_, String>("PRAGMA quick_check(1)")
        .fetch_all(pool)
        .await
        .map_err(unavailable)?;
    if quick_check != ["ok"] {
        return Err(CognitiveStoreError::Corrupt(
            "SQLite quick_check rejected the cognitive store".to_string(),
        ));
    }
    let foreign_key_errors = sqlx::query("PRAGMA foreign_key_check")
        .fetch_all(pool)
        .await
        .map_err(unavailable)?;
    if !foreign_key_errors.is_empty() {
        return Err(CognitiveStoreError::Corrupt(
            "SQLite foreign_key_check rejected the cognitive store".to_string(),
        ));
    }
    verify_migration_ledger(pool).await?;
    let mut schema_oracle_parts = Vec::with_capacity(REQUIRED_SCHEMA_OBJECTS.len());
    for (name, expected_type) in REQUIRED_SCHEMA_OBJECTS {
        let object = sqlx::query("SELECT type, sql FROM sqlite_schema WHERE name = ?")
            .bind(name)
            .fetch_optional(pool)
            .await
            .map_err(unavailable)?
            .ok_or_else(|| {
                CognitiveStoreError::Corrupt(format!(
                    "required cognitive schema object `{name}` is missing"
                ))
            })?;
        let object_type: String = object.try_get("type").map_err(unavailable)?;
        let sql: Option<String> = object.try_get("sql").map_err(unavailable)?;
        let Some(sql) = sql.filter(|value| !value.is_empty()) else {
            return Err(CognitiveStoreError::Corrupt(format!(
                "required cognitive schema object `{name}` has the wrong definition class"
            )));
        };
        if object_type != *expected_type {
            return Err(CognitiveStoreError::Corrupt(format!(
                "required cognitive schema object `{name}` has the wrong definition class"
            )));
        }
        schema_oracle_parts.push(((*name).to_string(), object_type, sql));
    }
    schema_oracle_parts.sort_by(|left, right| left.0.cmp(&right.0));
    let mut schema_hasher = Sha256::new();
    frame_part(
        &mut schema_hasher,
        b"hepta:cognitive:required-schema-oracle:v1",
    );
    frame_part(
        &mut schema_hasher,
        &u64::try_from(schema_oracle_parts.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    for (name, object_type, sql) in &schema_oracle_parts {
        frame_part(&mut schema_hasher, name.as_bytes());
        frame_part(&mut schema_hasher, object_type.as_bytes());
        frame_part(&mut schema_hasher, sql.as_bytes());
    }
    let schema_oracle = Sha256Digest::from_sha256_output(schema_hasher.finalize());
    if schema_oracle.as_str() != REQUIRED_SCHEMA_ORACLE_SHA256 {
        return Err(CognitiveStoreError::Corrupt(format!(
            "required cognitive schema definition oracle mismatch: {}",
            schema_oracle.as_str()
        )));
    }
    let row = sqlx::query(
        "SELECT schema_version, owner_agent_id FROM cognitive_meta WHERE singleton = 1",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    let schema_version: i64 = row.try_get("schema_version").map_err(unavailable)?;
    let stored_owner: String = row.try_get("owner_agent_id").map_err(unavailable)?;
    if schema_version != i64::from(COGNITIVE_SCHEMA_VERSION) {
        return Err(CognitiveStoreError::Corrupt(format!(
            "unsupported cognitive schema version {schema_version}"
        )));
    }
    if stored_owner != owner.as_str() {
        return Err(CognitiveStoreError::AccessDenied(format!(
            "cognitive database belongs to agent {stored_owner}, not {owner}"
        )));
    }
    let foreign_owned_rows: i64 = sqlx::query_scalar(
        "SELECT (
             SELECT COUNT(*) FROM source_ledger WHERE owner_agent_id != ?
         ) + (
             SELECT COUNT(*) FROM memory_revisions WHERE owner_agent_id != ?
         )",
    )
    .bind(owner.as_str())
    .bind(owner.as_str())
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if foreign_owned_rows != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "agent-local cognitive store contains foreign-owned source or memory rows".to_string(),
        ));
    }
    let projection_scope_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM kg_projection")
        .fetch_one(pool)
        .await
        .map_err(unavailable)?;
    if projection_scope_count >= bounded_limit(MAX_PROJECTION_SCOPES)? {
        return Err(CognitiveStoreError::Corrupt(format!(
            "cognitive store exceeds the {MAX_PROJECTION_SCOPES}-projection-scope limit"
        )));
    }

    let incomplete_fact_sets: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM kg_revision_fact_sets s
         WHERE s.entity_count != (
             SELECT COUNT(*) FROM kg_revision_entities e
             WHERE e.memory_id = s.memory_id
               AND e.memory_revision = s.memory_revision
         ) OR s.relation_count != (
             SELECT COUNT(*) FROM kg_revision_relations r
             WHERE r.memory_id = s.memory_id
               AND r.memory_revision = s.memory_revision
         )",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if incomplete_fact_sets != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "immutable KG fact-set receipts do not match their stored facts".to_string(),
        ));
    }
    let unbound_heads: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM memory_heads h
         LEFT JOIN kg_revision_fact_sets s
           ON s.memory_id = h.memory_id AND s.memory_revision = h.revision
         WHERE s.memory_id IS NULL",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if unbound_heads != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "current memory head is missing its explicit KG fact-set receipt".to_string(),
        ));
    }
    let invalid_fact_validity: i64 = sqlx::query_scalar(
        "SELECT (
             SELECT COUNT(*) FROM kg_revision_entities e
             JOIN memory_revisions m
               ON m.memory_id = e.memory_id AND m.revision = e.memory_revision
             WHERE e.valid_from_unix_seconds < m.valid_from_unix_seconds
                OR (m.valid_to_unix_seconds IS NOT NULL AND
                    (e.valid_to_unix_seconds IS NULL OR
                     e.valid_to_unix_seconds > m.valid_to_unix_seconds))
         ) + (
             SELECT COUNT(*) FROM kg_revision_relations r
             JOIN memory_revisions m
               ON m.memory_id = r.memory_id AND m.revision = r.memory_revision
             WHERE r.valid_from_unix_seconds < m.valid_from_unix_seconds
                OR (m.valid_to_unix_seconds IS NOT NULL AND
                    (r.valid_to_unix_seconds IS NULL OR
                     r.valid_to_unix_seconds > m.valid_to_unix_seconds))
         )",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if invalid_fact_validity != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "KG fact validity escapes its immutable memory revision".to_string(),
        ));
    }
    let mismatched_citation_scope: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM memory_citations c
         JOIN memory_revisions m
           ON m.memory_id = c.memory_id AND m.revision = c.memory_revision
         JOIN source_ledger s
           ON s.source_id = c.source_id AND s.source_revision = c.source_revision
         WHERE m.owner_agent_id != s.owner_agent_id
            OR m.scope_kind != s.scope_kind
            OR m.workspace_sha256 IS NOT s.workspace_sha256",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if mismatched_citation_scope != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "memory citation does not match the exact owner and scope".to_string(),
        ));
    }
    let incomplete_projection_receipts: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM kg_projection_generation_receipts r
         WHERE r.node_count != (
             SELECT COUNT(*) FROM kg_nodes n
             WHERE n.projection_scope = r.projection_scope
               AND n.generation = r.generation
         ) OR r.edge_count != (
             SELECT COUNT(*) FROM kg_edges e
             WHERE e.projection_scope = r.projection_scope
               AND e.generation = r.generation
         ) OR r.node_count != (
             SELECT COUNT(*) FROM kg_projection_node_entities i
             WHERE i.projection_scope = r.projection_scope
               AND i.generation = r.generation
         ) OR r.node_count != (
             SELECT COUNT(*) FROM kg_entity_fts f
             WHERE f.projection_scope = r.projection_scope
               AND f.generation = r.generation
         )",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if incomplete_projection_receipts != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "KG projection receipt does not match its nodes, edges, identities, and FTS rows"
                .to_string(),
        ));
    }
    let invalid_current_pointers: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM kg_projection p
         LEFT JOIN kg_projection_generation_receipts r
           ON r.projection_scope = p.projection_scope
          AND r.generation = p.generation
         WHERE p.generation <= 0 OR r.projection_scope IS NULL",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if invalid_current_pointers != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "KG current projection pointer has no complete immutable receipt".to_string(),
        ));
    }
    verify_revision_fact_digests(pool, owner).await?;
    verify_current_projection_contents(pool, owner).await?;
    crate::logical_turn_registry::verify_logical_turn_registry(pool, owner).await?;
    crate::local_lease_outbox::verify_local_lease_outbox(pool, owner).await?;
    crate::local_compact_executor::verify_local_compact_events(pool, owner).await?;
    Ok(())
}

async fn verify_migration_ledger(pool: &SqlitePool) -> Result<(), CognitiveStoreError> {
    let ledger_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM sqlite_schema
         WHERE type = 'table' AND name = '_sqlx_migrations'",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if ledger_count != 1 {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive migration ledger is missing".to_string(),
        ));
    }

    let rows = sqlx::query(
        "SELECT version, description, success, checksum
         FROM _sqlx_migrations ORDER BY version",
    )
    .fetch_all(pool)
    .await
    .map_err(unavailable)?;
    if rows.len() != MIGRATOR.migrations.len() {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive migration ledger is incomplete or has unknown entries".to_string(),
        ));
    }

    let migrations = rows
        .iter()
        .map(|row| {
            Ok((
                row.try_get::<i64, _>("version").map_err(unavailable)?,
                row.try_get::<bool, _>("success").map_err(unavailable)?,
            ))
        })
        .collect::<Result<Vec<_>, CognitiveStoreError>>()?;
    if migrations
        != [
            (1, true),
            (2, true),
            (3, true),
            (4, true),
            (5, true),
            (6, true),
            (7, true),
            (8, true),
            (9, true),
            (10, true),
        ]
    {
        return Err(CognitiveStoreError::Corrupt(format!(
            "cognitive migration ledger is not the exact successful 0001/0002/0003/0004/0005/0006/0007/0008/0009/0010 set: {migrations:?}"
        )));
    }

    for (row, migration) in rows.iter().zip(MIGRATOR.migrations.iter()) {
        let version: i64 = row.try_get("version").map_err(unavailable)?;
        let description: String = row.try_get("description").map_err(unavailable)?;
        let success: bool = row.try_get("success").map_err(unavailable)?;
        let checksum: Vec<u8> = row.try_get("checksum").map_err(unavailable)?;
        if version != migration.version
            || description != migration.description.as_ref()
            || !success
            || checksum.as_slice() != migration.checksum.as_ref()
        {
            return Err(CognitiveStoreError::Corrupt(format!(
                "cognitive migration ledger entry {version} does not match the current lineage"
            )));
        }
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct StoredProjectionEdge {
    edge_id: String,
    from_node_id: String,
    to_node_id: String,
    relation: String,
    valid_from: i64,
    valid_to: Option<i64>,
    memory_id: String,
    memory_revision: i64,
    source_id: String,
    source_revision: i64,
}

impl From<&ProjectionEdge> for StoredProjectionEdge {
    fn from(edge: &ProjectionEdge) -> Self {
        Self {
            edge_id: edge.edge_id.clone(),
            from_node_id: edge.from_node_id.clone(),
            to_node_id: edge.to_node_id.clone(),
            relation: edge.relation.clone(),
            valid_from: edge.valid_from,
            valid_to: edge.valid_to,
            memory_id: edge.memory_id.clone(),
            memory_revision: edge.memory_revision,
            source_id: edge.source_id.clone(),
            source_revision: edge.source_revision,
        }
    }
}

async fn verify_current_projection_contents(
    pool: &SqlitePool,
    owner: &AgentId,
) -> Result<(), CognitiveStoreError> {
    let mut transaction = pool.begin().await.map_err(unavailable)?;
    let current_rows = sqlx::query(
        "SELECT p.projection_scope, p.generation,
                r.input_heads_sha256, r.output_sha256
         FROM kg_projection p
         JOIN kg_projection_generation_receipts r
           ON r.projection_scope = p.projection_scope
          AND r.generation = p.generation
         ORDER BY p.projection_scope LIMIT ?",
    )
    .bind(bounded_limit(MAX_PROJECTION_SCOPES)?)
    .fetch_all(&mut *transaction)
    .await
    .map_err(unavailable)?;
    if current_rows.len() > MAX_PROJECTION_SCOPES {
        return Err(CognitiveStoreError::Corrupt(format!(
            "cognitive store exceeds the {MAX_PROJECTION_SCOPES}-projection-scope limit"
        )));
    }

    for current in current_rows {
        let projection_scope: String = current.try_get("projection_scope").map_err(unavailable)?;
        let generation: i64 = current.try_get("generation").map_err(unavailable)?;
        let (scope_kind, workspace_sha256) = projection_scope_database_parts(&projection_scope)?;

        let head_rows = sqlx::query(
            "SELECT r.memory_id, r.revision, r.content_sha256,
                    r.verification, r.lifecycle, s.fact_set_sha256
             FROM memory_heads h
             JOIN memory_revisions r
               ON r.memory_id = h.memory_id AND r.revision = h.revision
             JOIN kg_revision_fact_sets s
               ON s.memory_id = r.memory_id AND s.memory_revision = r.revision
             WHERE r.owner_agent_id = ? AND r.scope_kind = ?
               AND r.workspace_sha256 IS ?
             ORDER BY r.memory_id LIMIT ?",
        )
        .bind(owner.as_str())
        .bind(scope_kind)
        .bind(workspace_sha256.as_deref())
        .bind(bounded_limit(MAX_SCOPE_HEADS)?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if head_rows.len() > MAX_SCOPE_HEADS {
            return Err(CognitiveStoreError::Corrupt(format!(
                "KG projection input exceeds the {MAX_SCOPE_HEADS}-head reopen verification limit"
            )));
        }
        let heads = head_rows
            .into_iter()
            .map(|row| {
                Ok(ProjectionHead {
                    memory_id: row.try_get("memory_id").map_err(unavailable)?,
                    revision: row.try_get("revision").map_err(unavailable)?,
                    content_sha256: row.try_get("content_sha256").map_err(unavailable)?,
                    verification: row.try_get("verification").map_err(unavailable)?,
                    lifecycle: row.try_get("lifecycle").map_err(unavailable)?,
                    fact_set_sha256: row.try_get("fact_set_sha256").map_err(unavailable)?,
                })
            })
            .collect::<Result<Vec<_>, CognitiveStoreError>>()?;
        let expected_input = input_heads_digest(&projection_scope, &heads);
        let stored_input: String = current.try_get("input_heads_sha256").map_err(unavailable)?;
        if expected_input.as_str() != stored_input {
            return Err(CognitiveStoreError::Corrupt(format!(
                "KG current projection `{projection_scope}` input-head digest failed canonical recomputation"
            )));
        }

        let entity_rows = sqlx::query(
            "SELECT e.memory_id, e.memory_revision, e.entity_key,
                    e.canonical_entity_id, e.entity_type, e.label,
                    e.valid_from_unix_seconds, e.valid_to_unix_seconds,
                    e.source_id, e.source_revision
             FROM memory_heads h
             JOIN memory_revisions r
               ON r.memory_id = h.memory_id AND r.revision = h.revision
             JOIN kg_revision_entities e
               ON e.memory_id = r.memory_id AND e.memory_revision = r.revision
             WHERE r.owner_agent_id = ? AND r.scope_kind = ?
               AND r.workspace_sha256 IS ?
               AND r.verification = 'verified' AND r.lifecycle = 'active'
             ORDER BY e.memory_id, e.memory_revision, e.entity_key LIMIT ?",
        )
        .bind(owner.as_str())
        .bind(scope_kind)
        .bind(workspace_sha256.as_deref())
        .bind(bounded_limit(MAX_SCOPE_NODES)?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if entity_rows.len() > MAX_SCOPE_NODES {
            return Err(CognitiveStoreError::Corrupt(format!(
                "KG projection output exceeds the {MAX_SCOPE_NODES}-node reopen verification limit"
            )));
        }
        let mut expected_nodes = Vec::with_capacity(entity_rows.len());
        for row in entity_rows {
            let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
            let memory_revision: i64 = row.try_get("memory_revision").map_err(unavailable)?;
            let entity_key: String = row.try_get("entity_key").map_err(unavailable)?;
            expected_nodes.push(ProjectionNode {
                node_id: occurrence_node_id(&memory_id, memory_revision, &entity_key),
                canonical_entity_id: row.try_get("canonical_entity_id").map_err(unavailable)?,
                entity_type: row.try_get("entity_type").map_err(unavailable)?,
                label: row.try_get("label").map_err(unavailable)?,
                valid_from: row
                    .try_get("valid_from_unix_seconds")
                    .map_err(unavailable)?,
                valid_to: row.try_get("valid_to_unix_seconds").map_err(unavailable)?,
                memory_id,
                memory_revision,
                source_id: row.try_get("source_id").map_err(unavailable)?,
                source_revision: row.try_get("source_revision").map_err(unavailable)?,
            });
        }

        let relation_rows = sqlx::query(
            "SELECT q.memory_id, q.memory_revision, q.relation_key,
                    q.canonical_relation_id, q.from_entity_key,
                    q.to_entity_key, q.relation, q.valid_from_unix_seconds,
                    q.valid_to_unix_seconds, q.source_id, q.source_revision
             FROM memory_heads h
             JOIN memory_revisions r
               ON r.memory_id = h.memory_id AND r.revision = h.revision
             JOIN kg_revision_relations q
               ON q.memory_id = r.memory_id AND q.memory_revision = r.revision
             WHERE r.owner_agent_id = ? AND r.scope_kind = ?
               AND r.workspace_sha256 IS ?
               AND r.verification = 'verified' AND r.lifecycle = 'active'
             ORDER BY q.memory_id, q.memory_revision, q.relation_key LIMIT ?",
        )
        .bind(owner.as_str())
        .bind(scope_kind)
        .bind(workspace_sha256.as_deref())
        .bind(bounded_limit(MAX_SCOPE_EDGES)?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if relation_rows.len() > MAX_SCOPE_EDGES {
            return Err(CognitiveStoreError::Corrupt(format!(
                "KG projection output exceeds the {MAX_SCOPE_EDGES}-edge reopen verification limit"
            )));
        }
        let mut expected_edges = Vec::with_capacity(relation_rows.len());
        for row in relation_rows {
            let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
            let memory_revision: i64 = row.try_get("memory_revision").map_err(unavailable)?;
            let relation_key: String = row.try_get("relation_key").map_err(unavailable)?;
            let from_entity_key: String = row.try_get("from_entity_key").map_err(unavailable)?;
            let to_entity_key: String = row.try_get("to_entity_key").map_err(unavailable)?;
            expected_edges.push(ProjectionEdge {
                edge_id: occurrence_edge_id(&memory_id, memory_revision, &relation_key),
                canonical_relation_id: row.try_get("canonical_relation_id").map_err(unavailable)?,
                from_node_id: occurrence_node_id(&memory_id, memory_revision, &from_entity_key),
                to_node_id: occurrence_node_id(&memory_id, memory_revision, &to_entity_key),
                relation: row.try_get("relation").map_err(unavailable)?,
                valid_from: row
                    .try_get("valid_from_unix_seconds")
                    .map_err(unavailable)?,
                valid_to: row.try_get("valid_to_unix_seconds").map_err(unavailable)?,
                memory_id,
                memory_revision,
                source_id: row.try_get("source_id").map_err(unavailable)?,
                source_revision: row.try_get("source_revision").map_err(unavailable)?,
            });
        }

        let stored_node_rows = sqlx::query(
            "SELECT n.node_id, i.canonical_entity_id, n.entity_type, n.label,
                    n.valid_from_unix_seconds, n.valid_to_unix_seconds,
                    n.memory_id, n.memory_revision, n.source_id, n.source_revision
             FROM kg_nodes n
             JOIN kg_projection_node_entities i
               ON i.projection_scope = n.projection_scope
              AND i.generation = n.generation AND i.node_id = n.node_id
             WHERE n.projection_scope = ? AND n.generation = ?
             ORDER BY n.node_id LIMIT ?",
        )
        .bind(&projection_scope)
        .bind(generation)
        .bind(bounded_limit(MAX_SCOPE_NODES)?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if stored_node_rows.len() > MAX_SCOPE_NODES {
            return Err(CognitiveStoreError::Corrupt(
                "stored KG projection exceeds the node reopen verification limit".to_string(),
            ));
        }
        let mut stored_nodes = stored_node_rows
            .into_iter()
            .map(|row| {
                Ok(ProjectionNode {
                    node_id: row.try_get("node_id").map_err(unavailable)?,
                    canonical_entity_id: row.try_get("canonical_entity_id").map_err(unavailable)?,
                    entity_type: row.try_get("entity_type").map_err(unavailable)?,
                    label: row.try_get("label").map_err(unavailable)?,
                    valid_from: row
                        .try_get("valid_from_unix_seconds")
                        .map_err(unavailable)?,
                    valid_to: row.try_get("valid_to_unix_seconds").map_err(unavailable)?,
                    memory_id: row.try_get("memory_id").map_err(unavailable)?,
                    memory_revision: row.try_get("memory_revision").map_err(unavailable)?,
                    source_id: row.try_get("source_id").map_err(unavailable)?,
                    source_revision: row.try_get("source_revision").map_err(unavailable)?,
                })
            })
            .collect::<Result<Vec<_>, CognitiveStoreError>>()?;
        let mut expected_nodes_by_id = expected_nodes.clone();
        expected_nodes_by_id.sort_by(|left, right| left.node_id.cmp(&right.node_id));
        stored_nodes.sort_by(|left, right| left.node_id.cmp(&right.node_id));
        if stored_nodes != expected_nodes_by_id {
            return Err(CognitiveStoreError::Corrupt(format!(
                "KG current projection `{projection_scope}` nodes do not match current immutable fact supports"
            )));
        }

        let stored_edge_rows = sqlx::query(
            "SELECT edge_id, from_node_id, to_node_id, relation,
                    valid_from_unix_seconds, valid_to_unix_seconds,
                    memory_id, memory_revision, source_id, source_revision
             FROM kg_edges
             WHERE projection_scope = ? AND generation = ?
             ORDER BY edge_id LIMIT ?",
        )
        .bind(&projection_scope)
        .bind(generation)
        .bind(bounded_limit(MAX_SCOPE_EDGES)?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if stored_edge_rows.len() > MAX_SCOPE_EDGES {
            return Err(CognitiveStoreError::Corrupt(
                "stored KG projection exceeds the edge reopen verification limit".to_string(),
            ));
        }
        let mut stored_edges = stored_edge_rows
            .into_iter()
            .map(|row| {
                Ok(StoredProjectionEdge {
                    edge_id: row.try_get("edge_id").map_err(unavailable)?,
                    from_node_id: row.try_get("from_node_id").map_err(unavailable)?,
                    to_node_id: row.try_get("to_node_id").map_err(unavailable)?,
                    relation: row.try_get("relation").map_err(unavailable)?,
                    valid_from: row
                        .try_get("valid_from_unix_seconds")
                        .map_err(unavailable)?,
                    valid_to: row.try_get("valid_to_unix_seconds").map_err(unavailable)?,
                    memory_id: row.try_get("memory_id").map_err(unavailable)?,
                    memory_revision: row.try_get("memory_revision").map_err(unavailable)?,
                    source_id: row.try_get("source_id").map_err(unavailable)?,
                    source_revision: row.try_get("source_revision").map_err(unavailable)?,
                })
            })
            .collect::<Result<Vec<_>, CognitiveStoreError>>()?;
        let mut expected_stored_edges = expected_edges
            .iter()
            .map(StoredProjectionEdge::from)
            .collect::<Vec<_>>();
        stored_edges.sort();
        expected_stored_edges.sort();
        if stored_edges != expected_stored_edges {
            return Err(CognitiveStoreError::Corrupt(format!(
                "KG current projection `{projection_scope}` edges do not match current immutable fact supports"
            )));
        }

        let fts_rows = sqlx::query(
            "SELECT projection_scope, generation, node_id, entity_type, label
             FROM kg_entity_fts
             WHERE projection_scope = ? AND generation = ?
             ORDER BY node_id, entity_type, label LIMIT ?",
        )
        .bind(&projection_scope)
        .bind(generation)
        .bind(bounded_limit(MAX_SCOPE_NODES)?)
        .fetch_all(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if fts_rows.len() > MAX_SCOPE_NODES {
            return Err(CognitiveStoreError::Corrupt(
                "stored KG entity FTS exceeds the reopen verification limit".to_string(),
            ));
        }
        let mut stored_fts = fts_rows
            .into_iter()
            .map(|row| {
                Ok((
                    row.try_get::<String, _>("projection_scope")
                        .map_err(unavailable)?,
                    row.try_get::<i64, _>("generation").map_err(unavailable)?,
                    row.try_get::<String, _>("node_id").map_err(unavailable)?,
                    row.try_get::<String, _>("entity_type")
                        .map_err(unavailable)?,
                    row.try_get::<String, _>("label").map_err(unavailable)?,
                ))
            })
            .collect::<Result<Vec<_>, CognitiveStoreError>>()?;
        let mut expected_fts = expected_nodes
            .iter()
            .map(|node| {
                (
                    projection_scope.clone(),
                    generation,
                    node.node_id.clone(),
                    node.entity_type.clone(),
                    node.label.clone(),
                )
            })
            .collect::<Vec<_>>();
        stored_fts.sort();
        expected_fts.sort();
        if stored_fts != expected_fts {
            return Err(CognitiveStoreError::Corrupt(format!(
                "KG current projection `{projection_scope}` FTS rows do not exactly match its nodes"
            )));
        }

        let expected_output = output_digest(&projection_scope, &expected_nodes, &expected_edges);
        let stored_output: String = current.try_get("output_sha256").map_err(unavailable)?;
        if expected_output.as_str() != stored_output {
            return Err(CognitiveStoreError::Corrupt(format!(
                "KG current projection `{projection_scope}` output digest failed canonical recomputation"
            )));
        }
    }
    transaction.commit().await.map_err(unavailable)?;
    Ok(())
}

fn projection_scope_database_parts(
    projection_scope: &str,
) -> Result<(&'static str, Option<String>), CognitiveStoreError> {
    if projection_scope == "agent_private" {
        return Ok(("agent_private", None));
    }
    let workspace = projection_scope
        .strip_prefix("workspace_private:")
        .ok_or_else(|| CognitiveStoreError::Corrupt("invalid KG projection scope".to_string()))?;
    let workspace =
        Sha256Digest::parse(workspace.to_string()).map_err(CognitiveStoreError::Corrupt)?;
    Ok(("workspace_private", Some(workspace.as_str().to_string())))
}

fn bounded_limit(maximum: usize) -> Result<i64, CognitiveStoreError> {
    maximum
        .checked_add(1)
        .and_then(|value| i64::try_from(value).ok())
        .ok_or_else(|| {
            CognitiveStoreError::Corrupt("KG reopen verification limit exceeds i64".to_string())
        })
}

fn create_private_directory(path: &Path) -> Result<(), CognitiveStoreError> {
    fs::create_dir_all(path).map_err(unavailable)?;
    if path.canonicalize().map_err(unavailable)? != path {
        return Err(CognitiveStoreError::Invalid(
            "per-agent cognitive root must be canonical and must not traverse a symlink"
                .to_string(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700)).map_err(unavailable)?;
    }
    Ok(())
}

fn protect_database_file(path: &Path) -> Result<(), CognitiveStoreError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o600)).map_err(unavailable)?;
    }
    Ok(())
}
