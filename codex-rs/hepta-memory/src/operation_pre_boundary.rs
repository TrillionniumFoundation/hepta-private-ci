//! Narrow reauthorization of an internally witnessed, never-entered request.
//! This child module uses the original dispatch-claim chain and transaction.

use super::*;
use crate::production_writer::PreBoundaryRejected;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ReauthorizationBinding {
    pub operation_id: String,
    pub lease_id: String,
    pub semantic_sha256: Sha256Digest,
    pub payload_sha256: Sha256Digest,
    pub request_sha256: Sha256Digest,
    pub authority_grant_sha256: Sha256Digest,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub owner_generation: u64,
    pub fencing_token: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum RejectionStage {
    Claim,
    Entry,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ProofRecord {
    binding: ReauthorizationBinding,
    dispatch_event_id: String,
    entered_claim_sha256: Sha256Digest,
    settled_claim_sha256: Sha256Digest,
    stage: RejectionStage,
    rejected_nonce: [u8; 32],
}

pub(crate) struct ReauthorizedClaim {
    pub claim: DurableDispatchClaim,
    pub dispatch_event_id: String,
}

pub(crate) async fn record_rejection(
    store: &CognitiveStore,
    proof: PreBoundaryRejected,
    now_unix_ms: u64,
) -> Result<(), LocalLeaseOutboxError> {
    let (binding, entered, dispatch_event_id, stage, rejected_nonce) = proof.into_parts();
    let mut transaction = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    verify_binding(&mut transaction, store, &binding, &dispatch_event_id).await?;
    let previous = latest_claim(&mut transaction, &binding.operation_id)
        .await?
        .ok_or_else(|| stale("pre-boundary proof has no entered claim"))?;
    if previous.state != ClaimState::Entered
        || to_receipt(&binding.operation_id, &previous) != entered
        || entered.owner_generation != binding.owner_generation
        || entered.fencing_token != binding.fencing_token
    {
        return Err(stale(
            "pre-boundary proof does not match the exact entered head",
        ));
    }
    let settled = append_claim(
        &mut transaction,
        &binding.operation_id,
        Some(&previous),
        previous.attempt,
        previous.owner_generation,
        &previous.fencing_token,
        ClaimState::Settled,
        previous.lease_expires_at_unix_ms,
        previous.next_eligible_at_unix_ms,
        now_unix_ms,
    )
    .await?;
    let proof = ProofRecord {
        binding,
        dispatch_event_id,
        entered_claim_sha256: entered.claim_sha256,
        settled_claim_sha256: settled.claim_sha256,
        stage,
        rejected_nonce,
    };
    let payload = serde_json::to_string(&proof)
        .map_err(|error| LocalLeaseOutboxError::Invalid(error.to_string()))?;
    let digest = proof_digest(&payload);
    sqlx::query(
        "INSERT INTO cognitive_operation_pre_boundary_rejections (
            operation_id, entered_claim_sha256, settled_claim_sha256,
            dispatch_event_id, lease_id, proof_json, proof_sha256, recorded_at_unix_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&proof.binding.operation_id)
    .bind(proof.entered_claim_sha256.as_str())
    .bind(proof.settled_claim_sha256.as_str())
    .bind(&proof.dispatch_event_id)
    .bind(&proof.binding.lease_id)
    .bind(&payload)
    .bind(digest.as_str())
    .bind(to_i64(now_unix_ms, "pre-boundary proof timestamp")?)
    .execute(&mut *transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    transaction
        .commit()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    Ok(())
}

pub(crate) async fn awaiting_reauthorization(
    store: &CognitiveStore,
    binding: &ReauthorizationBinding,
    now_unix_ms: u64,
) -> Result<bool, LocalLeaseOutboxError> {
    let mut transaction = store
        .pool
        .begin()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    let found = match current_proof(&mut transaction, store, binding).await {
        Ok(found) => found,
        Err(LocalLeaseOutboxError::StaleFence(_)) => None,
        Err(error) => return Err(error),
    };
    let eligible = found.as_ref().is_some_and(|(_, head)| {
        head.attempt < MAX_DURABLE_DISPATCH_ATTEMPTS && now_unix_ms >= head.next_eligible_at_unix_ms
    });
    transaction
        .commit()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    Ok(eligible)
}

pub(crate) async fn has_rejection_proof(
    store: &CognitiveStore,
    binding: &ReauthorizationBinding,
) -> Result<bool, LocalLeaseOutboxError> {
    let mut transaction = store
        .pool
        .begin()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    // A predecessor's proof grants no retry under a new fence. It must also
    // not suppress the successor's ordinary observer-only reconciliation.
    let found = match current_proof(&mut transaction, store, binding).await {
        Ok(found) => found.is_some(),
        Err(LocalLeaseOutboxError::StaleFence(_)) => false,
        Err(error) => return Err(error),
    };
    transaction
        .commit()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    Ok(found)
}

pub(crate) async fn claim_reauthorization(
    store: &CognitiveStore,
    binding: &ReauthorizationBinding,
    receipt: &crate::ProductionQueuedReceipt,
    new_nonce: [u8; 32],
    now_unix_ms: u64,
    lease_duration_ms: u64,
) -> Result<Option<ReauthorizedClaim>, LocalLeaseOutboxError> {
    validate_claim_input(
        &binding.operation_id,
        binding.owner_generation,
        &binding.fencing_token,
        now_unix_ms,
        lease_duration_ms,
    )?;
    let mut transaction = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    let Some((proof, previous)) = current_proof(&mut transaction, store, binding).await? else {
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        return Ok(None);
    };
    // The original queued verifier cannot accept this proven Indeterminate
    // request. Preserve its exact immutable admission/outbox identity check
    // inside the same transaction that consumes the current internal proof.
    // An unprivileged serialized receipt cannot substitute those row IDs,
    // topic or payload merely because it names a K with a valid proof.
    let receipt_matches: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_operation_ledger o
         JOIN cognitive_local_outbox b ON b.lease_id = o.lease_id AND b.outbox_id = o.outbox_id
         JOIN cognitive_local_events e ON e.lease_id = o.lease_id AND e.event_id = o.event_id
         WHERE o.operation_id = ? AND o.lease_id = ? AND o.event_id = ? AND o.outbox_id = ?
           AND b.occurrence_key = o.operation_id AND e.occurrence_key = o.operation_id
           AND b.event_id = e.event_id AND b.topic = ?
           AND b.payload_json = ? AND e.payload_json = b.payload_json
           AND b.payload_sha256 = ? AND e.payload_sha256 = b.payload_sha256
           AND o.payload_sha256 = b.payload_sha256",
    )
    .bind(&binding.operation_id)
    .bind(&binding.lease_id)
    .bind(&receipt.event_id)
    .bind(&receipt.outbox_id)
    .bind(&receipt.topic)
    .bind(&receipt.payload_json)
    .bind(receipt.payload_sha256.as_str())
    .fetch_one(&mut *transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if receipt.occurrence_key != binding.operation_id
        || receipt.lease_id != binding.lease_id
        || receipt.owner_agent_id != *store.owner_agent_id()
        || receipt.generation != binding.owner_generation
        || receipt.inherited_from_generation.is_some()
        || receipt_matches != 1
    {
        return Err(stale(
            "reauthorization receipt does not match the original immutable admission",
        ));
    }
    let rejected_nonce = serde_json::to_string(&new_nonce)
        .map_err(|error| LocalLeaseOutboxError::Invalid(error.to_string()))?;
    let used_nonce: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_operation_pre_boundary_rejections
         WHERE operation_id = ? AND json_extract(proof_json, '$.rejected_nonce') = ?",
    )
    .bind(&binding.operation_id)
    .bind(rejected_nonce)
    .fetch_one(&mut *transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if proof.rejected_nonce == new_nonce || used_nonce != 0 {
        return Err(stale(
            "reauthorization requires a fresh externally issued nonce",
        ));
    }
    if now_unix_ms < previous.next_eligible_at_unix_ms {
        return Err(LocalLeaseOutboxError::IllegalTransition(
            "pre-boundary reauthorization is still in the original retry backoff".to_string(),
        ));
    }
    let attempt = previous
        .attempt
        .checked_add(1)
        .filter(|attempt| *attempt <= MAX_DURABLE_DISPATCH_ATTEMPTS)
        .ok_or(LocalLeaseOutboxError::CapacityExceeded {
            resource: "durable dispatch attempts",
            maximum: MAX_DURABLE_DISPATCH_ATTEMPTS as usize,
        })?;
    let expiry = now_unix_ms
        .checked_add(lease_duration_ms)
        .ok_or_else(|| stale("reauthorization claim expiry overflow"))?;
    let eligible = expiry
        .checked_add(retry_backoff_ms(attempt))
        .ok_or_else(|| stale("reauthorization backoff overflow"))?;
    // The new head consumes the proof atomically. A crash after this commit
    // has no current proof and therefore stays unknown, even before Entered.
    let claim = append_claim(
        &mut transaction,
        &binding.operation_id,
        Some(&previous),
        attempt,
        binding.owner_generation,
        &binding.fencing_token,
        ClaimState::Claimed,
        expiry,
        eligible,
        now_unix_ms,
    )
    .await?;
    transaction
        .commit()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    Ok(Some(ReauthorizedClaim {
        claim: to_receipt(&binding.operation_id, &claim),
        dispatch_event_id: proof.dispatch_event_id,
    }))
}

pub(crate) async fn enter_reauthorization(
    store: &CognitiveStore,
    binding: &ReauthorizationBinding,
    claim: &DurableDispatchClaim,
    dispatch_event_id: &str,
    now_unix_ms: u64,
) -> Result<DurableDispatchClaim, LocalLeaseOutboxError> {
    let mut transaction = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    verify_binding(&mut transaction, store, binding, dispatch_event_id).await?;
    let previous = latest_claim(&mut transaction, &binding.operation_id)
        .await?
        .ok_or_else(|| stale("reauthorization claim disappeared before entry"))?;
    if previous.state != ClaimState::Claimed
        || to_receipt(&binding.operation_id, &previous) != *claim
        || now_unix_ms >= previous.lease_expires_at_unix_ms
    {
        return Err(stale("reauthorization lost its exact claim before entry"));
    }
    let entered = append_claim(
        &mut transaction,
        &binding.operation_id,
        Some(&previous),
        previous.attempt,
        previous.owner_generation,
        &previous.fencing_token,
        ClaimState::Entered,
        previous.lease_expires_at_unix_ms,
        previous.next_eligible_at_unix_ms,
        now_unix_ms,
    )
    .await?;
    transaction
        .commit()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    Ok(to_receipt(&binding.operation_id, &entered))
}

async fn current_proof(
    transaction: &mut Transaction<'_, Sqlite>,
    store: &CognitiveStore,
    binding: &ReauthorizationBinding,
) -> Result<Option<(ProofRecord, ClaimRow)>, LocalLeaseOutboxError> {
    let Some(head) = latest_claim(transaction, &binding.operation_id).await? else {
        return Ok(None);
    };
    if head.state != ClaimState::Settled {
        return Ok(None);
    }
    let row: Option<(String, String, String, String, String)> = sqlx::query_as(
        "SELECT proof_json, proof_sha256, entered_claim_sha256, dispatch_event_id, lease_id
         FROM cognitive_operation_pre_boundary_rejections
         WHERE operation_id = ? AND settled_claim_sha256 = ?",
    )
    .bind(&binding.operation_id)
    .bind(head.claim_sha256.as_str())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    let Some((payload, digest, entered_sha256, dispatch_event_id, lease_id)) = row else {
        return Ok(None);
    };
    let proof: ProofRecord = serde_json::from_str(&payload)
        .map_err(|error| LocalLeaseOutboxError::Corrupt(error.to_string()))?;
    if proof_digest(&payload).as_str() != digest
        || serde_json::to_string(&proof)
            .map_err(|error| LocalLeaseOutboxError::Corrupt(error.to_string()))?
            != payload
        || proof.settled_claim_sha256 != head.claim_sha256
        || proof.entered_claim_sha256.as_str() != entered_sha256
        || proof.dispatch_event_id != dispatch_event_id
        || proof.binding.lease_id != lease_id
        || proof.binding.operation_id != binding.operation_id
    {
        return Err(LocalLeaseOutboxError::Corrupt(
            "pre-boundary proof binding is corrupt".to_string(),
        ));
    }
    if &proof.binding != binding
        || head.owner_generation != binding.owner_generation
        || head.fencing_token != binding.fencing_token
    {
        return Err(stale(
            "pre-boundary proof belongs to a different operation or owner fence",
        ));
    }
    let entered: Option<(i64, String, String)> = sqlx::query_as(
        "SELECT claim_sequence, claim_state, claim_sha256 FROM cognitive_operation_dispatch_claims
         WHERE operation_id = ? AND claim_sequence = ?",
    )
    .bind(&binding.operation_id)
    .bind(to_i64(
        head.claim_sequence.saturating_sub(1),
        "pre-boundary entered sequence",
    )?)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if !entered.is_some_and(|(_, state, digest)| {
        state == "entered" && digest == proof.entered_claim_sha256.as_str()
    }) {
        return Err(LocalLeaseOutboxError::Corrupt(
            "pre-boundary proof has no adjacent entered claim".to_string(),
        ));
    }
    // A concurrently committed terminal/reconcile event wins. It cannot be
    // resurrected by a still-present immutable proof from an older head.
    if !binding_is_current(transaction, binding, &proof.dispatch_event_id).await? {
        return Ok(None);
    }
    verify_binding(transaction, store, binding, &proof.dispatch_event_id).await?;
    Ok(Some((proof, head)))
}

async fn verify_binding(
    transaction: &mut Transaction<'_, Sqlite>,
    store: &CognitiveStore,
    binding: &ReauthorizationBinding,
    dispatch_event_id: &str,
) -> Result<(), LocalLeaseOutboxError> {
    verify_operation_fence(
        transaction,
        store,
        &binding.operation_id,
        binding.owner_generation,
        &binding.fencing_token,
    )
    .await?;
    if !binding_is_current(transaction, binding, dispatch_event_id).await? {
        return Err(stale(
            "pre-boundary outcome or immutable operation binding changed",
        ));
    }
    let payload: String = sqlx::query_scalar(
        "SELECT payload_json FROM cognitive_local_outbox WHERE lease_id = ? AND occurrence_key = ?",
    )
    .bind(&binding.lease_id)
    .bind(&binding.operation_id)
    .fetch_one(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    let request =
        crate::Hos2InstallBudgetV1::from_json(&payload).map_err(LocalLeaseOutboxError::Corrupt)?;
    crate::local_lease_outbox::validate_hos2_predecessor(
        transaction,
        store.owner_agent_id(),
        &request,
    )
    .await?;
    Ok(())
}

async fn binding_is_current(
    transaction: &mut Transaction<'_, Sqlite>,
    binding: &ReauthorizationBinding,
    dispatch_event_id: &str,
) -> Result<bool, LocalLeaseOutboxError> {
    let count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_operation_ledger o
         JOIN cognitive_local_outbox b ON b.lease_id = o.lease_id AND b.outbox_id = o.outbox_id
         JOIN cognitive_local_events e ON e.lease_id = o.lease_id AND e.occurrence_key = o.operation_id
         WHERE o.operation_id = ? AND o.lease_id = ? AND o.semantic_sha256 = ?
           AND o.payload_sha256 = ? AND b.payload_sha256 = o.payload_sha256
           AND b.topic = 'hepta.hos2.install-budget.v1' AND o.destination_id = 'hos2.cpu-budget.v1'
           AND o.generation = ? AND o.fencing_token = ? AND o.authority_epoch = ? AND o.owner_epoch = ?
           AND e.event_id = ? AND e.event_kind = 'indeterminate'
           AND e.generation = o.generation AND e.fencing_token = o.fencing_token
           AND e.payload_json = ?
           AND e.event_sequence = (SELECT MAX(event_sequence) FROM cognitive_local_events
               WHERE lease_id = o.lease_id AND occurrence_key = o.operation_id)",
    ).bind(&binding.operation_id).bind(&binding.lease_id).bind(binding.semantic_sha256.as_str())
        .bind(binding.payload_sha256.as_str()).bind(to_i64(binding.owner_generation, "owner generation")?)
        .bind(&binding.fencing_token).bind(to_i64(binding.authority_epoch, "authority epoch")?)
        .bind(to_i64(binding.owner_epoch, "owner epoch")?).bind(dispatch_event_id)
        .bind(format!("dispatch_started_pending_ack:{}", binding.request_sha256.as_str()))
        .fetch_one(&mut **transaction).await.map_err(crate::cognitive_store::unavailable)?;
    Ok(count == 1)
}

fn proof_digest(payload: &str) -> Sha256Digest {
    let mut bytes = b"hepta.production.pre-boundary-rejection.v1\0".to_vec();
    bytes.extend_from_slice(payload.as_bytes());
    Sha256Digest::for_bytes(&bytes)
}

fn stale(message: &str) -> LocalLeaseOutboxError {
    LocalLeaseOutboxError::StaleFence(message.to_string())
}
