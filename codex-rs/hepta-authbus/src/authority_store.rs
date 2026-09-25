use std::path::Path;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

use crate::AuthBusAuthorityError;
use crate::AuthPolicy;
use crate::PolicyDecision;
use crate::PolicyEffect;
use crate::PolicySpec;
use crate::TrustedTimeSample;

const MAX_POLICIES: i64 = 4096;
static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

#[derive(Clone)]
pub(crate) struct AuthBusAuthorityStore {
    pub(crate) pool: SqlitePool,
}

impl AuthBusAuthorityStore {
    pub async fn open(path: &Path) -> Result<Self, AuthBusAuthorityError> {
        let pool = codex_state::open_durable_sqlite_pool(path, /*max_connections*/ 5)
            .await
            .map_err(storage)?;
        let quick_check: String = sqlx::query_scalar("PRAGMA quick_check")
            .fetch_one(&pool)
            .await
            .map_err(storage)?;
        if quick_check != "ok" {
            pool.close().await;
            return Err(AuthBusAuthorityError::CorruptState(
                "SQLite quick_check failed",
            ));
        }
        if let Err(error) = MIGRATOR.run(&pool).await {
            pool.close().await;
            return Err(storage(error));
        }
        if let Err(error) = crate::authority_schema::verify_schema(&pool, &MIGRATOR).await {
            pool.close().await;
            return Err(error);
        }
        sqlx::query(
            "UPDATE authbus_recovery_state
             SET recovery_required = (
                 SELECT EXISTS(
                     SELECT 1 FROM authbus_quota_reservation
                     WHERE state = 'dispatch_attempted'
                 )
             )
             WHERE singleton = 1",
        )
        .execute(&pool)
        .await
        .map_err(storage)?;
        Ok(Self { pool })
    }

    pub async fn observe_time(&self, time: TrustedTimeSample) -> Result<(), AuthBusAuthorityError> {
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, &time).await?;
        tx.commit().await.map_err(storage)
    }

    #[cfg(test)]
    pub async fn last_trusted_time(
        &self,
    ) -> Result<Option<TrustedTimeSample>, AuthBusAuthorityError> {
        let row = sqlx::query(
            "SELECT wall_time_ms, source_revision, source_digest
             FROM authbus_trusted_time WHERE singleton = 1",
        )
        .fetch_optional(&self.pool)
        .await
        .map_err(storage)?;
        row.map(|row| trusted_time_from_row(&row)).transpose()
    }

    pub async fn create_policy(
        &self,
        spec: PolicySpec,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        validate_policy_spec(&spec)?;
        self.observe_time(time.clone()).await?;
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, &time).await?;
        let archived: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM authbus_policy_archive WHERE policy_id = ?)",
        )
        .bind(spec.policy_id.as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        if archived {
            return Err(AuthBusAuthorityError::AlreadyExists);
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_policy")
            .fetch_one(&mut *tx)
            .await
            .map_err(storage)?;
        if count >= MAX_POLICIES {
            return Err(AuthBusAuthorityError::CapacityExceeded);
        }
        let result = sqlx::query(
            "INSERT INTO authbus_policy
             (policy_id, principal, action, scope_digest, effect, revision,
              not_before_ms, expires_at_ms, revoked)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
        )
        .bind(spec.policy_id.as_str())
        .bind(spec.principal.as_str())
        .bind(spec.action.as_str())
        .bind(spec.scope_digest.as_array().as_slice())
        .bind(effect_text(spec.effect))
        .bind(u64_bytes(1).as_slice())
        .bind(u64_bytes(spec.not_before_ms).as_slice())
        .bind(u64_bytes(spec.expires_at_ms).as_slice())
        .execute(&mut *tx)
        .await;
        if let Err(error) = result {
            if is_unique_violation(&error) {
                return Err(AuthBusAuthorityError::AlreadyExists);
            }
            return Err(storage(error));
        }
        let policy = AuthPolicy {
            policy_id: spec.policy_id,
            principal: spec.principal,
            action: spec.action,
            scope_digest: spec.scope_digest,
            effect: spec.effect,
            revision: 1,
            not_before_ms: spec.not_before_ms,
            expires_at_ms: spec.expires_at_ms,
            revoked: false,
        };
        record_policy_history(&mut tx, &policy).await?;
        tx.commit().await.map_err(storage)?;
        Ok(policy)
    }

    pub async fn replace_policy(
        &self,
        spec: PolicySpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        validate_policy_spec(&spec)?;
        self.observe_time(time.clone()).await?;
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, &time).await?;
        let mut current = load_policy_by_id(&mut tx, &spec.policy_id).await?;
        if current.revision != expected_revision {
            return Err(AuthBusAuthorityError::RevisionConflict);
        }
        if current.revoked
            || current.principal != spec.principal
            || current.action != spec.action
            || current.scope_digest != spec.scope_digest
        {
            return Err(AuthBusAuthorityError::InvalidTransition);
        }
        current.effect = spec.effect;
        current.not_before_ms = spec.not_before_ms;
        current.expires_at_ms = spec.expires_at_ms;
        current.revision = next_revision(current.revision)?;
        sqlx::query(
            "UPDATE authbus_policy SET effect = ?, revision = ?,
             not_before_ms = ?, expires_at_ms = ? WHERE policy_id = ?",
        )
        .bind(effect_text(current.effect))
        .bind(u64_bytes(current.revision).as_slice())
        .bind(u64_bytes(current.not_before_ms).as_slice())
        .bind(u64_bytes(current.expires_at_ms).as_slice())
        .bind(current.policy_id.as_str())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        record_policy_history(&mut tx, &current).await?;
        tx.commit().await.map_err(storage)?;
        Ok(current)
    }

    pub async fn revoke_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.observe_time(time.clone()).await?;
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, &time).await?;
        let mut current = load_policy_by_id(&mut tx, policy_id).await?;
        if current.revision != expected_revision {
            return Err(AuthBusAuthorityError::RevisionConflict);
        }
        if !current.revoked {
            current.revoked = true;
            current.revision = next_revision(current.revision)?;
            sqlx::query("UPDATE authbus_policy SET revoked = 1, revision = ? WHERE policy_id = ?")
                .bind(u64_bytes(current.revision).as_slice())
                .bind(policy_id.as_str())
                .execute(&mut *tx)
                .await
                .map_err(storage)?;
            record_policy_history(&mut tx, &current).await?;
        }
        tx.commit().await.map_err(storage)?;
        Ok(current)
    }

    pub async fn retire_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        retired_at_ms: u64,
    ) -> Result<(), AuthBusAuthorityError> {
        if expected_revision == 0 || retired_at_ms == 0 {
            return Err(AuthBusAuthorityError::InvalidInput(
                "policy retirement requires revision and time",
            ));
        }
        let mut tx = begin(&self.pool).await?;
        let current = load_policy_by_id(&mut tx, policy_id).await?;
        if current.revision != expected_revision || !current.revoked {
            return Err(AuthBusAuthorityError::InvalidTransition);
        }
        let references: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_quota_reservation
             WHERE policy_id = ? AND state IN ('held','dispatch_attempted','indeterminate')",
        )
        .bind(policy_id.as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        if references != 0 {
            return Err(AuthBusAuthorityError::PolicyInUse);
        }
        sqlx::query(
            "INSERT INTO authbus_policy_archive
             (policy_id, principal, action, scope_digest, effect, revision,
              not_before_ms, expires_at_ms, revoked, retired_at_ms)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
        )
        .bind(current.policy_id.as_str())
        .bind(current.principal.as_str())
        .bind(current.action.as_str())
        .bind(current.scope_digest.as_array().as_slice())
        .bind(effect_text(current.effect))
        .bind(u64_bytes(current.revision).as_slice())
        .bind(u64_bytes(current.not_before_ms).as_slice())
        .bind(u64_bytes(current.expires_at_ms).as_slice())
        .bind(u64_bytes(retired_at_ms).as_slice())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        sqlx::query("DELETE FROM authbus_policy WHERE policy_id = ?")
            .bind(policy_id.as_str())
            .execute(&mut *tx)
            .await
            .map_err(storage)?;
        tx.commit().await.map_err(storage)
    }

    pub async fn authorize(
        &self,
        principal: &StableId,
        action: &StableId,
        scope_digest: Digest32,
        policy_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<PolicyDecision, AuthBusAuthorityError> {
        if scope_digest.is_zero() || policy_revision == 0 {
            return Err(AuthBusAuthorityError::InvalidInput(
                "authorization requires non-zero scope and policy revision",
            ));
        }
        self.observe_time(time.clone()).await?;
        let mut tx = begin(&self.pool).await?;
        advance_time(&mut tx, &time).await?;
        let row = sqlx::query(
            "SELECT policy_id, principal, action, scope_digest, effect, revision,
                    not_before_ms, expires_at_ms, revoked
             FROM authbus_policy WHERE principal = ? AND action = ? AND scope_digest = ?",
        )
        .bind(principal.as_str())
        .bind(action.as_str())
        .bind(scope_digest.as_array().as_slice())
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage)?
        .ok_or(AuthBusAuthorityError::PolicyMissing)?;
        let policy = policy_from_row(&row)?;
        if policy.revision != policy_revision {
            return Err(AuthBusAuthorityError::StalePolicyRevision);
        }
        if policy.revoked
            || time.wall_time_ms < policy.not_before_ms
            || time.wall_time_ms >= policy.expires_at_ms
        {
            return Err(AuthBusAuthorityError::PolicyUnavailable);
        }
        let decision = PolicyDecision::new(&policy, &time);
        tx.commit().await.map_err(storage)?;
        Ok(decision)
    }
}

pub(crate) async fn begin(
    pool: &SqlitePool,
) -> Result<Transaction<'static, Sqlite>, AuthBusAuthorityError> {
    pool.begin_with("BEGIN IMMEDIATE").await.map_err(storage)
}

pub(crate) async fn advance_time(
    tx: &mut Transaction<'_, Sqlite>,
    sample: &TrustedTimeSample,
) -> Result<(), AuthBusAuthorityError> {
    if sample.wall_time_ms == 0 || sample.source_revision == 0 || sample.source_digest.is_zero() {
        return Err(AuthBusAuthorityError::InvalidInput(
            "trusted time must bind non-zero time, revision and source digest",
        ));
    }
    let previous = sqlx::query(
        "SELECT wall_time_ms, source_revision, source_digest
         FROM authbus_trusted_time WHERE singleton = 1",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?;
    if let Some(previous) = previous {
        let prior = trusted_time_from_row(&previous)?;
        if sample.source_revision < prior.source_revision
            || sample.wall_time_ms < prior.wall_time_ms
        {
            return Err(AuthBusAuthorityError::ClockRollback);
        }
        if sample.source_revision == prior.source_revision && sample != &prior {
            return Err(AuthBusAuthorityError::TimeConflict);
        }
    }
    sqlx::query(
        "INSERT INTO authbus_trusted_time
         (singleton, wall_time_ms, source_revision, source_digest) VALUES (1, ?, ?, ?)
         ON CONFLICT(singleton) DO UPDATE SET
         wall_time_ms = excluded.wall_time_ms,
         source_revision = excluded.source_revision,
         source_digest = excluded.source_digest",
    )
    .bind(u64_bytes(sample.wall_time_ms).as_slice())
    .bind(u64_bytes(sample.source_revision).as_slice())
    .bind(sample.source_digest.as_array().as_slice())
    .execute(&mut **tx)
    .await
    .map_err(storage)?;
    Ok(())
}

async fn record_policy_history(
    tx: &mut Transaction<'_, Sqlite>,
    policy: &AuthPolicy,
) -> Result<(), AuthBusAuthorityError> {
    sqlx::query(
        "INSERT INTO authbus_policy_history
         (policy_id, principal, action, scope_digest, effect, revision,
          not_before_ms, expires_at_ms, revoked)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(policy.policy_id.as_str())
    .bind(policy.principal.as_str())
    .bind(policy.action.as_str())
    .bind(policy.scope_digest.as_array().as_slice())
    .bind(effect_text(policy.effect))
    .bind(u64_bytes(policy.revision).as_slice())
    .bind(u64_bytes(policy.not_before_ms).as_slice())
    .bind(u64_bytes(policy.expires_at_ms).as_slice())
    .bind(if policy.revoked { 1_i64 } else { 0_i64 })
    .execute(&mut **tx)
    .await
    .map_err(storage)?;
    Ok(())
}

pub(crate) async fn load_policy_by_id(
    tx: &mut Transaction<'_, Sqlite>,
    policy_id: &StableId,
) -> Result<AuthPolicy, AuthBusAuthorityError> {
    let row = sqlx::query(
        "SELECT policy_id, principal, action, scope_digest, effect, revision,
                not_before_ms, expires_at_ms, revoked
         FROM authbus_policy WHERE policy_id = ?",
    )
    .bind(policy_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?
    .ok_or(AuthBusAuthorityError::NotFound)?;
    policy_from_row(&row)
}

fn policy_from_row(row: &sqlx::sqlite::SqliteRow) -> Result<AuthPolicy, AuthBusAuthorityError> {
    let effect: String = row.try_get("effect").map_err(storage)?;
    let revoked: i64 = row.try_get("revoked").map_err(storage)?;
    let policy = AuthPolicy {
        policy_id: stable_id(row.try_get("policy_id").map_err(storage)?)?,
        principal: stable_id(row.try_get("principal").map_err(storage)?)?,
        action: stable_id(row.try_get("action").map_err(storage)?)?,
        scope_digest: Digest32::from_array(blob_array::<32>(row, "scope_digest")?),
        effect: policy_effect(&effect)?,
        revision: nonzero_u64(row, "revision")?,
        not_before_ms: nonzero_u64(row, "not_before_ms")?,
        expires_at_ms: nonzero_u64(row, "expires_at_ms")?,
        revoked: match revoked {
            0 => false,
            1 => true,
            _ => {
                return Err(AuthBusAuthorityError::CorruptState(
                    "invalid policy revocation flag",
                ));
            }
        },
    };
    if policy.scope_digest.is_zero() || policy.expires_at_ms <= policy.not_before_ms {
        return Err(AuthBusAuthorityError::CorruptState("invalid policy record"));
    }
    Ok(policy)
}

fn trusted_time_from_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<TrustedTimeSample, AuthBusAuthorityError> {
    TrustedTimeSample::new(
        nonzero_u64(row, "wall_time_ms")?,
        nonzero_u64(row, "source_revision")?,
        Digest32::from_array(blob_array::<32>(row, "source_digest")?),
    )
}

fn validate_policy_spec(spec: &PolicySpec) -> Result<(), AuthBusAuthorityError> {
    if spec.scope_digest.is_zero()
        || spec.not_before_ms == 0
        || spec.expires_at_ms <= spec.not_before_ms
    {
        return Err(AuthBusAuthorityError::InvalidInput(
            "policy scope or validity window is invalid",
        ));
    }
    Ok(())
}

fn effect_text(effect: PolicyEffect) -> &'static str {
    match effect {
        PolicyEffect::Allow => "allow",
        PolicyEffect::Deny => "deny",
    }
}

fn policy_effect(value: &str) -> Result<PolicyEffect, AuthBusAuthorityError> {
    match value {
        "allow" => Ok(PolicyEffect::Allow),
        "deny" => Ok(PolicyEffect::Deny),
        _ => Err(AuthBusAuthorityError::CorruptState("invalid policy effect")),
    }
}

pub(crate) fn next_revision(revision: u64) -> Result<u64, AuthBusAuthorityError> {
    revision
        .checked_add(1)
        .ok_or(AuthBusAuthorityError::CapacityExceeded)
}

pub(crate) fn nonzero_u64(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<u64, AuthBusAuthorityError> {
    let value = u64::from_be_bytes(blob_array::<8>(row, column)?);
    if value == 0 {
        return Err(AuthBusAuthorityError::CorruptState("zero monotonic value"));
    }
    Ok(value)
}

pub(crate) fn blob_array<const N: usize>(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<[u8; N], AuthBusAuthorityError> {
    row.try_get::<Vec<u8>, _>(column)
        .map_err(storage)?
        .try_into()
        .map_err(|_| AuthBusAuthorityError::CorruptState("invalid fixed-width field"))
}

pub(crate) fn stable_id(value: String) -> Result<StableId, AuthBusAuthorityError> {
    StableId::new(value)
        .map_err(|_| AuthBusAuthorityError::CorruptState("invalid stable identifier"))
}

pub(crate) fn u64_bytes(value: u64) -> [u8; 8] {
    value.to_be_bytes()
}

fn is_unique_violation(error: &sqlx::Error) -> bool {
    error
        .as_database_error()
        .is_some_and(sqlx::error::DatabaseError::is_unique_violation)
}

pub(crate) fn storage(error: impl ToString) -> AuthBusAuthorityError {
    AuthBusAuthorityError::Storage(error.to_string())
}

#[cfg(test)]
#[path = "authority_store_tests.rs"]
mod tests;
