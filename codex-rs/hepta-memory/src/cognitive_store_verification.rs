//! Reopen verification through independently admitted SQLite snapshots.
//!
//! Each verifier authenticates executable schema in the same transaction as
//! its reads or integrity commands. No pool query may cross that admission cut.

use codex_hepta_contracts::AgentId;
use sqlx::Row;
use sqlx::SqliteConnection;
use sqlx::SqlitePool;

use super::CognitiveStoreError;
use super::MIGRATOR;
use super::bounded_limit;
use super::budget;
use super::integrity;
use super::schema;
use super::unavailable;
use super::verify_current_projection_contents;
use crate::cognitive_intelligence_writer::verify_revision_fact_digests;
use crate::cognitive_kg_store::MAX_PROJECTION_SCOPES;
use crate::cognitive_model::COGNITIVE_SCHEMA_VERSION;

/// Authenticate the full compiled schema and logical budget in this snapshot.
pub(crate) async fn admit_snapshot(
    connection: &mut SqliteConnection,
) -> Result<(), CognitiveStoreError> {
    let verified = schema::verify_schema(connection).await?;
    budget::verify(connection, &verified.tables).await
}

/// Authenticate before a journal verifier reads its own transaction snapshot.
pub(crate) async fn admit_journal_snapshot(
    connection: &mut SqliteConnection,
) -> Result<(), CognitiveStoreError> {
    schema::verify_schema(connection).await?;
    budget::verify_journal_snapshot(connection).await
}

pub(super) async fn verify_store(
    pool: &SqlitePool,
    owner: &AgentId,
) -> Result<(), CognitiveStoreError> {
    let mut transaction = pool.begin().await.map_err(unavailable)?;
    admit_snapshot(&mut transaction).await?;
    verify_admitted_snapshot(&mut transaction, owner).await?;
    transaction.commit().await.map_err(unavailable)?;
    // FTS integrity uses an INSERT command. Its own admitted write transaction
    // starts after the read snapshot closes, never under a competing guard.
    integrity::verify_ledger_contents(pool).await?;
    verify_revision_fact_digests(pool, owner).await?;
    verify_current_projection_contents(pool, owner).await?;
    crate::logical_turn_registry::verify_logical_turn_registry(pool, owner).await?;
    crate::local_lease_outbox::verify_local_lease_outbox(pool, owner).await?;
    crate::local_compact_executor::verify_local_compact_events(pool, owner).await?;
    Ok(())
}

// The caller retains the admitted transaction through every query below.
async fn verify_admitted_snapshot(
    connection: &mut SqliteConnection,
    owner: &AgentId,
) -> Result<(), CognitiveStoreError> {
    // Integrity PRAGMAs execute table CHECK expressions. Authenticate every
    // logical table and the migration schema before those scans run.
    let quick_check = sqlx::query_scalar::<_, String>("PRAGMA quick_check(1)")
        .fetch_all(&mut *connection)
        .await
        .map_err(unavailable)?;
    if quick_check != ["ok"] {
        return Err(CognitiveStoreError::Corrupt(
            "SQLite quick_check rejected the cognitive store".to_string(),
        ));
    }
    let foreign_key_errors = sqlx::query("SELECT 1 FROM pragma_foreign_key_check LIMIT 1")
        .fetch_optional(&mut *connection)
        .await
        .map_err(unavailable)?;
    if foreign_key_errors.is_some() {
        return Err(CognitiveStoreError::Corrupt(
            "SQLite foreign_key_check rejected the cognitive store".to_string(),
        ));
    }
    verify_migration_ledger(connection).await?;
    let row = sqlx::query(
        "SELECT schema_version, owner_agent_id FROM cognitive_meta WHERE singleton = 1",
    )
    .fetch_one(&mut *connection)
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
    .fetch_one(&mut *connection)
    .await
    .map_err(unavailable)?;
    if foreign_owned_rows != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "agent-local cognitive store contains foreign-owned source or memory rows".to_string(),
        ));
    }
    let projection_scope_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM kg_projection")
        .fetch_one(&mut *connection)
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
    .fetch_one(&mut *connection)
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
    .fetch_one(&mut *connection)
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
    .fetch_one(&mut *connection)
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
    .fetch_one(&mut *connection)
    .await
    .map_err(unavailable)?;
    if mismatched_citation_scope != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "memory citation does not match the exact owner and scope".to_string(),
        ));
    }
    let incomplete_projection_receipts: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM kg_projection_generation_receipts r
         WHERE NOT EXISTS (
             SELECT 1 FROM kg_projection_generation_storage s
             WHERE s.projection_scope = r.projection_scope
               AND s.generation = r.generation
               AND s.storage_mode = 'revision_facts_v1'
         ) AND (r.node_count != (
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
         ))",
    )
    .fetch_one(&mut *connection)
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
    .fetch_one(&mut *connection)
    .await
    .map_err(unavailable)?;
    if invalid_current_pointers != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "KG current projection pointer has no complete immutable receipt".to_string(),
        ));
    }
    Ok(())
}

async fn verify_migration_ledger(
    connection: &mut SqliteConnection,
) -> Result<(), CognitiveStoreError> {
    let ledger_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM sqlite_schema
         WHERE type = 'table' AND name = '_sqlx_migrations'",
    )
    .fetch_one(&mut *connection)
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
    .fetch_all(&mut *connection)
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
    let expected: Vec<_> = MIGRATOR
        .iter()
        .map(|migration| (migration.version, true))
        .collect();
    if migrations != expected {
        return Err(CognitiveStoreError::Corrupt(format!(
            "cognitive migration ledger is not the exact successful compiled migration set: {migrations:?}"
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

#[cfg(test)]
#[path = "cognitive_store_verification_tests.rs"]
mod tests;
