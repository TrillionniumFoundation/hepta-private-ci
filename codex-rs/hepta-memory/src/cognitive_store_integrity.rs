//! Bounded content verification and exact memory search-index validation.

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::SqlitePool;

use super::CognitiveStoreError;
use super::unavailable;
use crate::cognitive_model::MAX_MEMORY_BYTES;
use crate::cognitive_model::MAX_SOURCE_BYTES;

pub(super) async fn verify_ledger_contents(pool: &SqlitePool) -> Result<(), CognitiveStoreError> {
    let mut transaction = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(unavailable)?;
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
            .fetch_one(&mut *transaction)
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
                .fetch_all(&mut *transaction)
                .await
                .map_err(unavailable)?;
            if rows.is_empty() {
                break;
            }
            for row in rows {
                let content: &[u8] = row.try_get("content").map_err(unavailable)?;
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
    .fetch_one(&mut *transaction)
    .await
    .map_err(unavailable)?;
    if invalid_citations {
        return Err(CognitiveStoreError::Corrupt(
            "memory citations are missing, excessive, or non-contiguous".to_string(),
        ));
    }
    let invalid_fts: bool = sqlx::query_scalar(
        "SELECT
             (SELECT COUNT(*) FROM memory_fts) !=
             (SELECT COUNT(*) FROM memory_revisions)
             OR EXISTS(
                 SELECT 1 FROM memory_fts f
                 LEFT JOIN memory_revisions r
                   ON r.memory_id = f.memory_id AND r.revision = f.revision
                 WHERE r.memory_id IS NULL OR f.content IS NOT r.content
             ) OR EXISTS(
                 SELECT 1 FROM memory_fts
                 GROUP BY memory_id, revision HAVING COUNT(*) != 1
             )",
    )
    .fetch_one(&mut *transaction)
    .await
    .map_err(unavailable)?;
    if invalid_fts {
        return Err(CognitiveStoreError::Corrupt(
            "memory FTS rows do not exactly match immutable memory revisions".to_string(),
        ));
    }
    // SQLite quick_check does not validate an FTS5 inverted index against its
    // content rows. This special command performs verification, never repair.
    sqlx::query("INSERT INTO memory_fts(memory_fts) VALUES ('integrity-check')")
        .execute(&mut *transaction)
        .await
        .map_err(|error| {
            CognitiveStoreError::Corrupt(format!("memory FTS index integrity failed: {error}"))
        })?;
    transaction.commit().await.map_err(unavailable)?;
    Ok(())
}

#[cfg(test)]
#[path = "cognitive_store_integrity_tests.rs"]
mod tests;
