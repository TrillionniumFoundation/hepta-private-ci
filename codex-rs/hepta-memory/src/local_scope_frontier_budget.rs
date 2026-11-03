//! Bound all source fields before the original scope reader allocates row data.
use super::*;

pub(super) const MAX_SCOPE_OPERATIONS: usize = 4096;
const MAX_SCOPE_TRANSITIONS: usize = 32768;
const MAX_SCOPE_BYTES: usize = 64 * 1024 * 1024;

pub(super) async fn preflight(
    transaction: &mut Transaction<'_, Sqlite>,
    handle: &LocalLeaseOutbox,
    scope: &Sha256Digest,
) -> Result<usize, LocalLeaseOutboxError> {
    let size = preflight_bounded(transaction, handle, scope, ScopeLimits {
        operations: MAX_SCOPE_OPERATIONS, transitions: MAX_SCOPE_TRANSITIONS, bytes: MAX_SCOPE_BYTES,
    }).await?;
    debug_assert!(size.bytes <= MAX_SCOPE_BYTES);
    Ok(size.operations)
}

struct ScopeLimits { operations: usize, transitions: usize, bytes: usize }
struct ScopeSize { operations: usize, bytes: usize }

async fn preflight_bounded(
    transaction: &mut Transaction<'_, Sqlite>, handle: &LocalLeaseOutbox,
    scope: &Sha256Digest, limits: ScopeLimits,
) -> Result<ScopeSize, LocalLeaseOutboxError> {
    // Every SQL source is a fixed literal. Runtime identity stays in bind parameters.
    let sources: [(&'static str, usize, bool); 5] = [
        ("SELECT COUNT(*), COALESCE(SUM(
                COALESCE(length(CAST(o.operation_id AS BLOB)), 0) +
                COALESCE(length(CAST(o.semantic_sha256 AS BLOB)), 0) +
                COALESCE(length(CAST(o.subject_id AS BLOB)), 0) +
                COALESCE(length(CAST(o.destination_id AS BLOB)), 0) +
                COALESCE(length(CAST(o.payload_sha256 AS BLOB)), 0) +
                COALESCE(length(CAST(o.scope_sha256 AS BLOB)), 0) +
                COALESCE(length(CAST(o.expected_predecessor_sha256 AS BLOB)), 0) +
                COALESCE(length(CAST(o.lease_id AS BLOB)), 0) +
                COALESCE(length(CAST(o.event_id AS BLOB)), 0) +
                COALESCE(length(CAST(o.outbox_id AS BLOB)), 0) +
                COALESCE(length(CAST(o.owner_agent_id AS BLOB)), 0) +
                COALESCE(length(CAST(o.fencing_token AS BLOB)), 0) + 64), 0)
             FROM cognitive_operation_ledger o
             WHERE o.lease_id = ?1 AND o.scope_sha256 = ?2", limits.operations, false),
        ("SELECT COUNT(*), COALESCE(SUM(
                COALESCE(length(CAST(e.event_id AS BLOB)), 0) +
                COALESCE(length(CAST(e.occurrence_key AS BLOB)), 0) +
                COALESCE(length(CAST(e.owner_agent_id AS BLOB)), 0) +
                COALESCE(length(CAST(e.fencing_token AS BLOB)), 0) +
                COALESCE(length(CAST(e.event_kind AS BLOB)), 0) +
                COALESCE(length(CAST(e.payload_json AS BLOB)), 0) +
                COALESCE(length(CAST(e.payload_sha256 AS BLOB)), 0) +
                COALESCE(length(CAST(e.previous_sha256 AS BLOB)), 0) +
                COALESCE(length(CAST(e.event_sha256 AS BLOB)), 0) + 64), 0)
             FROM cognitive_local_events e JOIN cognitive_operation_ledger o ON o.lease_id = e.lease_id AND o.operation_id = e.occurrence_key
             WHERE o.lease_id = ?1 AND o.scope_sha256 = ?2", MAX_SCOPE_TRANSITIONS, true),
        ("SELECT COUNT(*), COALESCE(SUM(
                COALESCE(length(CAST(b.outbox_id AS BLOB)), 0) +
                COALESCE(length(CAST(b.event_id AS BLOB)), 0) +
                COALESCE(length(CAST(b.occurrence_key AS BLOB)), 0) +
                COALESCE(length(CAST(b.owner_agent_id AS BLOB)), 0) +
                COALESCE(length(CAST(b.fencing_token AS BLOB)), 0) +
                COALESCE(length(CAST(b.topic AS BLOB)), 0) +
                COALESCE(length(CAST(b.payload_json AS BLOB)), 0) +
                COALESCE(length(CAST(b.payload_sha256 AS BLOB)), 0) +
                COALESCE(length(CAST(b.previous_sha256 AS BLOB)), 0) +
                COALESCE(length(CAST(b.outbox_sha256 AS BLOB)), 0) + 64), 0)
             FROM cognitive_local_outbox b JOIN cognitive_operation_ledger o ON o.lease_id = b.lease_id AND o.operation_id = b.occurrence_key
             WHERE o.lease_id = ?1 AND o.scope_sha256 = ?2", limits.operations, false),
        ("SELECT COUNT(*), COALESCE(SUM(
                COALESCE(length(CAST(c.fencing_token AS BLOB)), 0) +
                COALESCE(length(CAST(c.claim_state AS BLOB)), 0) +
                COALESCE(length(CAST(c.previous_sha256 AS BLOB)), 0) +
                COALESCE(length(CAST(c.claim_sha256 AS BLOB)), 0) + 64), 0)
             FROM cognitive_operation_dispatch_claims c JOIN cognitive_operation_ledger o ON o.operation_id = c.operation_id
             WHERE o.lease_id = ?1 AND o.scope_sha256 = ?2", MAX_SCOPE_TRANSITIONS, true),
        ("SELECT COUNT(*), COALESCE(SUM(
                COALESCE(length(CAST(l.owner_agent_id AS BLOB)), 0) +
                COALESCE(length(CAST(l.fencing_token AS BLOB)), 0) +
                COALESCE(length(CAST(l.state AS BLOB)), 0) +
                COALESCE(length(CAST(l.previous_sha256 AS BLOB)), 0) +
                COALESCE(length(CAST(l.lease_sha256 AS BLOB)), 0) + 64), 0)
             FROM cognitive_local_leases l
             WHERE l.lease_id = ?1 AND ?2 IS NOT NULL", MAX_LEASE_ROWS, false),
    ];
    let mut bytes = 0usize;
    let mut transitions = 0usize;
    let mut operations = 0usize;
    // 64 in each query covers the integer fields and join witness of every row.
    for (index, (query, maximum, transition)) in sources.iter().enumerate() {
        let (count, field_bytes): (i64, i64) = sqlx::query_as(*query)
            .bind(&handle.lease_id).bind(scope.as_str()).fetch_one(&mut **transaction)
            .await.map_err(crate::cognitive_store::unavailable)?;
        let count = usize::try_from(count).map_err(|_| corrupt("negative scope row count"))?;
        let field_bytes = usize::try_from(field_bytes).map_err(|_| corrupt("negative scope byte count"))?;
        require_budget(count, *maximum, "original scope source rows")?;
        bytes = bytes.checked_add(field_bytes).ok_or_else(|| corrupt("scope byte count overflow"))?;
        require_budget(bytes, limits.bytes, "original scope source bytes")?;
        if *transition {
            transitions = transitions.checked_add(count).ok_or_else(|| corrupt("scope transition count overflow"))?;
            require_budget(transitions, limits.transitions, "original scope transitions")?;
        }
        if index == 0 { operations = count; }
    }
    Ok(ScopeSize { operations, bytes })
}

pub(super) fn require_budget(value: usize, maximum: usize, resource: &'static str)
    -> Result<(), LocalLeaseOutboxError> {
    if value > maximum { return Err(LocalLeaseOutboxError::CapacityExceeded { resource, maximum }); }
    Ok(())
}

#[cfg(test)]
#[path = "local_scope_frontier_budget_tests.rs"]
mod tests;
