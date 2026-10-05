use std::collections::BTreeMap;

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::SqlitePool;

use crate::EvidenceError;
use crate::qualification::QUALIFICATION_EVIDENCE_MAX_RECEIPT_BYTES;
use crate::schema_validation::classify_sqlx_error;

const MAX_QUALIFICATION_STARTUP_ROWS: i64 = 1_000_000;
const MAX_QUALIFICATION_STARTUP_ENVELOPE_BYTES: i64 = 512 * 1024 * 1024;
const AUTHBUS_SIGNATURE_BYTES: i64 = 64;

struct RequiredObject {
    name: &'static str,
    kind: &'static str,
    table_name: &'static str,
    fragments: &'static [&'static str],
}

const REQUIRED_OPERATIONAL_OBJECTS: &[RequiredObject] = &[
    RequiredObject {
        name: "evidence_publication_owner",
        kind: "table",
        table_name: "evidence_publication_owner",
        fragments: &[
            "create table",
            "owner_generation integer not null check (owner_generation > 0)",
            "lease_expires_at_ms integer not null check (lease_expires_at_ms > 0)",
            "without rowid",
        ],
    },
    RequiredObject {
        name: "evidence_publication_owner_transition",
        kind: "trigger",
        table_name: "evidence_publication_owner",
        fragments: &[
            "before update on evidence_publication_owner",
            "new.owner_generation != old.owner_generation + 1",
            "old.lease_expires_at_ms > new.updated_at_ms",
            "invalid evidence publication owner transition",
        ],
    },
    RequiredObject {
        name: "evidence_publication_owner_no_delete",
        kind: "trigger",
        table_name: "evidence_publication_owner",
        fragments: &[
            "before delete on evidence_publication_owner",
            "evidence publication owner history cannot be deleted",
        ],
    },
    RequiredObject {
        name: "evidence_publication_batches",
        kind: "table",
        table_name: "evidence_publication_batches",
        fragments: &[
            "create table",
            "'prepared', 'dispatching', 'indeterminate', 'acknowledged'",
            "intent_count integer not null check (intent_count between 1 and 512)",
            "snapshot_sha256 text not null",
            "proposed_frontier_generation integer not null",
        ],
    },
    RequiredObject {
        name: "evidence_publication_batches_store_state_seq",
        kind: "index",
        table_name: "evidence_publication_batches",
        fragments: &["create index", "store_id, state, first_intent_seq"],
    },
    RequiredObject {
        name: "evidence_publication_batches_transition",
        kind: "trigger",
        table_name: "evidence_publication_batches",
        fragments: &[
            "before update on evidence_publication_batches",
            "old.state = 'prepared' and new.state = 'dispatching'",
            "old.state = 'dispatching' and new.state = 'indeterminate'",
            "new.state = 'acknowledged'",
            "invalid evidence publication batch transition",
        ],
    },
    RequiredObject {
        name: "evidence_publication_batches_no_delete",
        kind: "trigger",
        table_name: "evidence_publication_batches",
        fragments: &[
            "before delete on evidence_publication_batches",
            "evidence publication batches cannot be deleted",
        ],
    },
    RequiredObject {
        name: "evidence_publication_intents",
        kind: "table",
        table_name: "evidence_publication_intents",
        fragments: &[
            "create table",
            "operation_id text not null unique",
            "evidence_id text not null unique",
            "qualification_seq integer not null unique",
            "'pending', 'batched', 'acknowledged'",
        ],
    },
    RequiredObject {
        name: "evidence_publication_intents_store_state_seq",
        kind: "index",
        table_name: "evidence_publication_intents",
        fragments: &["create index", "store_id, state, qualification_seq"],
    },
    RequiredObject {
        name: "evidence_publication_intents_transition",
        kind: "trigger",
        table_name: "evidence_publication_intents",
        fragments: &[
            "before update on evidence_publication_intents",
            "old.state = 'pending' and new.state = 'batched'",
            "old.state = 'batched' and new.state = 'acknowledged'",
            "invalid evidence publication intent transition",
        ],
    },
    RequiredObject {
        name: "evidence_publication_intents_no_delete",
        kind: "trigger",
        table_name: "evidence_publication_intents",
        fragments: &[
            "before delete on evidence_publication_intents",
            "evidence publication intents cannot be deleted",
        ],
    },
    RequiredObject {
        name: "qualification_evidence_enqueue_publication",
        kind: "trigger",
        table_name: "qualification_evidence",
        fragments: &[
            "after insert on qualification_evidence",
            "insert into evidence_publication_intents",
            "'qualification:' || new.evidence_id",
        ],
    },
    RequiredObject {
        name: "evidence_recovery_identity_backfill_publication",
        kind: "trigger",
        table_name: "evidence_recovery_identity",
        fragments: &[
            "after insert on evidence_recovery_identity",
            "insert into evidence_publication_intents",
            "from qualification_evidence",
        ],
    },
    RequiredObject {
        name: "evidence_trust_acceptance",
        kind: "table",
        table_name: "evidence_trust_acceptance",
        fragments: &[
            "create table",
            "registry_generation blob not null check (length(registry_generation) = 8)",
            "registry_sha256 text not null",
            "accepted_frontier_generation blob not null",
            "unique(store_id, registry_generation)",
        ],
    },
    RequiredObject {
        name: "evidence_trust_acceptance_store_seq",
        kind: "index",
        table_name: "evidence_trust_acceptance",
        fragments: &["create index", "store_id, seq"],
    },
    RequiredObject {
        name: "evidence_trust_acceptance_no_update",
        kind: "trigger",
        table_name: "evidence_trust_acceptance",
        fragments: &[
            "before update on evidence_trust_acceptance",
            "accepted evidence trust generations are immutable",
        ],
    },
    RequiredObject {
        name: "evidence_trust_acceptance_no_delete",
        kind: "trigger",
        table_name: "evidence_trust_acceptance",
        fragments: &[
            "before delete on evidence_trust_acceptance",
            "accepted evidence trust generations cannot be deleted",
        ],
    },
];

pub(crate) async fn verify_operational_schema(pool: &SqlitePool) -> Result<(), EvidenceError> {
    verify_required_objects(pool).await?;
    verify_qualification_startup_capacity(pool).await?;
    verify_publication_rows(pool).await?;
    verify_trust_rows(pool).await
}

async fn verify_required_objects(pool: &SqlitePool) -> Result<(), EvidenceError> {
    for required in REQUIRED_OPERATIONAL_OBJECTS {
        let rows = sqlx::query("SELECT type, tbl_name, sql FROM sqlite_schema WHERE name = ?")
            .bind(required.name)
            .fetch_all(pool)
            .await
            .map_err(classify_sqlx_error)?;
        if rows.len() != 1 {
            return Err(corrupt(&format!(
                "required operational schema object {} is missing or duplicated",
                required.name
            )));
        }
        let row = &rows[0];
        let kind: String = row.try_get("type").map_err(classify_sqlx_error)?;
        let table_name: String = row.try_get("tbl_name").map_err(classify_sqlx_error)?;
        let sql: Option<String> = row.try_get("sql").map_err(classify_sqlx_error)?;
        let normalized = sql
            .ok_or_else(|| corrupt("required operational schema object has no SQL"))?
            .to_ascii_lowercase()
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ");
        if kind != required.kind || table_name != required.table_name {
            return Err(corrupt(&format!(
                "operational schema object {} has the wrong type or owner",
                required.name
            )));
        }
        for fragment in required.fragments {
            let fragment = fragment
                .to_ascii_lowercase()
                .split_whitespace()
                .collect::<Vec<_>>()
                .join(" ");
            if !normalized.contains(&fragment) {
                return Err(corrupt(&format!(
                    "operational schema object {} is missing invariant fragment: {}",
                    required.name, fragment
                )));
            }
        }
    }
    Ok(())
}

/// Bound the later canonical row reconstruction before it materializes rows.
///
/// The detailed decoder still verifies every row, digest and lineage edge. This
/// aggregate preflight ensures a syntactically valid but oversized SQLite image
/// cannot force startup to allocate an unbounded result set first.
async fn verify_qualification_startup_capacity(
    pool: &SqlitePool,
) -> Result<(), EvidenceError> {
    let row = sqlx::query(
        "SELECT COUNT(*) AS row_count,
                COALESCE(MAX(length(CAST(envelope_json AS BLOB))), 0) AS largest_envelope,
                COALESCE(SUM(length(CAST(envelope_json AS BLOB))), 0) AS envelope_bytes,
                COALESCE(MAX(CASE WHEN auth_signature IS NULL
                                  THEN 0 ELSE length(auth_signature) END), 0)
                    AS largest_signature,
                COALESCE(SUM(CASE WHEN auth_signature IS NULL
                                  THEN 0 ELSE length(auth_signature) END), 0)
                    AS signature_bytes
         FROM qualification_evidence",
    )
    .fetch_one(pool)
    .await
    .map_err(classify_sqlx_error)?;
    validate_qualification_startup_capacity(
        row.try_get("row_count").map_err(classify_sqlx_error)?,
        row.try_get("largest_envelope")
            .map_err(classify_sqlx_error)?,
        row.try_get("envelope_bytes")
            .map_err(classify_sqlx_error)?,
        row.try_get("largest_signature")
            .map_err(classify_sqlx_error)?,
        row.try_get("signature_bytes")
            .map_err(classify_sqlx_error)?,
    )
}

fn validate_qualification_startup_capacity(
    row_count: i64,
    largest_envelope: i64,
    envelope_bytes: i64,
    largest_signature: i64,
    signature_bytes: i64,
) -> Result<(), EvidenceError> {
    if row_count < 0
        || largest_envelope < 0
        || envelope_bytes < 0
        || largest_signature < 0
        || signature_bytes < 0
    {
        return Err(corrupt(
            "qualification startup capacity accounting contains a negative value",
        ));
    }
    if largest_envelope > QUALIFICATION_EVIDENCE_MAX_RECEIPT_BYTES as i64 {
        return Err(corrupt(
            "qualification startup found an envelope above the canonical receipt bound",
        ));
    }
    if largest_signature > AUTHBUS_SIGNATURE_BYTES
        || signature_bytes
            > row_count
                .checked_mul(AUTHBUS_SIGNATURE_BYTES)
                .ok_or_else(|| corrupt("qualification signature capacity overflow"))?
    {
        return Err(corrupt(
            "qualification startup found authentication signatures above the fixed-width bound",
        ));
    }
    if row_count > MAX_QUALIFICATION_STARTUP_ROWS
        || envelope_bytes > MAX_QUALIFICATION_STARTUP_ENVELOPE_BYTES
    {
        return Err(EvidenceError::Unavailable(
            "qualification startup reconstruction exceeds its row or byte budget".to_string(),
        ));
    }
    Ok(())
}

async fn verify_publication_rows(pool: &SqlitePool) -> Result<(), EvidenceError> {
    let uncovered: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM qualification_evidence AS q
         JOIN evidence_recovery_identity AS r ON r.singleton = 1
         LEFT JOIN evidence_publication_intents AS i ON i.evidence_id = q.evidence_id
         WHERE i.evidence_id IS NULL OR i.store_id != r.store_id OR i.qualification_seq != q.seq",
    )
    .fetch_one(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if uncovered != 0 {
        return Err(corrupt(
            "enrolled qualification evidence is missing its durable publication intent",
        ));
    }

    let duplicate_open: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM (
             SELECT store_id
             FROM evidence_publication_batches
             WHERE state IN ('prepared', 'dispatching', 'indeterminate')
             GROUP BY store_id HAVING COUNT(*) > 1
         )",
    )
    .fetch_one(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if duplicate_open != 0 {
        return Err(corrupt(
            "more than one unresolved publication batch exists for one store",
        ));
    }

    let mismatched_batches: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM evidence_publication_batches AS b
         WHERE b.intent_count != (
             SELECT COUNT(*) FROM evidence_publication_intents AS i
             WHERE i.batch_id = b.batch_id
         )
         OR b.first_intent_seq != (
             SELECT MIN(i.seq) FROM evidence_publication_intents AS i
             WHERE i.batch_id = b.batch_id
         )
         OR b.last_intent_seq != (
             SELECT MAX(i.seq) FROM evidence_publication_intents AS i
             WHERE i.batch_id = b.batch_id
         )
         OR EXISTS (
             SELECT 1 FROM evidence_publication_intents AS i
             WHERE i.batch_id = b.batch_id
               AND ((b.state = 'acknowledged' AND i.state != 'acknowledged')
                 OR (b.state != 'acknowledged' AND i.state != 'batched'))
         )",
    )
    .fetch_one(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if mismatched_batches != 0 {
        return Err(corrupt(
            "publication batch membership, bounds or acknowledgement state is inconsistent",
        ));
    }

    let orphaned: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM evidence_publication_intents AS i
         WHERE (i.state = 'pending' AND i.batch_id IS NOT NULL)
            OR (i.state != 'pending' AND NOT EXISTS (
                SELECT 1 FROM evidence_publication_batches AS b
                WHERE b.batch_id = i.batch_id AND b.store_id = i.store_id
            ))",
    )
    .fetch_one(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if orphaned != 0 {
        return Err(corrupt(
            "publication intent state or batch ownership is inconsistent",
        ));
    }
    Ok(())
}

async fn verify_trust_rows(pool: &SqlitePool) -> Result<(), EvidenceError> {
    let rows = sqlx::query(
        "SELECT store_id, agent_id, registry_generation, registry_sha256,
                predecessor_sha256, accepted_frontier_generation,
                accepted_frontier_sha256, backend_identity_sha256
         FROM evidence_trust_acceptance ORDER BY store_id, seq",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    let mut previous = BTreeMap::<String, (String, u64, Sha256Digest, u64, Sha256Digest)>::new();
    for row in rows {
        let store_id: String = row.try_get("store_id").map_err(classify_sqlx_error)?;
        let agent_id: String = row.try_get("agent_id").map_err(classify_sqlx_error)?;
        let generation = read_u64(&row, "registry_generation")?;
        let digest = parse_digest(&row, "registry_sha256")?;
        let predecessor = row
            .try_get::<Option<String>, _>("predecessor_sha256")
            .map_err(classify_sqlx_error)?
            .map(Sha256Digest::parse)
            .transpose()
            .map_err(EvidenceError::Corrupt)?;
        let frontier_generation = read_u64(&row, "accepted_frontier_generation")?;
        let frontier_digest = parse_digest(&row, "accepted_frontier_sha256")?;
        let backend = parse_digest(&row, "backend_identity_sha256")?;
        if let Some((old_agent, old_generation, old_digest, old_frontier, old_backend)) =
            previous.get(&store_id)
        {
            if agent_id != *old_agent
                || generation != old_generation.saturating_add(1)
                || predecessor.as_ref() != Some(old_digest)
                || frontier_generation <= *old_frontier
                || backend != *old_backend
            {
                return Err(corrupt(
                    "accepted evidence trust generations are not one monotonic predecessor chain",
                ));
            }
        } else if generation != 1 || predecessor.is_some() {
            return Err(corrupt(
                "first accepted evidence trust generation is not generation one",
            ));
        }
        let matching_frontier: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM evidence_frontier_acceptance
             WHERE store_id = ? AND frontier_generation = ?
               AND frontier_sha256 = ? AND backend_identity_sha256 = ?",
        )
        .bind(&store_id)
        .bind(frontier_generation.to_be_bytes().to_vec())
        .bind(frontier_digest.as_str())
        .bind(backend.as_str())
        .fetch_one(pool)
        .await
        .map_err(classify_sqlx_error)?;
        if matching_frontier != 1 {
            return Err(corrupt(
                "accepted trust generation is not bound to exactly one accepted frontier",
            ));
        }
        previous.insert(
            store_id,
            (agent_id, generation, digest, frontier_generation, backend),
        );
    }
    Ok(())
}

fn read_u64(row: &sqlx::sqlite::SqliteRow, column: &str) -> Result<u64, EvidenceError> {
    let bytes: Vec<u8> = row.try_get(column).map_err(classify_sqlx_error)?;
    let bytes: [u8; 8] = bytes
        .try_into()
        .map_err(|_| corrupt(&format!("{column} is not an eight-byte unsigned integer")))?;
    Ok(u64::from_be_bytes(bytes))
}

fn parse_digest(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<Sha256Digest, EvidenceError> {
    Sha256Digest::parse(
        row.try_get::<String, _>(column)
            .map_err(classify_sqlx_error)?,
    )
    .map_err(EvidenceError::Corrupt)
}

fn corrupt(message: &str) -> EvidenceError {
    EvidenceError::Corrupt(message.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn qualification_startup_capacity_accepts_exact_bounds() {
        assert!(
            validate_qualification_startup_capacity(
                MAX_QUALIFICATION_STARTUP_ROWS,
                QUALIFICATION_EVIDENCE_MAX_RECEIPT_BYTES as i64,
                MAX_QUALIFICATION_STARTUP_ENVELOPE_BYTES,
                AUTHBUS_SIGNATURE_BYTES,
                MAX_QUALIFICATION_STARTUP_ROWS * AUTHBUS_SIGNATURE_BYTES,
            )
            .is_ok()
        );
    }

    #[test]
    fn qualification_startup_capacity_rejects_resource_and_shape_overflow() {
        assert!(matches!(
            validate_qualification_startup_capacity(
                MAX_QUALIFICATION_STARTUP_ROWS + 1,
                1,
                1,
                0,
                0,
            ),
            Err(EvidenceError::Unavailable(_))
        ));
        assert!(matches!(
            validate_qualification_startup_capacity(
                1,
                QUALIFICATION_EVIDENCE_MAX_RECEIPT_BYTES as i64 + 1,
                1,
                0,
                0,
            ),
            Err(EvidenceError::Corrupt(_))
        ));
        assert!(matches!(
            validate_qualification_startup_capacity(
                1,
                1,
                1,
                AUTHBUS_SIGNATURE_BYTES + 1,
                AUTHBUS_SIGNATURE_BYTES + 1,
            ),
            Err(EvidenceError::Corrupt(_))
        ));
    }
}
