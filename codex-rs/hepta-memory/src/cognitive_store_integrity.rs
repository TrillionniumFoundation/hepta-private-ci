//! Bounded content verification and exact memory search-index validation.

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::SqliteConnection;
use sqlx::SqlitePool;

use super::CognitiveStoreError;
use super::unavailable;
use crate::cognitive_model::CognitiveScope;
use crate::cognitive_model::LedgerSourceKind;
use crate::cognitive_model::MAX_MEMORY_BYTES;
use crate::cognitive_model::MAX_SOURCE_BYTES;
use crate::cognitive_model::MemoryLifecycleState;
use crate::cognitive_model::MemoryVerification;
use crate::cognitive_model::SourceEventId;
use crate::cognitive_model::StableMemoryId;

pub(super) async fn verify_ledger_contents(pool: &SqlitePool) -> Result<(), CognitiveStoreError> {
    let mut transaction = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(unavailable)?;
    super::verify_schema_snapshot(&mut transaction).await?;
    verify_admitted_ledger_contents(&mut transaction).await?;
    transaction.commit().await.map_err(unavailable)?;
    Ok(())
}

/// Verify stable Source, Memory, citation and memory-search state inside an
/// already admitted schema and bounded snapshot. The caller holds its existing
/// write fence because FTS integrity checking uses a verification-only INSERT.
/// These tables have retained their definitions since migration 0001, so the
/// same checks also reject corrupt historical evidence before migrations can
/// replace old KG projections. This does not validate historical KG semantics.
pub(super) async fn verify_admitted_ledger_contents(
    connection: &mut SqliteConnection,
) -> Result<(), CognitiveStoreError> {
    verify_admitted_metadata(connection).await?;
    // Table names are compiled identifiers. Bound each row before fetching its
    // content. Eight source rows use at most 8 MiB; 64 memory rows use at most
    // 4 MiB and reduce query overhead for large histories of 64-KiB memories.
    for (table, maximum, page_size) in [
        ("source_ledger", MAX_SOURCE_BYTES, 8_i64),
        ("memory_revisions", MAX_MEMORY_BYTES, 64_i64),
    ] {
        let mut bounds = sqlx::QueryBuilder::<sqlx::Sqlite>::new("SELECT EXISTS(SELECT 1 FROM ");
        bounds
            .push(table)
            .push(" WHERE length(CAST(content AS BLOB)) NOT BETWEEN 1 AND ")
            .push_bind(i64::try_from(maximum).map_err(unavailable)?)
            .push(")");
        let oversized: bool = bounds
            .build_query_scalar()
            .fetch_one(&mut *connection)
            .await
            .map_err(unavailable)?;
        if oversized {
            return Err(CognitiveStoreError::Corrupt(format!(
                "{table} content exceeds its durable row bounds"
            )));
        }
        let mut after_rowid: Option<i64> = None;
        loop {
            let mut page = sqlx::QueryBuilder::<sqlx::Sqlite>::new(
                "SELECT rowid, CAST(content AS BLOB) AS content, content_sha256 FROM ",
            );
            page.push(table);
            if let Some(after_rowid) = after_rowid {
                page.push(" WHERE rowid > ").push_bind(after_rowid);
            }
            page.push(" ORDER BY rowid LIMIT ").push_bind(page_size);
            let rows = page
                .build()
                .fetch_all(&mut *connection)
                .await
                .map_err(unavailable)?;
            if rows.is_empty() {
                break;
            }
            for row in rows {
                let content: &[u8] = row.try_get("content").map_err(unavailable)?;
                if table == "memory_revisions" && std::str::from_utf8(content).is_err() {
                    return Err(CognitiveStoreError::Corrupt(
                        "memory_revisions content is not valid UTF-8".to_string(),
                    ));
                }
                let digest: &str = row.try_get("content_sha256").map_err(unavailable)?;
                if Sha256Digest::for_bytes(content).as_str() != digest {
                    return Err(CognitiveStoreError::Corrupt(format!(
                        "{table} content digest failed canonical recomputation"
                    )));
                }
                after_rowid = Some(row.try_get("rowid").map_err(unavailable)?);
            }
        }
    }
    let invalid_history: bool = sqlx::query_scalar(
        "SELECT EXISTS(
             SELECT 1 FROM memory_revisions r
             LEFT JOIN memory_revisions p
               ON p.memory_id = r.memory_id AND p.revision = r.revision - 1
             WHERE (r.revision = 1 AND r.supersedes_revision IS NOT NULL)
                OR (r.revision > 1 AND r.supersedes_revision IS NOT (r.revision - 1))
                OR (r.revision > 1 AND (
                    p.memory_id IS NULL OR r.scope_kind IS NOT p.scope_kind
                    OR r.workspace_sha256 IS NOT p.workspace_sha256
                    OR (p.lifecycle = 'tombstoned' AND r.lifecycle = 'active')
                )) LIMIT 1
         )",
    )
    .fetch_one(&mut *connection)
    .await
    .map_err(unavailable)?;
    if invalid_history {
        return Err(CognitiveStoreError::Corrupt(
            "memory revision history violates predecessor, scope, or tombstone continuity"
                .to_string(),
        ));
    }
    let invalid_heads: bool = sqlx::query_scalar(
        "SELECT EXISTS(
             SELECT 1 FROM memory_revisions m
             LEFT JOIN memory_heads h ON h.memory_id = m.memory_id
             WHERE h.memory_id IS NULL OR h.revision < m.revision LIMIT 1
         )",
    )
    .fetch_one(&mut *connection)
    .await
    .map_err(unavailable)?;
    if invalid_heads {
        return Err(CognitiveStoreError::Corrupt(
            "current memory heads do not identify every latest immutable revision".to_string(),
        ));
    }
    let invalid_citations: bool = sqlx::query_scalar(
        "SELECT EXISTS(
             SELECT 1 FROM memory_revisions r
             LEFT JOIN memory_citations c
               ON c.memory_id = r.memory_id AND c.memory_revision = r.revision
             GROUP BY r.memory_id, r.revision
             HAVING COUNT(c.ordinal) NOT BETWEEN 1 AND 32
                OR MIN(c.ordinal) != 0 OR MAX(c.ordinal) != COUNT(c.ordinal) - 1
         )",
    )
    .fetch_one(&mut *connection)
    .await
    .map_err(unavailable)?;
    if invalid_citations {
        return Err(CognitiveStoreError::Corrupt(
            "memory citations are missing, excessive, or non-contiguous".to_string(),
        ));
    }
    verify_admitted_citation_scope(connection).await?;
    let invalid_fts: bool = sqlx::query_scalar(
        "SELECT
             (SELECT COUNT(*) FROM memory_fts) !=
             (SELECT COUNT(*) FROM memory_revisions)
             OR EXISTS(
                 SELECT 1 FROM memory_fts
                 WHERE typeof(memory_id) != 'text' OR typeof(revision) != 'integer'
                    OR typeof(content) != 'text' LIMIT 1
             ) OR EXISTS(
                 SELECT 1 FROM memory_fts f
                 LEFT JOIN memory_revisions r
                   ON r.memory_id = f.memory_id AND r.revision = f.revision
                 WHERE r.memory_id IS NULL OR f.content IS NOT r.content
             ) OR EXISTS(
                 SELECT 1 FROM memory_fts
                 GROUP BY memory_id, revision HAVING COUNT(*) != 1
             )",
    )
    .fetch_one(&mut *connection)
    .await
    .map_err(unavailable)?;
    if invalid_fts {
        return Err(CognitiveStoreError::Corrupt(
            "memory FTS rows do not exactly match immutable memory revisions".to_string(),
        ));
    }
    // Independently verify the FTS5 inverted index against its content rows.
    // This special command performs verification, never repair.
    sqlx::query("INSERT INTO memory_fts(memory_fts) VALUES ('integrity-check')")
        .execute(&mut *connection)
        .await
        .map_err(|error| {
            CognitiveStoreError::Corrupt(format!("memory FTS index integrity failed: {error}"))
        })?;
    Ok(())
}

/// SQLite CHECKs accept NULL, and FTS has no column affinities. Validate the
/// stable typed API contracts independently, bounding every text field before
/// materializing a page. Historical memory:v1 IDs retain their original grammar.
async fn verify_admitted_metadata(
    connection: &mut SqliteConnection,
) -> Result<(), CognitiveStoreError> {
    for (table, id_column, fields) in [
        (
            "source_ledger",
            "source_id",
            &[("source_kind", 32, false)][..],
        ),
        (
            "memory_revisions",
            "memory_id",
            &[
                ("verification", 16, false),
                ("lifecycle", 16, false),
                ("tombstone_reason", 256, true),
            ][..],
        ),
    ] {
        let mut bounds = sqlx::QueryBuilder::<sqlx::Sqlite>::new("SELECT EXISTS(SELECT 1 FROM ");
        bounds.push(table).push(" WHERE ");
        for (index, (column, maximum, optional)) in [
            (id_column, 74, false),
            ("scope_kind", 17, false),
            ("workspace_sha256", 64, true),
            ("content_sha256", 64, false),
        ]
        .iter()
        .chain(fields)
        .enumerate()
        {
            if index > 0 {
                bounds.push(" OR ");
            }
            if *optional {
                bounds.push("(").push(column).push(" IS NOT NULL AND (");
            } else {
                bounds.push("(");
            }
            bounds
                .push("typeof(")
                .push(column)
                .push(") != 'text' OR length(CAST(")
                .push(column)
                .push(" AS BLOB)) > ")
                .push_bind(*maximum);
            bounds.push(if *optional { "))" } else { ")" });
        }
        bounds.push(" LIMIT 1)");
        let invalid: bool = bounds
            .build_query_scalar()
            .fetch_one(&mut *connection)
            .await
            .map_err(unavailable)?;
        if invalid {
            return Err(CognitiveStoreError::Corrupt(format!(
                "{table} typed metadata exceeds durable bounds or has the wrong storage type"
            )));
        }
        let metadata_error = |error| {
            CognitiveStoreError::Corrupt(format!("{table} has invalid typed metadata: {error}"))
        };
        let mut after_rowid: Option<i64> = None;
        loop {
            let mut page = sqlx::QueryBuilder::<sqlx::Sqlite>::new("SELECT rowid, ");
            page.push(id_column)
                .push(" AS stable_id, scope_kind, workspace_sha256, content_sha256");
            for (column, _, _) in fields {
                page.push(", ").push(column);
            }
            page.push(" FROM ").push(table);
            if let Some(after_rowid) = after_rowid {
                page.push(" WHERE rowid > ").push_bind(after_rowid);
            }
            page.push(" ORDER BY rowid LIMIT 64");
            let rows = page
                .build()
                .fetch_all(&mut *connection)
                .await
                .map_err(unavailable)?;
            if rows.is_empty() {
                break;
            }
            for row in rows {
                let id: String = row
                    .try_get("stable_id")
                    .map_err(|error| metadata_error(error.to_string()))?;
                let kind: &str = row
                    .try_get("scope_kind")
                    .map_err(|error| metadata_error(error.to_string()))?;
                let workspace: Option<String> = row
                    .try_get("workspace_sha256")
                    .map_err(|error| metadata_error(error.to_string()))?;
                CognitiveScope::parse(kind, workspace).map_err(&metadata_error)?;
                let digest: String = row
                    .try_get("content_sha256")
                    .map_err(|error| metadata_error(error.to_string()))?;
                Sha256Digest::parse(digest).map_err(&metadata_error)?;
                if table == "source_ledger" {
                    SourceEventId::parse(id).map_err(&metadata_error)?;
                    let kind: &str = row
                        .try_get("source_kind")
                        .map_err(|error| metadata_error(error.to_string()))?;
                    LedgerSourceKind::parse(kind).map_err(&metadata_error)?;
                } else {
                    if let Some(digest) = id.strip_prefix("memory:v1:") {
                        Sha256Digest::parse(digest.to_string()).map_err(&metadata_error)?;
                    } else {
                        StableMemoryId::parse(id).map_err(&metadata_error)?;
                    }
                    let verification: &str = row
                        .try_get("verification")
                        .map_err(|error| metadata_error(error.to_string()))?;
                    MemoryVerification::parse(verification).map_err(&metadata_error)?;
                    let lifecycle: &str = row
                        .try_get("lifecycle")
                        .map_err(|error| metadata_error(error.to_string()))?;
                    let reason: Option<String> = row
                        .try_get("tombstone_reason")
                        .map_err(|error| metadata_error(error.to_string()))?;
                    if reason
                        .as_ref()
                        .is_some_and(|reason| reason.trim().is_empty())
                    {
                        return Err(metadata_error("tombstone reason is blank".to_string()));
                    }
                    MemoryLifecycleState::parse(lifecycle, reason).map_err(&metadata_error)?;
                }
                after_rowid = Some(row.try_get("rowid").map_err(unavailable)?);
            }
        }
    }
    Ok(())
}

pub(super) async fn verify_admitted_citation_scope(
    connection: &mut SqliteConnection,
) -> Result<(), CognitiveStoreError> {
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
    Ok(())
}

#[cfg(test)]
#[path = "cognitive_store_integrity_tests.rs"]
mod tests;
