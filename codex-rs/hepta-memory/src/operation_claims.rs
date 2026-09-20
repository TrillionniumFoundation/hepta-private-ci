use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::CognitiveStore;
use crate::LocalLeaseOutboxError;

pub(crate) const MAX_DURABLE_DISPATCH_ATTEMPTS: u32 = 64;
pub(crate) const MAX_DURABLE_CLAIM_LEASE_MS: u64 = 60_000;
const MAX_RETRY_BACKOFF_MS: u64 = 5_000;
const CLAIM_GENESIS: &[u8] = b"hepta:kernel.operations:dispatch-claim:genesis:v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ClaimState {
    Claimed,
    Renewed,
    Entered,
    Settled,
}

impl ClaimState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Claimed => "claimed",
            Self::Renewed => "renewed",
            Self::Entered => "entered",
            Self::Settled => "settled",
        }
    }

    fn parse(value: &str) -> Result<Self, LocalLeaseOutboxError> {
        match value {
            "claimed" => Ok(Self::Claimed),
            "renewed" => Ok(Self::Renewed),
            "entered" => Ok(Self::Entered),
            "settled" => Ok(Self::Settled),
            other => Err(LocalLeaseOutboxError::Corrupt(format!(
                "unknown durable dispatch claim state {other:?}"
            ))),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct DurableDispatchClaim {
    pub operation_id: String,
    pub claim_sequence: u64,
    pub attempt: u32,
    pub owner_generation: u64,
    pub fencing_token: String,
    pub lease_expires_at_unix_ms: u64,
    pub next_eligible_at_unix_ms: u64,
    pub claim_sha256: Sha256Digest,
}

#[derive(Clone, Debug)]
struct ClaimRow {
    claim_sequence: u64,
    attempt: u32,
    owner_generation: u64,
    fencing_token: String,
    state: ClaimState,
    lease_expires_at_unix_ms: u64,
    next_eligible_at_unix_ms: u64,
    claim_sha256: Sha256Digest,
}

pub(crate) async fn claim(
    store: &CognitiveStore,
    operation_id: &str,
    owner_generation: u64,
    fencing_token: &str,
    now_unix_ms: u64,
    lease_duration_ms: u64,
) -> Result<DurableDispatchClaim, LocalLeaseOutboxError> {
    validate_claim_input(operation_id, owner_generation, fencing_token, now_unix_ms, lease_duration_ms)?;
    let mut transaction = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    verify_operation_fence(
        &mut transaction,
        store,
        operation_id,
        owner_generation,
        fencing_token,
    )
    .await?;
    let previous = latest_claim(&mut transaction, operation_id).await?;

    if let Some(previous) = previous.as_ref() {
        match previous.state {
            ClaimState::Claimed | ClaimState::Renewed => {
                if previous.owner_generation == owner_generation
                    && previous.fencing_token == fencing_token
                    && now_unix_ms < previous.lease_expires_at_unix_ms
                {
                    transaction
                        .commit()
                        .await
                        .map_err(crate::cognitive_store::unavailable)?;
                    return Ok(to_receipt(operation_id, previous));
                }
                if now_unix_ms < previous.lease_expires_at_unix_ms {
                    return Err(LocalLeaseOutboxError::StaleFence(
                        "durable dispatch claim is held by a live owner".to_string(),
                    ));
                }
                if owner_generation <= previous.owner_generation {
                    return Err(LocalLeaseOutboxError::StaleFence(
                        "expired durable dispatch claim requires a strictly newer owner generation"
                            .to_string(),
                    ));
                }
                if now_unix_ms < previous.next_eligible_at_unix_ms {
                    return Err(LocalLeaseOutboxError::IllegalTransition(format!(
                        "durable dispatch retry is not eligible until {}",
                        previous.next_eligible_at_unix_ms
                    )));
                }
            }
            ClaimState::Entered => {
                return Err(LocalLeaseOutboxError::IllegalTransition(
                    "durable dispatch already entered the effect boundary; reconcile instead of retry"
                        .to_string(),
                ));
            }
            ClaimState::Settled => {
                return Err(LocalLeaseOutboxError::IllegalTransition(
                    "durable dispatch claim is already terminal".to_string(),
                ));
            }
        }
    }

    let attempt = match previous.as_ref() {
        Some(previous) => previous
            .attempt
            .checked_add(1)
            .filter(|attempt| *attempt <= MAX_DURABLE_DISPATCH_ATTEMPTS)
            .ok_or(LocalLeaseOutboxError::CapacityExceeded {
                resource: "durable dispatch attempts",
                maximum: MAX_DURABLE_DISPATCH_ATTEMPTS as usize,
            })?,
        None => 1,
    };
    let lease_expires_at_unix_ms = now_unix_ms
        .checked_add(lease_duration_ms)
        .ok_or_else(|| LocalLeaseOutboxError::Invalid("dispatch claim lease overflow".to_string()))?;
    let next_eligible_at_unix_ms = lease_expires_at_unix_ms
        .checked_add(retry_backoff_ms(attempt))
        .ok_or_else(|| LocalLeaseOutboxError::Invalid("dispatch retry deadline overflow".to_string()))?;
    let row = append_claim(
        &mut transaction,
        operation_id,
        previous.as_ref(),
        attempt,
        owner_generation,
        fencing_token,
        ClaimState::Claimed,
        lease_expires_at_unix_ms,
        next_eligible_at_unix_ms,
        now_unix_ms,
    )
    .await?;
    transaction
        .commit()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    Ok(to_receipt(operation_id, &row))
}

pub(crate) async fn renew(
    store: &CognitiveStore,
    claim: &DurableDispatchClaim,
    now_unix_ms: u64,
    lease_duration_ms: u64,
) -> Result<DurableDispatchClaim, LocalLeaseOutboxError> {
    validate_claim_input(
        &claim.operation_id,
        claim.owner_generation,
        &claim.fencing_token,
        now_unix_ms,
        lease_duration_ms,
    )?;
    let mut transaction = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    verify_operation_fence(
        &mut transaction,
        store,
        &claim.operation_id,
        claim.owner_generation,
        &claim.fencing_token,
    )
    .await?;
    let previous = latest_claim(&mut transaction, &claim.operation_id)
        .await?
        .ok_or_else(|| LocalLeaseOutboxError::StaleFence("dispatch claim is missing".to_string()))?;
    if !matches!(previous.state, ClaimState::Claimed | ClaimState::Renewed)
        || previous.attempt != claim.attempt
        || previous.owner_generation != claim.owner_generation
        || previous.fencing_token != claim.fencing_token
        || previous.claim_sha256 != claim.claim_sha256
    {
        return Err(LocalLeaseOutboxError::StaleFence(
            "dispatch claim renewal does not match the current claim head".to_string(),
        ));
    }
    if now_unix_ms >= previous.lease_expires_at_unix_ms {
        return Err(LocalLeaseOutboxError::StaleFence(
            "dispatch claim lease already expired".to_string(),
        ));
    }
    let lease_expires_at_unix_ms = now_unix_ms
        .checked_add(lease_duration_ms)
        .ok_or_else(|| LocalLeaseOutboxError::Invalid("dispatch claim lease overflow".to_string()))?;
    if lease_expires_at_unix_ms <= previous.lease_expires_at_unix_ms {
        return Err(LocalLeaseOutboxError::Invalid(
            "dispatch claim renewal must extend the lease".to_string(),
        ));
    }
    let next_eligible_at_unix_ms = lease_expires_at_unix_ms
        .checked_add(retry_backoff_ms(previous.attempt))
        .ok_or_else(|| LocalLeaseOutboxError::Invalid("dispatch retry deadline overflow".to_string()))?;
    let row = append_claim(
        &mut transaction,
        &claim.operation_id,
        Some(&previous),
        previous.attempt,
        previous.owner_generation,
        &previous.fencing_token,
        ClaimState::Renewed,
        lease_expires_at_unix_ms,
        next_eligible_at_unix_ms,
        now_unix_ms,
    )
    .await?;
    transaction
        .commit()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    Ok(to_receipt(&claim.operation_id, &row))
}

pub(crate) async fn mark_entered(
    store: &CognitiveStore,
    claim: &DurableDispatchClaim,
    now_unix_ms: u64,
) -> Result<DurableDispatchClaim, LocalLeaseOutboxError> {
    transition_claim(store, claim, now_unix_ms, ClaimState::Entered).await
}

pub(crate) async fn mark_settled(
    store: &CognitiveStore,
    claim: &DurableDispatchClaim,
    now_unix_ms: u64,
) -> Result<DurableDispatchClaim, LocalLeaseOutboxError> {
    transition_claim(store, claim, now_unix_ms, ClaimState::Settled).await
}

async fn transition_claim(
    store: &CognitiveStore,
    claim: &DurableDispatchClaim,
    now_unix_ms: u64,
    target: ClaimState,
) -> Result<DurableDispatchClaim, LocalLeaseOutboxError> {
    if now_unix_ms == 0 {
        return Err(LocalLeaseOutboxError::Invalid(
            "dispatch claim timestamp must be non-zero".to_string(),
        ));
    }
    let mut transaction = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    verify_operation_fence(
        &mut transaction,
        store,
        &claim.operation_id,
        claim.owner_generation,
        &claim.fencing_token,
    )
    .await?;
    let previous = latest_claim(&mut transaction, &claim.operation_id)
        .await?
        .ok_or_else(|| LocalLeaseOutboxError::StaleFence("dispatch claim is missing".to_string()))?;

    if target == ClaimState::Settled
        && previous.state == ClaimState::Settled
        && previous.attempt == claim.attempt
        && previous.owner_generation == claim.owner_generation
        && previous.fencing_token == claim.fencing_token
    {
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        return Ok(to_receipt(&claim.operation_id, &previous));
    }

    let allowed = match target {
        ClaimState::Entered => matches!(previous.state, ClaimState::Claimed | ClaimState::Renewed),
        ClaimState::Settled => previous.state == ClaimState::Entered,
        ClaimState::Claimed | ClaimState::Renewed => false,
    };
    if !allowed
        || previous.attempt != claim.attempt
        || previous.owner_generation != claim.owner_generation
        || previous.fencing_token != claim.fencing_token
    {
        return Err(LocalLeaseOutboxError::StaleFence(
            "dispatch claim transition does not match the current claim head".to_string(),
        ));
    }
    if target == ClaimState::Entered && now_unix_ms >= previous.lease_expires_at_unix_ms {
        return Err(LocalLeaseOutboxError::StaleFence(
            "dispatch claim expired before effect entry".to_string(),
        ));
    }

    let row = append_claim(
        &mut transaction,
        &claim.operation_id,
        Some(&previous),
        previous.attempt,
        previous.owner_generation,
        &previous.fencing_token,
        target,
        previous.lease_expires_at_unix_ms,
        previous.next_eligible_at_unix_ms,
        now_unix_ms,
    )
    .await?;
    transaction
        .commit()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    Ok(to_receipt(&claim.operation_id, &row))
}

async fn verify_operation_fence(
    transaction: &mut Transaction<'_, Sqlite>,
    store: &CognitiveStore,
    operation_id: &str,
    owner_generation: u64,
    fencing_token: &str,
) -> Result<(), LocalLeaseOutboxError> {
    let operation = sqlx::query(
        "SELECT lease_id, owner_agent_id FROM cognitive_operation_ledger WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?
    .ok_or_else(|| {
        LocalLeaseOutboxError::StaleFence(
            "durable dispatch claim requires an operation ledger row".to_string(),
        )
    })?;
    let lease_id: String = operation
        .try_get("lease_id")
        .map_err(crate::cognitive_store::unavailable)?;
    let owner_agent_id: String = operation
        .try_get("owner_agent_id")
        .map_err(crate::cognitive_store::unavailable)?;
    if owner_agent_id != store.owner_agent_id().as_str() {
        return Err(LocalLeaseOutboxError::Corrupt(
            "durable operation claim belongs to a foreign cognitive owner".to_string(),
        ));
    }
    let lease = sqlx::query(
        "SELECT generation, fencing_token, state
         FROM cognitive_local_leases
         WHERE lease_id = ?
         ORDER BY lease_sequence DESC LIMIT 1",
    )
    .bind(&lease_id)
    .fetch_one(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    let generation: i64 = lease
        .try_get("generation")
        .map_err(crate::cognitive_store::unavailable)?;
    let token: String = lease
        .try_get("fencing_token")
        .map_err(crate::cognitive_store::unavailable)?;
    let state: String = lease
        .try_get("state")
        .map_err(crate::cognitive_store::unavailable)?;
    if generation <= 0
        || u64::try_from(generation).ok() != Some(owner_generation)
        || token != fencing_token
        || state != "active"
    {
        return Err(LocalLeaseOutboxError::StaleFence(
            "durable dispatch claim does not match the current active owner fence".to_string(),
        ));
    }
    Ok(())
}

async fn latest_claim(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<Option<ClaimRow>, LocalLeaseOutboxError> {
    let row = sqlx::query(
        "SELECT claim_sequence, attempt, owner_generation, fencing_token, claim_state,
                lease_expires_at_unix_ms, next_eligible_at_unix_ms, claim_sha256
         FROM cognitive_operation_dispatch_claims
         WHERE operation_id = ?
         ORDER BY claim_sequence DESC LIMIT 1",
    )
    .bind(operation_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    row.map(|row| {
        let claim_sequence = read_u64(&row, "claim_sequence")?;
        let attempt = read_u64(&row, "attempt")?;
        let owner_generation = read_u64(&row, "owner_generation")?;
        let lease_expires_at_unix_ms = read_u64(&row, "lease_expires_at_unix_ms")?;
        let next_eligible_at_unix_ms = read_u64(&row, "next_eligible_at_unix_ms")?;
        Ok(ClaimRow {
            claim_sequence,
            attempt: u32::try_from(attempt).map_err(|_| {
                LocalLeaseOutboxError::Corrupt("dispatch claim attempt overflow".to_string())
            })?,
            owner_generation,
            fencing_token: row
                .try_get("fencing_token")
                .map_err(crate::cognitive_store::unavailable)?,
            state: ClaimState::parse(
                row.try_get::<String, _>("claim_state")
                    .map_err(crate::cognitive_store::unavailable)?
                    .as_str(),
            )?,
            lease_expires_at_unix_ms,
            next_eligible_at_unix_ms,
            claim_sha256: Sha256Digest::parse(
                row.try_get::<String, _>("claim_sha256")
                    .map_err(crate::cognitive_store::unavailable)?,
            )
            .map_err(LocalLeaseOutboxError::Corrupt)?,
        })
    })
    .transpose()
}

#[allow(clippy::too_many_arguments)]
async fn append_claim(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
    previous: Option<&ClaimRow>,
    attempt: u32,
    owner_generation: u64,
    fencing_token: &str,
    state: ClaimState,
    lease_expires_at_unix_ms: u64,
    next_eligible_at_unix_ms: u64,
    recorded_at_unix_ms: u64,
) -> Result<ClaimRow, LocalLeaseOutboxError> {
    let claim_sequence = previous
        .map(|row| row.claim_sequence)
        .unwrap_or(0)
        .checked_add(1)
        .ok_or_else(|| LocalLeaseOutboxError::Invalid("dispatch claim sequence overflow".to_string()))?;
    let previous_sha256 = previous
        .map(|row| row.claim_sha256.clone())
        .unwrap_or_else(|| Sha256Digest::for_bytes(CLAIM_GENESIS));
    let claim_sha256 = claim_digest(
        operation_id,
        claim_sequence,
        attempt,
        owner_generation,
        fencing_token,
        state,
        lease_expires_at_unix_ms,
        next_eligible_at_unix_ms,
        &previous_sha256,
    );
    sqlx::query(
        "INSERT INTO cognitive_operation_dispatch_claims (
            operation_id, claim_sequence, attempt, owner_generation, fencing_token,
            claim_state, lease_expires_at_unix_ms, next_eligible_at_unix_ms,
            previous_sha256, claim_sha256, recorded_at_unix_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(operation_id)
    .bind(to_i64(claim_sequence, "dispatch claim sequence")?)
    .bind(i64::from(attempt))
    .bind(to_i64(owner_generation, "dispatch claim owner generation")?)
    .bind(fencing_token)
    .bind(state.as_str())
    .bind(to_i64(lease_expires_at_unix_ms, "dispatch claim expiry")?)
    .bind(to_i64(next_eligible_at_unix_ms, "dispatch retry eligibility")?)
    .bind(previous_sha256.as_str())
    .bind(claim_sha256.as_str())
    .bind(to_i64(recorded_at_unix_ms, "dispatch claim timestamp")?)
    .execute(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    Ok(ClaimRow {
        claim_sequence,
        attempt,
        owner_generation,
        fencing_token: fencing_token.to_string(),
        state,
        lease_expires_at_unix_ms,
        next_eligible_at_unix_ms,
        claim_sha256,
    })
}

#[allow(clippy::too_many_arguments)]
fn claim_digest(
    operation_id: &str,
    claim_sequence: u64,
    attempt: u32,
    owner_generation: u64,
    fencing_token: &str,
    state: ClaimState,
    lease_expires_at_unix_ms: u64,
    next_eligible_at_unix_ms: u64,
    previous_sha256: &Sha256Digest,
) -> Sha256Digest {
    let mut bytes = Vec::new();
    for part in [
        b"hepta:kernel.operations:dispatch-claim:v1".as_slice(),
        operation_id.as_bytes(),
        &claim_sequence.to_be_bytes(),
        &attempt.to_be_bytes(),
        &owner_generation.to_be_bytes(),
        fencing_token.as_bytes(),
        state.as_str().as_bytes(),
        &lease_expires_at_unix_ms.to_be_bytes(),
        &next_eligible_at_unix_ms.to_be_bytes(),
        previous_sha256.as_str().as_bytes(),
    ] {
        bytes.extend_from_slice(&(part.len() as u64).to_be_bytes());
        bytes.extend_from_slice(part);
    }
    Sha256Digest::for_bytes(&bytes)
}

fn to_receipt(operation_id: &str, row: &ClaimRow) -> DurableDispatchClaim {
    DurableDispatchClaim {
        operation_id: operation_id.to_string(),
        claim_sequence: row.claim_sequence,
        attempt: row.attempt,
        owner_generation: row.owner_generation,
        fencing_token: row.fencing_token.clone(),
        lease_expires_at_unix_ms: row.lease_expires_at_unix_ms,
        next_eligible_at_unix_ms: row.next_eligible_at_unix_ms,
        claim_sha256: row.claim_sha256.clone(),
    }
}

fn validate_claim_input(
    operation_id: &str,
    owner_generation: u64,
    fencing_token: &str,
    now_unix_ms: u64,
    lease_duration_ms: u64,
) -> Result<(), LocalLeaseOutboxError> {
    if operation_id.trim().is_empty() || operation_id.len() > 128 || operation_id.as_bytes().contains(&0) {
        return Err(LocalLeaseOutboxError::Invalid(
            "dispatch claim operation id must contain 1..=128 non-NUL bytes".to_string(),
        ));
    }
    if owner_generation == 0 || fencing_token.trim().is_empty() || fencing_token.len() > 256 {
        return Err(LocalLeaseOutboxError::Invalid(
            "dispatch claim owner fence is invalid".to_string(),
        ));
    }
    if now_unix_ms == 0 || lease_duration_ms == 0 || lease_duration_ms > MAX_DURABLE_CLAIM_LEASE_MS {
        return Err(LocalLeaseOutboxError::Invalid(format!(
            "dispatch claim lease must be 1..={MAX_DURABLE_CLAIM_LEASE_MS} ms with non-zero current time"
        )));
    }
    Ok(())
}

fn retry_backoff_ms(attempt: u32) -> u64 {
    let exponent = attempt.saturating_sub(1).min(10);
    50_u64
        .saturating_mul(1_u64 << exponent)
        .min(MAX_RETRY_BACKOFF_MS)
}

fn read_u64(row: &sqlx::sqlite::SqliteRow, column: &str) -> Result<u64, LocalLeaseOutboxError> {
    let value: i64 = row
        .try_get(column)
        .map_err(crate::cognitive_store::unavailable)?;
    u64::try_from(value)
        .map_err(|_| LocalLeaseOutboxError::Corrupt(format!("negative dispatch claim {column}")))
}

fn to_i64(value: u64, label: &str) -> Result<i64, LocalLeaseOutboxError> {
    i64::try_from(value)
        .map_err(|_| LocalLeaseOutboxError::Invalid(format!("{label} overflows SQLite INTEGER")))
}
