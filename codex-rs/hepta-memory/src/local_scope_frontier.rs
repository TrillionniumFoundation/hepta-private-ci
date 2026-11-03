//! A complete, bounded read from the existing operation/event/outbox/claim owners.
//! All queries use one SQLite read transaction. No row, claim, or receipt is written.
use super::*;
use crate::operation_claims::{ObservedDispatchClaim, observe_claims};

#[path = "local_scope_frontier_budget.rs"]
mod budget;

pub(crate) struct ObservedScopeOperation {
    pub(crate) operation_id: String,
    pub(crate) subject_id: String,
    pub(crate) destination_id: String,
    pub(crate) semantic_sha256: Sha256Digest,
    pub(crate) payload_sha256: Sha256Digest,
    pub(crate) policy_generation: u64,
    pub(crate) expected_predecessor_sha256: Option<Sha256Digest>,
    pub(crate) topic: String,
    pub(crate) payload_json: String,
    pub(crate) generation: u64,
    pub(crate) fencing_token: String,
    pub(crate) admission_event_id: String,
    pub(crate) outbox_id: String,
    pub(crate) state: LocalOutcomeState,
    pub(crate) terminal_event_id: Option<String>,
    pub(crate) terminal_receipt: Option<String>,
    pub(crate) terminal_generation: Option<u64>,
    pub(crate) claims: Vec<ObservedDispatchClaim>,
}

impl LocalLeaseOutbox {
    pub(crate) async fn observe_scope(&self, scope: &Sha256Digest)
        -> Result<Vec<ObservedScopeOperation>, LocalLeaseOutboxError> {
        let mut transaction = self.store.pool.begin().await.map_err(crate::cognitive_store::unavailable)?;
        let count = budget::preflight(&mut transaction, self, scope).await?;
        let lease = self.current_lease(&mut transaction).await?;
        ensure_current_active(&lease, self)?;
        let fences = active_lease_fences(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        // Deliberately no generation or outcome filter: older, queued and
        // indeterminate rows may never disappear from a claimed complete scope.
        let ids: Vec<String> = sqlx::query_scalar(
            "SELECT operation_id FROM cognitive_operation_ledger WHERE lease_id = ? AND scope_sha256 = ? ORDER BY operation_id LIMIT 4097",
        ).bind(&self.lease_id).bind(scope.as_str()).fetch_all(&mut *transaction).await
            .map_err(crate::cognitive_store::unavailable)?;
        if ids.len() != count { return Err(corrupt("scope operation count changed during observation")); }
        let mut result = Vec::with_capacity(count);
        for operation_id in ids {
            result.push(read_operation(&mut transaction, self, scope, &fences, &operation_id).await?);
        }
        transaction.commit().await.map_err(crate::cognitive_store::unavailable)?;
        Ok(result)
    }
}

async fn read_operation(
    transaction: &mut Transaction<'_, Sqlite>,
    handle: &LocalLeaseOutbox,
    scope: &Sha256Digest,
    fences: &BTreeSet<(u64, String)>,
    operation_id: &str,
) -> Result<ObservedScopeOperation, LocalLeaseOutboxError> {
    let operation = find_operation(transaction, operation_id).await?
        .ok_or_else(|| corrupt("scope operation disappeared"))?;
    if operation.lease_id != handle.lease_id || operation.owner_agent_id != handle.owner_agent_id
        || operation.subject_id != handle.owner_agent_id.as_str() || operation.scope_sha256 != scope.as_str() {
        return Err(corrupt("scope operation belongs to another original owner"));
    }
    let admission = find_admission(transaction, &handle.lease_id, operation_id, &handle.owner_agent_id).await?
        .ok_or_else(|| corrupt("scope operation has no original admission"))?;
    let outbox = find_outbox(transaction, &handle.lease_id, operation_id, &handle.owner_agent_id).await?
        .ok_or_else(|| corrupt("scope operation has no original outbox"))?;
    verify_operation_row_incremental(&operation, &handle.lease_id, &handle.owner_agent_id, &admission, &outbox)?;
    validate_text(&outbox.payload_json, "original outbox payload", 65536)?;
    // Original authority/fence membership, not a replacement authorization.
    let bound: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_local_leases WHERE lease_id = ? AND generation = ? AND fencing_token = ?
           AND state = 'active' AND authority_epoch = ? AND owner_epoch = ?",
    ).bind(&operation.lease_id).bind(to_i64(operation.generation, "operation generation")?)
        .bind(&operation.fencing_token).bind(to_i64(operation.authority_epoch, "operation authority epoch")?)
        .bind(to_i64(operation.owner_epoch, "operation owner epoch")?).fetch_one(&mut **transaction).await
        .map_err(crate::cognitive_store::unavailable)?;
    if bound != 1 { return Err(corrupt("scope operation original authority is missing from lease history")); }
    verify_outbox_predecessor(transaction, &handle.lease_id, &outbox).await?;
    let events = sqlx::query(
        "SELECT event_sequence, event_id, occurrence_key, owner_agent_id, generation, fencing_token,
            event_kind, payload_json, payload_sha256, previous_sha256, event_sha256
         FROM cognitive_local_events WHERE lease_id = ? AND occurrence_key = ? ORDER BY event_sequence LIMIT 32769",
    ).bind(&handle.lease_id).bind(operation_id).fetch_all(&mut **transaction).await
        .map_err(crate::cognitive_store::unavailable)?;
    let mut states = BTreeMap::new();
    let mut kinds = BTreeSet::new();
    let mut latest = None;
    for row in events {
        let event = checked_event_row(&handle.lease_id, &row)?;
        if event.owner_agent_id != handle.owner_agent_id || event.occurrence_key != operation_id
            || !fences.contains(&(event.generation, event.fencing_token.clone())) {
            return Err(corrupt("scope event references a foreign owner or inactive historical fence"));
        }
        validate_text(&event.payload_json, "original event payload", 65536)?;
        verify_event_predecessor(transaction, &handle.lease_id, &event).await?;
        advance_outcome_state(&mut states, &mut kinds, operation_id, &event.kind)?;
        latest = Some(event);
    }
    let state = states.get(operation_id).copied().ok_or_else(|| corrupt("scope operation event history is missing"))?;
    let latest = latest.ok_or_else(|| corrupt("scope operation terminal history is missing"))?;
    let claims = observe_claims(transaction, operation_id).await?;
    for claim in &claims {
        if !fences.contains(&(claim.receipt.owner_generation, claim.receipt.fencing_token.clone())) {
            return Err(corrupt("scope claim has no original historical owner fence"));
        }
    }
    let terminal = matches!(latest.kind.as_str(), "reconcile_committed" | "reconcile_rejected");
    if !terminal && claims.last().is_some_and(|claim| claim.state == "settled") {
        return Err(corrupt("settled original claim has no original terminal event"));
    }
    let (terminal_event_id, terminal_receipt, terminal_generation) = if terminal {
        (Some(latest.event_id), Some(latest.payload_json), Some(latest.generation))
    } else { (None, None, None) };
    Ok(ObservedScopeOperation {
        operation_id: operation.operation_id, subject_id: operation.subject_id,
        destination_id: operation.destination_id,
        semantic_sha256: Sha256Digest::parse(operation.semantic_sha256).map_err(LocalLeaseOutboxError::Corrupt)?,
        payload_sha256: outbox.payload_sha256, policy_generation: operation.policy_generation,
        expected_predecessor_sha256: operation.expected_predecessor_sha256.map(Sha256Digest::parse)
            .transpose().map_err(LocalLeaseOutboxError::Corrupt)?,
        topic: outbox.topic, payload_json: outbox.payload_json, generation: operation.generation,
        fencing_token: operation.fencing_token, admission_event_id: admission.event_id, outbox_id: outbox.outbox_id,
        state, terminal_event_id, terminal_receipt, terminal_generation, claims,
    })
}

async fn verify_event_predecessor(transaction: &mut Transaction<'_, Sqlite>, lease_id: &str, event: &EventRow)
    -> Result<(), LocalLeaseOutboxError> {
    let matches = if event.sequence == 1 {
        i64::from(event.previous_sha256 == Sha256Digest::for_bytes(GENESIS_EVENT_SHA256))
    } else {
        sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM cognitive_local_events WHERE lease_id = ? AND event_sequence = ? AND event_sha256 = ?",
        ).bind(lease_id).bind(to_i64(event.sequence.saturating_sub(1), "previous event sequence")?)
            .bind(event.previous_sha256.as_str()).fetch_one(&mut **transaction).await
            .map_err(crate::cognitive_store::unavailable)?
    };
    if matches != 1 { return Err(corrupt("original scope event has a missing or conflicting predecessor")); }
    Ok(())
}

async fn verify_outbox_predecessor(transaction: &mut Transaction<'_, Sqlite>, lease_id: &str, outbox: &OutboxRow)
    -> Result<(), LocalLeaseOutboxError> {
    let matches = if outbox.sequence == 1 {
        i64::from(outbox.previous_sha256 == Sha256Digest::for_bytes(GENESIS_OUTBOX_SHA256))
    } else {
        sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM cognitive_local_outbox WHERE lease_id = ? AND outbox_sequence = ? AND outbox_sha256 = ?",
        ).bind(lease_id).bind(to_i64(outbox.sequence.saturating_sub(1), "previous outbox sequence")?)
            .bind(outbox.previous_sha256.as_str()).fetch_one(&mut **transaction).await
            .map_err(crate::cognitive_store::unavailable)?
    };
    let paired: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_local_outbox WHERE lease_id = ? AND occurrence_key = ?",
    ).bind(lease_id).bind(&outbox.occurrence_key).fetch_one(&mut **transaction).await
        .map_err(crate::cognitive_store::unavailable)?;
    if matches != 1 || paired != 1 { return Err(corrupt("original scope outbox pair or predecessor is not unique")); }
    Ok(())
}
