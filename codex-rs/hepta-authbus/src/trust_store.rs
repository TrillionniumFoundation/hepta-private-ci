use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::IssuerLifecycleState;
use crate::IssuerPurpose;
use crate::IssuerRecord;
use crate::IssuerRegistration;
use crate::IssuerRetirement;
use crate::IssuerSpec;
use crate::SignedTrustedTimeAttestation;
use crate::TrustedTimeSample;
use crate::authority_store::advance_time;
use crate::authority_store::begin;
use crate::authority_store::blob_array;
use crate::authority_store::next_revision;
use crate::authority_store::nonzero_u64;
use crate::authority_store::stable_id;
use crate::authority_store::storage;
use crate::authority_store::u64_bytes;

const MAX_ISSUER_EPOCHS: i64 = 4096;

impl AuthBusAuthorityStore {
    pub async fn enroll_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        let mut tx = begin(&self.pool).await?;
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_issuer_registry WHERE state != 'retired'",
        )
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        if count >= MAX_ISSUER_EPOCHS {
            return Err(AuthBusAuthorityError::CapacityExceeded);
        }
        let existing: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM authbus_issuer_registry
             WHERE issuer_id = ? AND purpose = ?)",
        )
        .bind(spec.issuer_id.as_str())
        .bind(purpose_text(purpose))
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        if existing {
            return Err(AuthBusAuthorityError::AlreadyExists);
        }
        insert_issuer(&mut tx, purpose, &spec).await?;
        let record = load_issuer(&mut tx, purpose, &spec.issuer_id, spec.key_epoch).await?;
        tx.commit().await.map_err(storage)?;
        Ok(record)
    }

    pub async fn rotate_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
        expected_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        let mut tx = begin(&self.pool).await?;
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_issuer_registry WHERE state != 'retired'",
        )
        .fetch_one(&mut *tx)
        .await
        .map_err(storage)?;
        if count >= MAX_ISSUER_EPOCHS {
            return Err(AuthBusAuthorityError::CapacityExceeded);
        }
        let current = load_active_issuer(&mut tx, purpose, &spec.issuer_id).await?;
        if current.key_epoch != expected_epoch || current.revision != expected_revision {
            return Err(AuthBusAuthorityError::RevisionConflict);
        }
        if spec.key_epoch <= current.key_epoch {
            return Err(AuthBusAuthorityError::KeyEpochRegression);
        }
        let next_old_revision = next_revision(current.revision)?;
        sqlx::query(
            "UPDATE authbus_issuer_registry SET state = 'revoked', revision = ?
             WHERE issuer_id = ? AND purpose = ? AND key_epoch = ?",
        )
        .bind(u64_bytes(next_old_revision).as_slice())
        .bind(current.issuer_id.as_str())
        .bind(purpose_text(purpose))
        .bind(current.key_epoch.get().to_be_bytes().as_slice())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        insert_issuer(&mut tx, purpose, &spec).await?;
        let record = load_issuer(&mut tx, purpose, &spec.issuer_id, spec.key_epoch).await?;
        tx.commit().await.map_err(storage)?;
        Ok(record)
    }

    pub async fn revoke_issuer(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        let mut tx = begin(&self.pool).await?;
        let mut record = load_issuer(&mut tx, purpose, issuer_id, key_epoch).await?;
        if record.state == IssuerLifecycleState::Revoked
            && record.revision == expected_revision.saturating_add(1)
        {
            tx.commit().await.map_err(storage)?;
            return Ok(record);
        }
        if record.state != IssuerLifecycleState::Active || record.revision != expected_revision {
            return Err(AuthBusAuthorityError::RevisionConflict);
        }
        record.state = IssuerLifecycleState::Revoked;
        record.revision = next_revision(record.revision)?;
        persist_issuer_state(&mut tx, &record).await?;
        tx.commit().await.map_err(storage)?;
        Ok(record)
    }

    pub async fn retire_issuer_epoch(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRetirement, AuthBusAuthorityError> {
        let mut tx = begin(&self.pool).await?;
        let mut record = load_issuer(&mut tx, purpose, issuer_id, key_epoch).await?;
        if record.state == IssuerLifecycleState::Retired
            && record.revision == expected_revision.saturating_add(1)
        {
            tx.commit().await.map_err(storage)?;
            return Ok(IssuerRetirement::from_record(&record));
        }
        if record.state != IssuerLifecycleState::Revoked || record.revision != expected_revision {
            return Err(AuthBusAuthorityError::InvalidTransition);
        }
        record.state = IssuerLifecycleState::Retired;
        record.revision = next_revision(record.revision)?;
        persist_issuer_state(&mut tx, &record).await?;
        let retirement = IssuerRetirement::from_record(&record);
        tx.commit().await.map_err(storage)?;
        Ok(retirement)
    }

    pub async fn issuer_record(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        let mut tx = begin(&self.pool).await?;
        let record = load_issuer(&mut tx, purpose, issuer_id, key_epoch).await?;
        tx.commit().await.map_err(storage)?;
        Ok(record)
    }

    pub async fn message_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<IssuerRegistration, AuthBusAuthorityError> {
        let record = self
            .issuer_record(IssuerPurpose::Message, issuer_id, key_epoch)
            .await?;
        Ok(IssuerRegistration {
            issuer_id: record.issuer_id,
            key_epoch: record.key_epoch,
            verifying_key: record.verifying_key,
            revoked: record.state != IssuerLifecycleState::Active,
        })
    }

    pub async fn observe_trusted_time_attestation(
        &self,
        attestation: &SignedTrustedTimeAttestation,
    ) -> Result<TrustedTimeSample, AuthBusAuthorityError> {
        let mut tx = begin(&self.pool).await?;
        let record = load_issuer(
            &mut tx,
            IssuerPurpose::TrustedTime,
            &attestation.claims.issuer_id,
            attestation.claims.key_epoch,
        )
        .await?;
        let sample = attestation.verify(&record)?;
        advance_time(&mut tx, &sample).await?;
        tx.commit().await.map_err(storage)?;
        Ok(sample)
    }
}

async fn insert_issuer(
    tx: &mut Transaction<'_, Sqlite>,
    purpose: IssuerPurpose,
    spec: &IssuerSpec,
) -> Result<(), AuthBusAuthorityError> {
    sqlx::query(
        "INSERT INTO authbus_issuer_registry
         (issuer_id, purpose, key_epoch, public_key, state, revision)
         VALUES (?, ?, ?, ?, 'active', ?)",
    )
    .bind(spec.issuer_id.as_str())
    .bind(purpose_text(purpose))
    .bind(spec.key_epoch.get().to_be_bytes().as_slice())
    .bind(spec.verifying_key.to_bytes().as_slice())
    .bind(u64_bytes(1).as_slice())
    .execute(&mut **tx)
    .await
    .map_err(|error| {
        if error
            .as_database_error()
            .is_some_and(sqlx::error::DatabaseError::is_unique_violation)
        {
            AuthBusAuthorityError::AlreadyExists
        } else {
            storage(error)
        }
    })?;
    Ok(())
}

async fn load_active_issuer(
    tx: &mut Transaction<'_, Sqlite>,
    purpose: IssuerPurpose,
    issuer_id: &StableId,
) -> Result<IssuerRecord, AuthBusAuthorityError> {
    let row = sqlx::query(
        "SELECT issuer_id, purpose, key_epoch, public_key, state, revision
         FROM authbus_issuer_registry WHERE issuer_id = ? AND purpose = ? AND state = 'active'",
    )
    .bind(issuer_id.as_str())
    .bind(purpose_text(purpose))
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?
    .ok_or(AuthBusAuthorityError::IssuerMissing)?;
    issuer_from_row(&row)
}

pub(crate) async fn load_issuer(
    tx: &mut Transaction<'_, Sqlite>,
    purpose: IssuerPurpose,
    issuer_id: &StableId,
    key_epoch: Generation,
) -> Result<IssuerRecord, AuthBusAuthorityError> {
    let row = sqlx::query(
        "SELECT issuer_id, purpose, key_epoch, public_key, state, revision
         FROM authbus_issuer_registry WHERE issuer_id = ? AND purpose = ? AND key_epoch = ?",
    )
    .bind(issuer_id.as_str())
    .bind(purpose_text(purpose))
    .bind(key_epoch.get().to_be_bytes().as_slice())
    .fetch_optional(&mut **tx)
    .await
    .map_err(storage)?
    .ok_or(AuthBusAuthorityError::IssuerMissing)?;
    issuer_from_row(&row)
}

async fn persist_issuer_state(
    tx: &mut Transaction<'_, Sqlite>,
    record: &IssuerRecord,
) -> Result<(), AuthBusAuthorityError> {
    sqlx::query(
        "UPDATE authbus_issuer_registry SET state = ?, revision = ?
         WHERE issuer_id = ? AND purpose = ? AND key_epoch = ?",
    )
    .bind(state_text(record.state))
    .bind(u64_bytes(record.revision).as_slice())
    .bind(record.issuer_id.as_str())
    .bind(purpose_text(record.purpose))
    .bind(record.key_epoch.get().to_be_bytes().as_slice())
    .execute(&mut **tx)
    .await
    .map_err(storage)?;
    Ok(())
}

fn issuer_from_row(row: &SqliteRow) -> Result<IssuerRecord, AuthBusAuthorityError> {
    let purpose: String = row.try_get("purpose").map_err(storage)?;
    let state: String = row.try_get("state").map_err(storage)?;
    let public_key = VerifyingKey::from_bytes(&blob_array::<32>(row, "public_key")?)
        .map_err(|_| AuthBusAuthorityError::CorruptState("invalid issuer public key"))?;
    Ok(IssuerRecord {
        issuer_id: stable_id(row.try_get("issuer_id").map_err(storage)?)?,
        purpose: parse_purpose(&purpose)?,
        key_epoch: Generation::new(nonzero_u64(row, "key_epoch")?)
            .map_err(|_| AuthBusAuthorityError::CorruptState("invalid issuer key epoch"))?,
        verifying_key: public_key,
        state: parse_state(&state)?,
        revision: nonzero_u64(row, "revision")?,
    })
}

pub(crate) fn purpose_text(purpose: IssuerPurpose) -> &'static str {
    match purpose {
        IssuerPurpose::Message => "message",
        IssuerPurpose::Settlement => "settlement",
        IssuerPurpose::TrustedTime => "trusted_time",
    }
}

fn parse_purpose(value: &str) -> Result<IssuerPurpose, AuthBusAuthorityError> {
    match value {
        "message" => Ok(IssuerPurpose::Message),
        "settlement" => Ok(IssuerPurpose::Settlement),
        "trusted_time" => Ok(IssuerPurpose::TrustedTime),
        _ => Err(AuthBusAuthorityError::CorruptState(
            "invalid issuer purpose",
        )),
    }
}

fn state_text(state: IssuerLifecycleState) -> &'static str {
    match state {
        IssuerLifecycleState::Active => "active",
        IssuerLifecycleState::Revoked => "revoked",
        IssuerLifecycleState::Retired => "retired",
    }
}

fn parse_state(value: &str) -> Result<IssuerLifecycleState, AuthBusAuthorityError> {
    match value {
        "active" => Ok(IssuerLifecycleState::Active),
        "revoked" => Ok(IssuerLifecycleState::Revoked),
        "retired" => Ok(IssuerLifecycleState::Retired),
        _ => Err(AuthBusAuthorityError::CorruptState("invalid issuer state")),
    }
}

#[cfg(test)]
#[path = "trust_store_tests.rs"]
mod tests;
