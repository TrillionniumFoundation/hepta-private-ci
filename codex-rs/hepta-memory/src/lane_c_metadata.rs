//! Fixed-width SQLite metadata admission before Lane C TEXT projection.

use sqlx::SqliteConnection;

use crate::CognitiveStoreError;
use crate::cognitive_store::unavailable;

// Reject oversized/corrupt metadata inside the read transaction before any
// TEXT is materialized in Rust, including the page's global head-digest scan.
// SQL returns only a fixed-width flag; invalid rows are never silently filtered.
pub(crate) async fn validate_scope_metadata(
    connection: &mut SqliteConnection,
    owner: &str,
    scope: &str,
    workspace: Option<&str>,
) -> Result<(), CognitiveStoreError> {
    // Bundled SQLite 3.51.3 optimizes octet_length(Column) through
    // OPFLAG_BYTELENARG: unlike CAST(TEXT AS BLOB), it uses the cell byte
    // length without fetching oversized TEXT. CASE enforces lazy cap checks.
    // Shared indexes span workspaces. Cap their normative StableId join keys
    // globally before even a bounded scoped lookup can encounter an oversized
    // overflow index key. No ledger content/body is selected by these guards.
    for query in [
        "SELECT EXISTS (SELECT 1 FROM memory_revisions r WHERE octet_length(r.memory_id) NOT BETWEEN 1 AND 128)",
        "SELECT EXISTS (SELECT 1 FROM source_ledger s WHERE octet_length(s.source_id) NOT BETWEEN 1 AND 128)",
        "SELECT EXISTS (SELECT 1 FROM memory_citations c WHERE octet_length(c.memory_id) NOT BETWEEN 1 AND 128 OR octet_length(c.source_id) NOT BETWEEN 1 AND 128)",
        "SELECT EXISTS (SELECT 1 FROM memory_heads h WHERE octet_length(h.memory_id) NOT BETWEEN 1 AND 128)",
    ] {
        let invalid: i64 = sqlx::query_scalar(query)
            .fetch_one(&mut *connection)
            .await
            .map_err(unavailable)?;
        if invalid != 0 {
            return Err(CognitiveStoreError::Corrupt(
                "Lane C metadata boundary rejected oversized, malformed or unauthorized metadata"
                    .to_string(),
            ));
        }
    }
    // This physical database has one admitted agent owner. Cap its filtering
    // columns without a scope/owner WHERE clause before any scoped comparison.
    // This protects projected metadata, not arbitrary SQLite/index RSS.
    for query in [
        "SELECT EXISTS (SELECT 1 FROM memory_revisions r WHERE CASE
           WHEN octet_length(r.owner_agent_id) NOT BETWEEN 1 AND 128 THEN 1
           WHEN octet_length(r.scope_kind) NOT BETWEEN 1 AND 17 THEN 1
           WHEN r.workspace_sha256 IS NOT NULL AND octet_length(r.workspace_sha256) != 64 THEN 1
           ELSE r.owner_agent_id != ? OR r.scope_kind NOT IN ('agent_private', 'workspace_private')
             OR (r.scope_kind = 'agent_private' AND r.workspace_sha256 IS NOT NULL)
             OR (r.scope_kind = 'workspace_private' AND r.workspace_sha256 IS NULL)
             OR (r.workspace_sha256 IS NOT NULL AND
                 (length(r.workspace_sha256) != 64 OR r.workspace_sha256 GLOB '*[^0-9a-f]*'))
           END)",
        "SELECT EXISTS (SELECT 1 FROM source_ledger s WHERE CASE
           WHEN octet_length(s.owner_agent_id) NOT BETWEEN 1 AND 128 THEN 1
           WHEN octet_length(s.scope_kind) NOT BETWEEN 1 AND 17 THEN 1
           WHEN s.workspace_sha256 IS NOT NULL AND octet_length(s.workspace_sha256) != 64 THEN 1
           ELSE s.owner_agent_id != ? OR s.scope_kind NOT IN ('agent_private', 'workspace_private')
             OR (s.scope_kind = 'agent_private' AND s.workspace_sha256 IS NOT NULL)
             OR (s.scope_kind = 'workspace_private' AND s.workspace_sha256 IS NULL)
             OR (s.workspace_sha256 IS NOT NULL AND
                 (length(s.workspace_sha256) != 64 OR s.workspace_sha256 GLOB '*[^0-9a-f]*'))
           END)",
    ] {
        let invalid: i64 = sqlx::query_scalar(query)
            .bind(owner)
            .fetch_one(&mut *connection)
            .await
            .map_err(unavailable)?;
        if invalid != 0 {
            return Err(CognitiveStoreError::Corrupt(
                "Lane C metadata boundary rejected oversized, malformed or unauthorized metadata"
                    .to_string(),
            ));
        }
    }
    // Head/citation rows have no independent scope. After global key/filter
    // caps, reject orphan references instead of losing them in scoped joins.
    for query in [
        "SELECT EXISTS (SELECT 1 FROM memory_heads h
         LEFT JOIN memory_revisions r ON r.memory_id = h.memory_id AND r.revision = h.revision
         WHERE r.memory_id IS NULL)",
        "SELECT EXISTS (SELECT 1 FROM memory_citations c
         LEFT JOIN memory_revisions r ON r.memory_id = c.memory_id AND r.revision = c.memory_revision
         WHERE r.memory_id IS NULL)",
    ] {
        let invalid: i64 = sqlx::query_scalar(query)
            .fetch_one(&mut *connection)
            .await
            .map_err(unavailable)?;
        if invalid != 0 {
            return Err(CognitiveStoreError::Corrupt(
                "Lane C metadata boundary rejected oversized, malformed or unauthorized metadata"
                    .to_string(),
            ));
        }
    }
    // Validate every join key first; separate queries return early before
    // ownership/head joins can materialize an oversized identifier.
    for query in [
        "SELECT EXISTS (SELECT 1 FROM memory_revisions r
         WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?
           AND CASE
             WHEN octet_length(r.memory_id) NOT BETWEEN 1 AND 128 THEN 1
             WHEN octet_length(r.content_sha256) != 64 THEN 1
             WHEN octet_length(r.verification) NOT BETWEEN 1 AND 11 THEN 1
             WHEN octet_length(r.lifecycle) NOT BETWEEN 1 AND 10 THEN 1
             ELSE length(r.content_sha256) != 64 OR r.content_sha256 GLOB '*[^0-9a-f]*'
               OR r.verification NOT IN ('verified', 'provisional')
               OR r.lifecycle NOT IN ('active', 'tombstoned')
           END)",
        "SELECT EXISTS (SELECT 1 FROM source_ledger s
         WHERE s.owner_agent_id = ? AND s.scope_kind = ? AND s.workspace_sha256 IS ?
           AND CASE
             WHEN octet_length(s.source_id) NOT BETWEEN 1 AND 128 THEN 1
             WHEN octet_length(s.content_sha256) != 64 THEN 1
             ELSE length(s.content_sha256) != 64 OR s.content_sha256 GLOB '*[^0-9a-f]*'
           END)",
        "SELECT EXISTS (SELECT 1 FROM memory_citations c
         JOIN memory_revisions r ON r.memory_id = c.memory_id AND r.revision = c.memory_revision
         WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?
           AND octet_length(c.source_id) NOT BETWEEN 1 AND 128)",
        "SELECT EXISTS (SELECT 1 FROM memory_revisions r
         LEFT JOIN memory_heads h ON h.memory_id = r.memory_id
         WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?
           AND (h.revision IS NULL
             OR h.revision != (SELECT max(latest.revision) FROM memory_revisions latest WHERE latest.memory_id = r.memory_id)
             OR NOT EXISTS (SELECT 1 FROM memory_revisions hr
               WHERE hr.memory_id = h.memory_id AND hr.revision = h.revision AND CASE
                 WHEN octet_length(hr.owner_agent_id) NOT BETWEEN 1 AND 128 THEN 0
                 WHEN octet_length(hr.scope_kind) NOT BETWEEN 1 AND 17 THEN 0
                 WHEN hr.workspace_sha256 IS NOT NULL AND octet_length(hr.workspace_sha256) != 64 THEN 0
                 ELSE hr.owner_agent_id = r.owner_agent_id AND hr.scope_kind = r.scope_kind
                   AND hr.workspace_sha256 IS r.workspace_sha256 END)))",
        "SELECT EXISTS (SELECT 1 FROM memory_citations c
         JOIN memory_revisions r ON r.memory_id = c.memory_id AND r.revision = c.memory_revision
         LEFT JOIN source_ledger s ON s.source_id = c.source_id AND s.source_revision = c.source_revision
         WHERE r.owner_agent_id = ? AND r.scope_kind = ? AND r.workspace_sha256 IS ?
           AND CASE
             WHEN s.source_id IS NULL THEN 1
             WHEN octet_length(s.owner_agent_id) NOT BETWEEN 1 AND 128 THEN 1
             WHEN octet_length(s.scope_kind) NOT BETWEEN 1 AND 17 THEN 1
             WHEN s.workspace_sha256 IS NOT NULL AND octet_length(s.workspace_sha256) != 64 THEN 1
             WHEN octet_length(s.content_sha256) != 64 THEN 1
             ELSE length(s.content_sha256) != 64 OR s.content_sha256 GLOB '*[^0-9a-f]*'
               OR s.scope_kind NOT IN ('agent_private', 'workspace_private')
               OR (s.workspace_sha256 IS NOT NULL AND
                   (length(s.workspace_sha256) != 64 OR s.workspace_sha256 GLOB '*[^0-9a-f]*'))
               OR s.owner_agent_id != r.owner_agent_id OR s.scope_kind != r.scope_kind
               OR s.workspace_sha256 IS NOT r.workspace_sha256
           END)",
    ] {
        let invalid: i64 = sqlx::query_scalar(query)
            .bind(owner).bind(scope).bind(workspace)
            .fetch_one(&mut *connection).await.map_err(unavailable)?;
        if invalid != 0 {
            return Err(CognitiveStoreError::Corrupt(
                "Lane C metadata boundary rejected oversized, malformed or unauthorized metadata".to_string(),
            ));
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "lane_c_lineage_guard_tests.rs"]
mod tests;
