//! Audit the retained Objective domain with the original startup/recovery path.

use super::*;
use codex_hepta_contracts::AgentId;
use sqlx::Row;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteRow;

pub(super) async fn decode_request(
    tx: &mut Transaction<'_, Sqlite>,
    row: &SqliteRow,
) -> Result<ObjectiveSenderRequest, ObjectiveSenderError> {
    let original: String = row.try_get("original_json").map_err(unavailable)?;
    let binding_json: String = row.try_get("binding_json").map_err(unavailable)?;
    let binding: Binding = serde_json::from_str(&binding_json).map_err(|_| corrupt())?;
    let request = ObjectiveSenderRequest::from_original(original, binding.origin.clone())
        .map_err(|_| corrupt())?;
    let id = &request.identity;
    if row
        .try_get::<String, _>("request_sha256")
        .map_err(unavailable)?
        != id.original_sha256.as_str()
        || row
            .try_get::<String, _>("owner_agent_id")
            .map_err(unavailable)?
            != request.origin.agent_id.as_str()
        || row.try_get::<String, _>("run_id").map_err(unavailable)? != id.run_id
        || row.try_get::<String, _>("issuer_id").map_err(unavailable)? != id.issuer_id
        || row
            .try_get::<String, _>("message_id")
            .map_err(unavailable)?
            != id.message_id
        || row.try_get::<i64, _>("key_epoch").map_err(unavailable)? != id.key_epoch as i64
        || row
            .try_get::<i64, _>("message_sequence")
            .map_err(unavailable)?
            != id.sequence as i64
        || row
            .try_get::<i64, _>("permit_sequence")
            .map_err(unavailable)?
            != 1
        || row
            .try_get::<String, _>("record_sha256")
            .map_err(unavailable)?
            != request_digest(&request.original, &binding_json).as_str()
    {
        return Err(corrupt());
    }
    verify_fence(tx, row, &binding).await?;
    Ok(request)
}

async fn verify_fence(
    tx: &mut Transaction<'_, Sqlite>,
    row: &SqliteRow,
    binding: &Binding,
) -> Result<(), ObjectiveSenderError> {
    let fence = &binding.fence;
    // Sha256Digest's transparent Deserialize does not call parse. This checks
    // retained syntax, not historical grant authentication from an opaque hash.
    for digest in [
        &fence.lease_sha256,
        &fence.authority_grant_digest,
        &fence.fencing_token_digest,
    ] {
        Sha256Digest::parse(digest.as_str()).map_err(|_| corrupt())?;
    }
    if fence.owner_agent_id != binding.origin.agent_id
        || row.try_get::<String, _>("lease_id").map_err(unavailable)? != fence.lease_id
        || row
            .try_get::<String, _>("lease_sha256")
            .map_err(unavailable)?
            != fence.lease_sha256.as_str()
    {
        return Err(corrupt());
    }
    let lease =
        sqlx::query("SELECT * FROM cognitive_local_leases WHERE lease_id = ? AND lease_sha256 = ?")
            .bind(&fence.lease_id)
            .bind(fence.lease_sha256.as_str())
            .fetch_optional(&mut **tx)
            .await
            .map_err(unavailable)?
            .ok_or_else(corrupt)?;
    if lease.try_get::<String, _>("state").map_err(unavailable)? != "active"
        || lease
            .try_get::<String, _>("owner_agent_id")
            .map_err(unavailable)?
            != fence.owner_agent_id.as_str()
        || lease.try_get::<i64, _>("generation").map_err(unavailable)? != fence.generation as i64
        || lease
            .try_get::<String, _>("fencing_token")
            .map_err(unavailable)?
            != fence.fencing_token_digest.as_str()
        || lease
            .try_get::<i64, _>("authority_epoch")
            .map_err(unavailable)?
            != fence.authority_epoch as i64
        || lease
            .try_get::<i64, _>("owner_epoch")
            .map_err(unavailable)?
            != fence.owner_epoch as i64
        || lease
            .try_get::<i64, _>("lease_expires_at_unix_seconds")
            .map_err(unavailable)?
            != fence.expires_at_unix_seconds as i64
    {
        return Err(corrupt());
    }
    Ok(())
}

pub(super) async fn read_events(
    tx: &mut Transaction<'_, Sqlite>,
    request: &ObjectiveSenderRequest,
    permit: ExistingPermit,
) -> Result<Vec<Event>, ObjectiveSenderError> {
    let key = request.identity.original_sha256.as_str();
    // Process and local lease generations are independently authenticated at
    // retention. The first permission must still carry exactly the original
    // request's complete owner/lease binding, not a different historical fence.
    let permit_binding: String = sqlx::query_scalar(
        "SELECT binding_json FROM cognitive_objective_sender_requests WHERE request_sha256 = ?",
    )
    .bind(key)
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?
    .ok_or_else(corrupt)?;
    let rows = sqlx::query("SELECT * FROM cognitive_objective_sender_events WHERE request_sha256 = ? ORDER BY event_sequence LIMIT 65")
        .bind(key).fetch_all(&mut **tx).await.map_err(unavailable)?;
    if rows.len() > MAX_EVENTS_PER_REQUEST as usize
        || (matches!(permit, ExistingPermit::Required) && rows.is_empty())
    {
        return Err(corrupt());
    }
    let mut events: Vec<Event> = Vec::new();
    for row in rows {
        let sequence: i64 = row.try_get("event_sequence").map_err(unavailable)?;
        let kind = EventKind::parse(
            &row.try_get::<String, _>("event_kind")
                .map_err(unavailable)?,
        )?;
        let observation: String = row.try_get("observation_json").map_err(unavailable)?;
        let binding_json: String = row.try_get("binding_json").map_err(unavailable)?;
        let binding: Binding = serde_json::from_str(&binding_json).map_err(|_| corrupt())?;
        let previous: String = row.try_get("previous_sha256").map_err(unavailable)?;
        let digest: String = row.try_get("event_sha256").map_err(unavailable)?;
        if sequence != events.len() as i64 + 1
            || binding.origin != request.origin
            || observation.len() > MAX_OBSERVATION_BYTES
            || previous
                != events
                    .last()
                    .map_or(ZERO_DIGEST, |event| event.digest.as_str())
            || digest
                != event_digest(
                    key,
                    sequence,
                    kind.text(),
                    &observation,
                    &binding_json,
                    &previous,
                )
                .as_str()
            || row
                .try_get::<String, _>("observation_sha256")
                .map_err(unavailable)?
                != Sha256Digest::for_bytes(observation.as_bytes()).as_str()
            || (sequence == 1
                && (kind != EventKind::PermitIssued
                    || observation != "null"
                    || binding_json != permit_binding))
            || (sequence > 1 && kind == EventKind::PermitIssued)
            || events
                .iter()
                .any(|event| event.kind == EventKind::LocalCancelled)
            || (kind == EventKind::LocalCancelled && sequence != 2)
            || (kind == EventKind::SubmissionObserved
                && events.iter().any(|event| event.kind == kind))
        {
            return Err(corrupt());
        }
        serde_json::from_str::<serde_json::Value>(&observation).map_err(|_| corrupt())?;
        verify_fence(tx, &row, &binding).await?;
        events.push(Event {
            kind,
            observation,
            digest,
        });
    }
    Ok(events)
}

pub(crate) async fn verify_sender_store(
    pool: &SqlitePool,
    owner: &AgentId,
) -> Result<(), CognitiveStoreError> {
    let mut tx = pool.begin().await.map_err(unavailable)?;
    let result = async {
        reserve(&mut tx, /*requests*/ 0, /*events*/ 0, /*bytes*/ 0).await?;
        let rows = sqlx::query("SELECT * FROM cognitive_objective_sender_requests ORDER BY request_sha256 LIMIT 1025")
            .fetch_all(&mut *tx).await.map_err(unavailable)?;
        for row in rows {
            let request = decode_request(&mut tx, &row).await?;
            if request.origin.agent_id != *owner {
                return Err(corrupt());
            }
            read_events(&mut tx, &request, ExistingPermit::Required).await?;
        }
        let orphan_count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM cognitive_objective_sender_events e LEFT JOIN cognitive_objective_sender_requests r
             ON r.request_sha256 = e.request_sha256 WHERE r.request_sha256 IS NULL",
        ).fetch_one(&mut *tx).await.map_err(unavailable)?;
        if orphan_count != 0 { return Err(corrupt()); }
        Ok::<_, ObjectiveSenderError>(())
    }.await;
    tx.rollback().await.map_err(unavailable)?;
    result.map_err(|error| match error {
        ObjectiveSenderError::Store(error) => error,
        _ => CognitiveStoreError::Corrupt("Objective sender domain integrity mismatch".to_string()),
    })
}
