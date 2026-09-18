use codex_hepta_authbus::AuthBusRollbackCheckpoint;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::authbus_control_store::AuthBusControlError;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

const ROLLBACK_GENESIS_DOMAIN: &[u8] = b"hepta.authbus.rollback-guard.genesis.v1";
const ROLLBACK_CHAIN_DOMAIN: &[u8] = b"hepta.authbus.rollback-guard.chain.v1\0";

impl HeptaEvidenceStore {
    pub async fn authbus_rollback_checkpoint(
        &self,
    ) -> Result<AuthBusRollbackCheckpoint, AuthBusControlError> {
        let mut tx = self.pool.begin().await.map_err(classify_sqlx_error)?;
        let checkpoint = rollback_checkpoint_in_transaction(&mut tx).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(checkpoint)
    }

    pub async fn verify_authbus_rollback_checkpoint(
        &self,
        expected: &AuthBusRollbackCheckpoint,
    ) -> Result<(), AuthBusControlError> {
        if !expected.validate() {
            return Err(AuthBusControlError::InvalidRequest(
                "invalid external rollback checkpoint",
            ));
        }
        let actual = self.authbus_rollback_checkpoint().await?;
        if &actual != expected {
            return Err(AuthBusControlError::RollbackDetected);
        }
        Ok(())
    }

    pub async fn install_authbus_issuer(
        &self,
        issuer: &IssuerRegistration,
    ) -> Result<(), AuthBusControlError> {
        if issuer.revoked {
            return Err(AuthBusControlError::InvalidRequest(
                "new issuer registration cannot start revoked",
            ));
        }
        let epoch = issuer.key_epoch.get();
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        if authbus_replay_epoch_retired(&mut tx, &issuer.issuer_id, issuer.key_epoch).await? {
            return Err(AuthBusControlError::RetiredIssuer);
        }
        let existing = load_issuer_row(&mut tx, &issuer.issuer_id, issuer.key_epoch).await?;
        if let Some(existing) = existing {
            if existing.state == "active"
                && existing.public_key == *issuer.verifying_key.as_bytes()
            {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(());
            }
            return Err(AuthBusControlError::ReservationConflict);
        }
        let head = load_issuer_head(&mut tx, &issuer.issuer_id).await?;
        if let Some(head_epoch) = head {
            if epoch <= head_epoch {
                return Err(AuthBusControlError::StalePolicyRevision);
            }
            let previous = load_issuer_row(
                &mut tx,
                &issuer.issuer_id,
                Generation::new(head_epoch).map_err(|_| {
                    AuthBusControlError::InvalidRequest("invalid issuer head epoch")
                })?,
            )
            .await?
            .ok_or_else(|| EvidenceError::Corrupt("AuthBus issuer head is dangling".into()))?;
            if previous.state != "revoked" && previous.state != "retired" {
                return Err(AuthBusControlError::InvalidRequest(
                    "revoke the current issuer epoch before rotating",
                ));
            }
        }
        let now = now_millis()?;
        let epoch_bytes = epoch.to_be_bytes();
        sqlx::query(
            "INSERT INTO authbus_issuer_registry(
                issuer_id, key_epoch, public_key, state, registered_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, 'active', ?, ?)",
        )
        .bind(issuer.issuer_id.as_str())
        .bind(epoch_bytes.as_slice())
        .bind(issuer.verifying_key.as_bytes().as_slice())
        .bind(now)
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        sqlx::query(
            "INSERT INTO authbus_issuer_heads(issuer_id, key_epoch, updated_at_ms)
             VALUES (?, ?, ?)
             ON CONFLICT(issuer_id) DO UPDATE SET
               key_epoch = excluded.key_epoch, updated_at_ms = excluded.updated_at_ms",
        )
        .bind(issuer.issuer_id.as_str())
        .bind(epoch_bytes.as_slice())
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let mut event = b"issuer-install\0".to_vec();
        push_text(&mut event, issuer.issuer_id.as_str());
        event.extend_from_slice(&epoch_bytes);
        event.extend_from_slice(issuer.verifying_key.as_bytes());
        advance_authbus_rollback_guard(&mut tx, &event).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }

    pub async fn revoke_authbus_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<(), AuthBusControlError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let existing = load_issuer_row(&mut tx, issuer_id, key_epoch)
            .await?
            .ok_or(AuthBusControlError::InvalidRequest("unknown issuer epoch"))?;
        match existing.state.as_str() {
            "revoked" => {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(());
            }
            "retired" => return Err(AuthBusControlError::RetiredIssuer),
            "active" => {}
            _ => return Err(EvidenceError::Corrupt("invalid AuthBus issuer state".into()).into()),
        }
        let now = now_millis()?;
        let epoch = key_epoch.get().to_be_bytes();
        sqlx::query(
            "UPDATE authbus_issuer_registry SET state = 'revoked', updated_at_ms = ?
             WHERE issuer_id = ? AND key_epoch = ?",
        )
        .bind(now)
        .bind(issuer_id.as_str())
        .bind(epoch.as_slice())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let mut event = b"issuer-revoke\0".to_vec();
        push_text(&mut event, issuer_id.as_str());
        event.extend_from_slice(&epoch);
        advance_authbus_rollback_guard(&mut tx, &event).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }

    pub async fn load_authbus_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<IssuerRegistration, AuthBusControlError> {
        let mut tx = self.pool.begin().await.map_err(classify_sqlx_error)?;
        if authbus_replay_epoch_retired(&mut tx, issuer_id, key_epoch).await? {
            return Err(AuthBusControlError::RetiredIssuer);
        }
        let row = load_issuer_row(&mut tx, issuer_id, key_epoch)
            .await?
            .ok_or(AuthBusControlError::InvalidRequest("unknown issuer epoch"))?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        let key = VerifyingKey::from_bytes(&row.public_key)
            .map_err(|_| EvidenceError::Corrupt("invalid stored AuthBus public key".into()))?;
        Ok(IssuerRegistration {
            issuer_id: issuer_id.clone(),
            key_epoch,
            verifying_key: key,
            revoked: row.state != "active",
        })
    }

    pub async fn retire_authbus_replay_epoch(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
        expected_checkpoint: &AuthBusRollbackCheckpoint,
    ) -> Result<AuthBusRollbackCheckpoint, AuthBusControlError> {
        if !expected_checkpoint.validate() {
            return Err(AuthBusControlError::InvalidRequest(
                "invalid retirement checkpoint",
            ));
        }
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let current_checkpoint = rollback_checkpoint_in_transaction(&mut tx).await?;
        if &current_checkpoint != expected_checkpoint {
            return Err(AuthBusControlError::RollbackDetected);
        }
        if authbus_replay_epoch_retired(&mut tx, issuer_id, key_epoch).await? {
            tx.commit().await.map_err(classify_sqlx_error)?;
            return Ok(current_checkpoint);
        }
        let issuer = load_issuer_row(&mut tx, issuer_id, key_epoch)
            .await?
            .ok_or(AuthBusControlError::InvalidRequest("unknown issuer epoch"))?;
        if issuer.state != "revoked" {
            return Err(AuthBusControlError::InvalidRequest(
                "only a revoked issuer epoch may be retired",
            ));
        }
        let head = load_issuer_head(&mut tx, issuer_id)
            .await?
            .ok_or_else(|| EvidenceError::Corrupt("AuthBus issuer has no head".into()))?;
        if head <= key_epoch.get() {
            return Err(AuthBusControlError::InvalidRequest(
                "a newer managed issuer epoch is required before retirement",
            ));
        }
        let epoch = key_epoch.get().to_be_bytes();
        let active_outbox: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_outbox
             WHERE issuer_id = ? AND key_epoch = ? AND state IN ('queued', 'leased')",
        )
        .bind(issuer_id.as_str())
        .bind(epoch.as_slice())
        .fetch_one(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if active_outbox != 0 {
            return Err(AuthBusControlError::InvalidRequest(
                "active deliveries block replay retirement",
            ));
        }
        let mut event = b"replay-retire\0".to_vec();
        push_text(&mut event, issuer_id.as_str());
        event.extend_from_slice(&epoch);
        let checkpoint = advance_authbus_rollback_guard(&mut tx, &event).await?;
        sqlx::query(
            "DELETE FROM authbus_replay_sequences WHERE issuer_id = ? AND key_epoch = ?",
        )
        .bind(issuer_id.as_str())
        .bind(epoch.as_slice())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        let checkpoint_generation = checkpoint.generation.to_be_bytes();
        let now = now_millis()?;
        sqlx::query(
            "INSERT INTO authbus_replay_retired_epochs(
                issuer_id, key_epoch, retired_checkpoint_generation, retired_at_ms
             ) VALUES (?, ?, ?, ?)",
        )
        .bind(issuer_id.as_str())
        .bind(epoch.as_slice())
        .bind(checkpoint_generation.as_slice())
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        sqlx::query(
            "UPDATE authbus_issuer_registry SET state = 'retired', updated_at_ms = ?
             WHERE issuer_id = ? AND key_epoch = ?",
        )
        .bind(now)
        .bind(issuer_id.as_str())
        .bind(epoch.as_slice())
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(checkpoint)
    }
}

pub(crate) async fn authbus_replay_epoch_retired(
    tx: &mut Transaction<'_, Sqlite>,
    issuer_id: &StableId,
    key_epoch: Generation,
) -> Result<bool, EvidenceError> {
    let epoch = key_epoch.get().to_be_bytes();
    sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM authbus_replay_retired_epochs
         WHERE issuer_id = ? AND key_epoch = ?)",
    )
    .bind(issuer_id.as_str())
    .bind(epoch.as_slice())
    .fetch_one(&mut **tx)
    .await
    .map_err(classify_sqlx_error)
}

pub(crate) async fn advance_authbus_rollback_guard(
    tx: &mut Transaction<'_, Sqlite>,
    event: &[u8],
) -> Result<AuthBusRollbackCheckpoint, EvidenceError> {
    if event.is_empty() || event.len() > 65_536 {
        return Err(EvidenceError::InvalidRecord(
            "invalid AuthBus rollback event".into(),
        ));
    }
    let current = rollback_checkpoint_in_transaction(tx).await?;
    let next_generation = current
        .generation
        .checked_add(1)
        .ok_or_else(|| EvidenceError::Unavailable("AuthBus rollback generation exhausted".into()))?;
    let mut bytes = ROLLBACK_CHAIN_DOMAIN.to_vec();
    bytes.extend_from_slice(&next_generation.to_be_bytes());
    bytes.extend_from_slice(current.chain_digest.as_array());
    bytes.extend_from_slice(
        &u32::try_from(event.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(event);
    let next = AuthBusRollbackCheckpoint {
        generation: next_generation,
        chain_digest: Digest32::of_bytes(&bytes),
    };
    let generation = next.generation.to_be_bytes();
    sqlx::query(
        "UPDATE authbus_rollback_guard
         SET generation = ?, chain_digest = ?, updated_at_ms = ? WHERE singleton = 1",
    )
    .bind(generation.as_slice())
    .bind(next.chain_digest.as_array().as_slice())
    .bind(now_millis()?)
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    Ok(next)
}

pub(crate) async fn verify_authbus_trust_rows(
    pool: &SqlitePool,
) -> Result<(), EvidenceError> {
    let guards = sqlx::query(
        "SELECT generation, chain_digest FROM authbus_rollback_guard WHERE singleton = 1",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if guards.len() != 1 {
        return Err(EvidenceError::Corrupt(
            "AuthBus rollback guard singleton is missing".into(),
        ));
    }
    let generation = u64_blob(&guards[0], "rollback generation")?;
    let digest = digest_column(&guards[0], "rollback chain digest")?;
    if generation == 0 && digest != Digest32::of_bytes(ROLLBACK_GENESIS_DOMAIN) {
        return Err(EvidenceError::Corrupt(
            "AuthBus rollback genesis digest is invalid".into(),
        ));
    }

    let heads = sqlx::query("SELECT issuer_id, key_epoch FROM authbus_issuer_heads")
        .fetch_all(pool)
        .await
        .map_err(classify_sqlx_error)?;
    for head in heads {
        let issuer_id: String = head.try_get("issuer_id").map_err(classify_sqlx_error)?;
        let epoch = u64_blob(&head, "key_epoch")?;
        let epoch_bytes = epoch.to_be_bytes();
        let highest: Vec<u8> = sqlx::query_scalar(
            "SELECT key_epoch FROM authbus_issuer_registry
             WHERE issuer_id = ? ORDER BY key_epoch DESC LIMIT 1",
        )
        .bind(&issuer_id)
        .fetch_one(pool)
        .await
        .map_err(classify_sqlx_error)?;
        if u64_blob_value(&highest, "highest issuer epoch")? != epoch {
            return Err(EvidenceError::Corrupt(format!(
                "AuthBus issuer head is not the highest enrolled epoch for {issuer_id}"
            )));
        }
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM authbus_issuer_registry
             WHERE issuer_id = ? AND key_epoch = ? AND state IN ('active', 'revoked')",
        )
        .bind(&issuer_id)
        .bind(epoch_bytes.as_slice())
        .fetch_one(pool)
        .await
        .map_err(classify_sqlx_error)?;
        if count != 1 {
            return Err(EvidenceError::Corrupt(format!(
                "AuthBus issuer head {issuer_id}/{epoch} is invalid"
            )));
        }
    }

    let retired = sqlx::query(
        "SELECT retired.issuer_id, retired.key_epoch, issuer.state
         FROM authbus_replay_retired_epochs AS retired
         LEFT JOIN authbus_issuer_registry AS issuer
           ON issuer.issuer_id = retired.issuer_id AND issuer.key_epoch = retired.key_epoch",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    for row in retired {
        let state: Option<String> = row.try_get("state").map_err(classify_sqlx_error)?;
        if state.as_deref() != Some("retired") {
            return Err(EvidenceError::Corrupt(
                "AuthBus replay tombstone does not match retired issuer state".into(),
            ));
        }
    }
    Ok(())
}

async fn rollback_checkpoint_in_transaction(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<AuthBusRollbackCheckpoint, EvidenceError> {
    let row = sqlx::query(
        "SELECT generation, chain_digest FROM authbus_rollback_guard WHERE singleton = 1",
    )
    .fetch_one(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    let checkpoint = AuthBusRollbackCheckpoint {
        generation: u64_blob(&row, "generation")?,
        chain_digest: digest_column(&row, "chain_digest")?,
    };
    if !checkpoint.validate() {
        return Err(EvidenceError::Corrupt(
            "invalid AuthBus rollback checkpoint".into(),
        ));
    }
    Ok(checkpoint)
}

#[derive(Debug)]
struct StoredIssuer {
    public_key: [u8; 32],
    state: String,
}

async fn load_issuer_row(
    tx: &mut Transaction<'_, Sqlite>,
    issuer_id: &StableId,
    key_epoch: Generation,
) -> Result<Option<StoredIssuer>, EvidenceError> {
    let epoch = key_epoch.get().to_be_bytes();
    sqlx::query(
        "SELECT public_key, state FROM authbus_issuer_registry
         WHERE issuer_id = ? AND key_epoch = ?",
    )
    .bind(issuer_id.as_str())
    .bind(epoch.as_slice())
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?
    .map(|row| {
        let key: Vec<u8> = row.try_get("public_key").map_err(classify_sqlx_error)?;
        let public_key: [u8; 32] = key
            .try_into()
            .map_err(|_| EvidenceError::Corrupt("invalid AuthBus public key width".into()))?;
        let state: String = row.try_get("state").map_err(classify_sqlx_error)?;
        if !matches!(state.as_str(), "active" | "revoked" | "retired") {
            return Err(EvidenceError::Corrupt("invalid AuthBus issuer state".into()));
        }
        Ok(StoredIssuer { public_key, state })
    })
    .transpose()
}

async fn load_issuer_head(
    tx: &mut Transaction<'_, Sqlite>,
    issuer_id: &StableId,
) -> Result<Option<u64>, EvidenceError> {
    let value: Option<Vec<u8>> = sqlx::query_scalar(
        "SELECT key_epoch FROM authbus_issuer_heads WHERE issuer_id = ?",
    )
    .bind(issuer_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    value
        .map(|value| u64_blob_value(&value, "issuer head epoch"))
        .transpose()
}

fn u64_blob(row: &SqliteRow, name: &str) -> Result<u64, EvidenceError> {
    let value: Vec<u8> = row.try_get(name).map_err(classify_sqlx_error)?;
    u64_blob_value(&value, name)
}

fn u64_blob_value(value: &[u8], name: &str) -> Result<u64, EvidenceError> {
    let bytes: [u8; 8] = value
        .try_into()
        .map_err(|_| EvidenceError::Corrupt(format!("invalid AuthBus {name} width")))?;
    Ok(u64::from_be_bytes(bytes))
}

fn digest_column(row: &SqliteRow, name: &str) -> Result<Digest32, EvidenceError> {
    let value: Vec<u8> = row.try_get(name).map_err(classify_sqlx_error)?;
    let bytes: [u8; 32] = value
        .try_into()
        .map_err(|_| EvidenceError::Corrupt(format!("invalid AuthBus {name} width")))?;
    let digest = Digest32::from_array(bytes);
    if digest.is_zero() {
        return Err(EvidenceError::Corrupt(format!("empty AuthBus {name}")));
    }
    Ok(digest)
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}
