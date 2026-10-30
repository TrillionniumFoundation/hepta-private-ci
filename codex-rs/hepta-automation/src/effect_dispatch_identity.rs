//! Provider identity selection and checks inside the original effect owner.
//! Existing rows remain authoritative; these helpers create no new identity
//! ledger, execution authority, or migration of already dispatched effects.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use sqlx::QueryBuilder;
use sqlx::Sqlite;
use sqlx::SqliteConnection;
use sqlx::Transaction;

use crate::AuthorizedEffectIntent;
use crate::AutomationStore;
use crate::TaskFlowError;
use crate::effect_dispatch_ledger::EFFECT_DISPATCH_SELECT;
use crate::effect_dispatch_ledger::EffectDispatchAttempt;
use crate::effect_dispatch_ledger::effect_attempt_from_row;

pub(crate) fn async_taskflow_key_matches(
    scope: &str,
    owner: &AgentId,
    run_id: &str,
    step_id: &str,
    key: &ProviderEffectKey,
) -> bool {
    if ProviderEffectKey::for_taskflow_v2(scope, owner, run_id, step_id).as_ref() == Ok(key) {
        return true;
    }
    let legacy_logical_id = format!("taskflow:{run_id}:{step_id}");
    ProviderEffectKey::for_logical_effect(scope, &legacy_logical_id).as_ref() == Ok(key)
}

impl AutomationStore {
    /// Select before consuming a new grant. The write transaction repeats the
    /// history check, so a concurrent first attempt cannot alter this choice.
    pub(crate) async fn select_effect_dispatch_key(
        &self,
        intent: &AuthorizedEffectIntent,
        wire_payload: &[u8],
        new_key: ProviderEffectKey,
    ) -> Result<ProviderEffectKey, TaskFlowError> {
        let mut query = QueryBuilder::<Sqlite>::new(EFFECT_DISPATCH_SELECT);
        query
            .push(" WHERE a.owner_agent_id=")
            .push_bind(self.taskflow_owner_agent_id().as_str())
            .push(" AND a.run_id=")
            .push_bind(&intent.run_id)
            .push(" AND a.step_id=")
            .push_bind(&intent.step_id)
            .push(" ORDER BY a.attempt LIMIT 1");
        let mut transaction = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let first = query
            .build()
            .fetch_optional(&mut *transaction)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?
            .map(effect_attempt_from_row)
            .transpose()?;
        let Some(first) = first else {
            transaction
                .rollback()
                .await
                .map_err(|_| TaskFlowError::Unavailable)?;
            return Ok(new_key);
        };
        validate_effect_dispatch_history(&mut transaction, &first).await?;
        if first.destination_id != intent.destination_id
            || first.payload_digest != intent.payload_digest
            || first.wire_payload.as_deref() != Some(wire_payload)
        {
            return Err(identity_conflict());
        }
        let key = first.provider_effect_key.ok_or_else(identity_conflict)?;
        transaction
            .rollback()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        Ok(key)
    }
}

/// Read each whole logical history in the owner's current SQLite snapshot.
/// Startup calls this once per ordered step, so a long retry history is scanned
/// linearly rather than once again for every historical attempt.
pub(crate) async fn validate_effect_dispatch_history(
    connection: &mut SqliteConnection,
    reference: &EffectDispatchAttempt,
) -> Result<(), TaskFlowError> {
    let differs: bool = sqlx::query_scalar(
        "SELECT EXISTS (
            SELECT 1 FROM taskflow_effect_dispatch_attempts
            WHERE owner_agent_id=? AND run_id=? AND step_id=?
              AND (provider_effect_key IS NOT ? OR wire_payload IS NOT ?
                   OR payload_digest IS NOT ? OR destination_id IS NOT ?)
         )",
    )
    .bind(reference.owner_agent_id.as_str())
    .bind(&reference.run_id)
    .bind(&reference.step_id)
    .bind(
        reference
            .provider_effect_key
            .as_ref()
            .map(ProviderEffectKey::as_str),
    )
    .bind(reference.wire_payload.as_deref())
    .bind(reference.payload_digest.as_str())
    .bind(&reference.destination_id)
    .fetch_one(connection)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    if differs {
        return Err(TaskFlowError::Corrupt(
            "effect history changes its provider identity or wire".to_string(),
        ));
    }
    Ok(())
}

/// The existing BEGIN IMMEDIATE owns this check and the following INSERT.
/// Every prior attempt must retain the same key, destination, digest and bytes;
/// old rows with no exact recovery material remain recovery-only.
pub(crate) async fn validate_effect_dispatch_identity_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    previous: &EffectDispatchAttempt,
    key: &ProviderEffectKey,
    payload_digest: &Sha256Digest,
    wire_payload: &[u8],
    destination_id: &str,
) -> Result<(), TaskFlowError> {
    let differs: bool = sqlx::query_scalar(
        "SELECT EXISTS (
            SELECT 1 FROM taskflow_effect_dispatch_attempts
            WHERE owner_agent_id=? AND run_id=? AND step_id=?
              AND (provider_effect_key IS NULL OR provider_effect_key != ?
                   OR wire_payload IS NULL OR wire_payload != ?
                   OR payload_digest != ? OR destination_id != ?)
         )",
    )
    .bind(previous.owner_agent_id.as_str())
    .bind(&previous.run_id)
    .bind(&previous.step_id)
    .bind(key.as_str())
    .bind(wire_payload)
    .bind(payload_digest.as_str())
    .bind(destination_id)
    .fetch_one(&mut **transaction)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    if differs {
        return Err(identity_conflict());
    }
    Ok(())
}

fn identity_conflict() -> TaskFlowError {
    TaskFlowError::Conflict(
        "the original effect key and exact wire must be retained; legacy ambiguity requires recovery".to_string(),
    )
}
