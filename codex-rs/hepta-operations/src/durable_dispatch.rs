//! Final dispatch admission and result transitions under one SQLite writer.
//!
//! The earlier committed `dispatching` row is deliberately retained as the
//! crash boundary. This transaction fences competing lease/recovery writers
//! through the synchronous local effect entry and its result write.

use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_types::Digest32;
use sqlx::Sqlite;
use sqlx::Transaction;

use super::ACK_LOST_DIGEST_DOMAIN;
use super::AUTHORITY_REJECTED_DIGEST_DOMAIN;
use super::AuthorizedDispatch;
use super::load_operation_tx;
use super::load_outbox_tx;
use super::next_revision;
use super::now_millis;
use super::require_current_lease;
use super::sqlx_error;
use super::to_i64;
use super::to_u64;
use super::validate_claim_snapshot;
use crate::DispatchClaim;
use crate::DispatchEffect;
use crate::DurableOperationError;
use crate::DurableOperationIntentV1 as OperationIntentV1;
use crate::DurableOperationRecord;
use crate::DurableOperationState;
use crate::DurableOperationStore;
use crate::DurableOutboxState;
use crate::MAX_DURABLE_LEASE_MS;

impl DurableOperationStore {
    pub(super) async fn execute_authorized_in_transaction<T>(
        &self,
        mut authorized: AuthorizedDispatch,
        effect: impl FnOnce(&OperationIntentV1) -> DispatchEffect<T>,
    ) -> Result<T, DurableOperationError> {
        if !Arc::ptr_eq(&self.dispatch_owner, &authorized.dispatch_owner) {
            return Err(DurableOperationError::Invalid("dispatch source owner"));
        }
        let claim = authorized.claim.clone();
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        let status = require_current_lease(&mut tx, &claim, now_millis()?).await?;
        let operation =
            load_operation_tx(&mut tx, &claim.intent.scope_id, &claim.intent.operation_id)
                .await?
                .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
        if operation.intent != claim.intent || operation.writer_fence != claim.fence {
            return Err(DurableOperationError::StaleLease);
        }
        if operation.state != DurableOperationState::Dispatching {
            return Err(DurableOperationError::InvalidTransition {
                from: operation.state,
                to: "effect_entry",
            });
        }
        let token = authorized
            .token
            .take()
            .ok_or(DurableOperationError::Unavailable(
                "final-use token already consumed".to_owned(),
            ))?;
        let authority: &FinalUseAuthority = &authorized.authority;
        let entry = authority.with_dispatch_boundary(token, &authorized.binding, || {
            // All awaited reads and the FinalUse check precede this fresh
            // lease check. No await or writer handoff can intervene before
            // the synchronous adapter entry.
            let admitted_at = now_millis()?;
            validate_claim_snapshot(&status, &claim, admitted_at)?;
            if operation.updated_at_unix_ms > to_u64(admitted_at)? {
                return Err(DurableOperationError::ClockRollback);
            }
            Ok((admitted_at, effect(&operation.intent)))
        });
        let (admitted_at, observation) = match entry {
            Ok(entry) => entry?,
            Err(error) => {
                release_not_dispatched_tx(
                    &mut tx,
                    &claim,
                    Digest32::of_bytes(AUTHORITY_REJECTED_DIGEST_DOMAIN),
                    Duration::ZERO,
                    now_millis()?,
                )
                .await?;
                tx.commit().await.map_err(sqlx_error)?;
                return Err(DurableOperationError::Authority(error));
            }
        };
        // The lease authorizes entry, not completion. Keep its admitted clock
        // for result persistence while this same transaction still excludes
        // successor writers; post-entry expiry cannot erase an observed effect.
        let result = match observation {
            DispatchEffect::Dispatched {
                value,
                dispatch_digest,
                acknowledgement_digest,
            } => {
                if dispatch_digest.is_zero()
                    || acknowledgement_digest.is_some_and(Digest32::is_zero)
                {
                    mark_indeterminate_tx(
                        &mut tx,
                        &claim,
                        Digest32::of_bytes(ACK_LOST_DIGEST_DOMAIN),
                        admitted_at,
                    )
                    .await?;
                    Err(DurableOperationError::Invalid("dispatch evidence digest"))
                } else {
                    record_dispatch_tx(&mut tx, &claim, dispatch_digest, admitted_at).await?;
                    match acknowledgement_digest {
                        Some(acknowledgement) => {
                            acknowledge_outbox_tx(&mut tx, &claim, acknowledgement, admitted_at)
                                .await?;
                        }
                        None => {
                            mark_indeterminate_tx(
                                &mut tx,
                                &claim,
                                Digest32::of_bytes(ACK_LOST_DIGEST_DOMAIN),
                                admitted_at,
                            )
                            .await?;
                        }
                    }
                    Ok(value)
                }
            }
            DispatchEffect::NotDispatched {
                value,
                reason_digest,
                retry_after,
            } => {
                release_not_dispatched_tx(&mut tx, &claim, reason_digest, retry_after, admitted_at)
                    .await?;
                Ok(value)
            }
            DispatchEffect::Indeterminate {
                value,
                reason_digest,
            } => {
                mark_indeterminate_tx(&mut tx, &claim, reason_digest, admitted_at).await?;
                Ok(value)
            }
        };
        tx.commit().await.map_err(sqlx_error)?;
        result
    }
}

pub(super) async fn record_dispatch_tx(
    tx: &mut Transaction<'_, Sqlite>,
    claim: &DispatchClaim,
    dispatch_digest: Digest32,
    now: i64,
) -> Result<DurableOperationRecord, DurableOperationError> {
    if dispatch_digest.is_zero() {
        return Err(DurableOperationError::Invalid("dispatch digest"));
    }
    require_current_lease(tx, claim, now).await?;
    let operation = load_operation_tx(tx, &claim.intent.scope_id, &claim.intent.operation_id)
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
    if operation.state == DurableOperationState::Dispatched
        && operation.dispatch_digest == Some(dispatch_digest)
    {
        return Ok(operation);
    }
    if operation.state != DurableOperationState::Dispatching {
        return Err(DurableOperationError::InvalidTransition {
            from: operation.state,
            to: "dispatched",
        });
    }
    let revision = next_revision(operation.revision)?;
    sqlx::query(
        "UPDATE operation_ledger SET state = 'dispatched', dispatch_digest = ?,
         revision = ?, updated_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(dispatch_digest.as_array().as_slice())
    .bind(to_i64(revision)?)
    .bind(now)
    .bind(claim.intent.scope_id.as_str())
    .bind(claim.intent.operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    let operation = load_operation_tx(tx, &claim.intent.scope_id, &claim.intent.operation_id)
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
    Ok(operation)
}

pub(super) async fn acknowledge_outbox_tx(
    tx: &mut Transaction<'_, Sqlite>,
    claim: &DispatchClaim,
    acknowledgement_digest: Digest32,
    now: i64,
) -> Result<(), DurableOperationError> {
    if acknowledgement_digest.is_zero() {
        return Err(DurableOperationError::Invalid("acknowledgement digest"));
    }
    let status = load_outbox_tx(
        tx,
        &claim.intent.destination,
        &claim.intent.scope_id,
        &claim.intent.operation_id,
    )
    .await?
    .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
    if status.state == DurableOutboxState::Acknowledged {
        if status.acknowledgement_digest == Some(acknowledgement_digest) {
            return Ok(());
        }
        return Err(DurableOperationError::Conflict(
            claim.intent.operation_id.clone(),
        ));
    }
    require_current_lease(tx, claim, now).await?;
    let operation = load_operation_tx(tx, &claim.intent.scope_id, &claim.intent.operation_id)
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
    if operation.state != DurableOperationState::Dispatched {
        return Err(DurableOperationError::InvalidTransition {
            from: operation.state,
            to: "outbox_acknowledged",
        });
    }
    let fence = status
        .fence
        .checked_add(1)
        .ok_or(DurableOperationError::Capacity)?;
    sqlx::query(
        "UPDATE cross_owner_outbox SET state = 'acked', fence = ?, worker_id = NULL,
         lease_until_ms = NULL, acknowledgement_digest = ?, updated_at_ms = ?, terminal_at_ms = ?
         WHERE destination = ? AND scope_id = ? AND operation_id = ?",
    )
    .bind(to_i64(fence)?)
    .bind(acknowledgement_digest.as_array().as_slice())
    .bind(now)
    .bind(now)
    .bind(claim.intent.destination.as_str())
    .bind(claim.intent.scope_id.as_str())
    .bind(claim.intent.operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    Ok(())
}

pub(super) async fn mark_indeterminate_tx(
    tx: &mut Transaction<'_, Sqlite>,
    claim: &DispatchClaim,
    reason_digest: Digest32,
    now: i64,
) -> Result<DurableOperationRecord, DurableOperationError> {
    if reason_digest.is_zero() {
        return Err(DurableOperationError::Invalid("indeterminate digest"));
    }
    let operation = load_operation_tx(tx, &claim.intent.scope_id, &claim.intent.operation_id)
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
    if operation.state == DurableOperationState::Indeterminate
        && operation.indeterminate_digest == Some(reason_digest)
    {
        return Ok(operation);
    }
    require_current_lease(tx, claim, now).await?;
    if !matches!(
        operation.state,
        DurableOperationState::Dispatching | DurableOperationState::Dispatched
    ) {
        return Err(DurableOperationError::InvalidTransition {
            from: operation.state,
            to: "indeterminate",
        });
    }
    let revision = next_revision(operation.revision)?;
    let status = load_outbox_tx(
        tx,
        &claim.intent.destination,
        &claim.intent.scope_id,
        &claim.intent.operation_id,
    )
    .await?
    .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
    let fence = status
        .fence
        .checked_add(1)
        .ok_or(DurableOperationError::Capacity)?;
    sqlx::query(
        "UPDATE operation_ledger SET state = 'indeterminate', indeterminate_digest = ?,
         revision = ?, updated_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(reason_digest.as_array().as_slice())
    .bind(to_i64(revision)?)
    .bind(now)
    .bind(claim.intent.scope_id.as_str())
    .bind(claim.intent.operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    sqlx::query(
        "UPDATE cross_owner_outbox SET state = 'indeterminate', fence = ?, worker_id = NULL,
         lease_until_ms = NULL, updated_at_ms = ?, terminal_at_ms = ?
         WHERE destination = ? AND scope_id = ? AND operation_id = ?",
    )
    .bind(to_i64(fence)?)
    .bind(now)
    .bind(now)
    .bind(claim.intent.destination.as_str())
    .bind(claim.intent.scope_id.as_str())
    .bind(claim.intent.operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    let operation = load_operation_tx(tx, &claim.intent.scope_id, &claim.intent.operation_id)
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
    Ok(operation)
}

pub(super) async fn release_not_dispatched_tx(
    tx: &mut Transaction<'_, Sqlite>,
    claim: &DispatchClaim,
    reason_digest: Digest32,
    retry_after: Duration,
    now: i64,
) -> Result<(), DurableOperationError> {
    if reason_digest.is_zero() {
        return Err(DurableOperationError::Invalid(
            "not-dispatched reason digest",
        ));
    }
    let retry_ms = u64::try_from(retry_after.as_millis())
        .map_err(|_| DurableOperationError::Invalid("retry duration"))?;
    if retry_ms > MAX_DURABLE_LEASE_MS {
        return Err(DurableOperationError::Invalid("retry duration"));
    }
    let next_eligible = now
        .checked_add(i64::try_from(retry_ms).map_err(|_| DurableOperationError::Capacity)?)
        .ok_or(DurableOperationError::Capacity)?;
    require_current_lease(tx, claim, now).await?;
    let operation = load_operation_tx(tx, &claim.intent.scope_id, &claim.intent.operation_id)
        .await?
        .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
    if operation.state != DurableOperationState::Dispatching {
        return Err(DurableOperationError::InvalidTransition {
            from: operation.state,
            to: "prepared",
        });
    }
    let revision = next_revision(operation.revision)?;
    let status = load_outbox_tx(
        tx,
        &claim.intent.destination,
        &claim.intent.scope_id,
        &claim.intent.operation_id,
    )
    .await?
    .ok_or_else(|| DurableOperationError::Missing(claim.intent.operation_id.clone()))?;
    let fence = status
        .fence
        .checked_add(1)
        .ok_or(DurableOperationError::Capacity)?;
    sqlx::query(
        "UPDATE operation_ledger SET state = 'prepared', authority_epoch = NULL,
         authority_digest = NULL, dispatch_digest = NULL, indeterminate_digest = NULL,
         revision = ?, writer_fence = ?, updated_at_ms = ?
         WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(to_i64(revision)?)
    .bind(to_i64(fence)?)
    .bind(now)
    .bind(claim.intent.scope_id.as_str())
    .bind(claim.intent.operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    sqlx::query(
        "UPDATE cross_owner_outbox SET state = 'queued', fence = ?, worker_id = NULL,
         lease_until_ms = NULL, next_eligible_at_ms = ?, updated_at_ms = ?
         WHERE destination = ? AND scope_id = ? AND operation_id = ?",
    )
    .bind(to_i64(fence)?)
    .bind(next_eligible)
    .bind(now)
    .bind(claim.intent.destination.as_str())
    .bind(claim.intent.scope_id.as_str())
    .bind(claim.intent.operation_id.as_str())
    .execute(&mut **tx)
    .await
    .map_err(sqlx_error)?;
    Ok(())
}
