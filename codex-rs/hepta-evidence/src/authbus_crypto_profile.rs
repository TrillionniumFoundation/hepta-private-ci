use codex_hepta_authbus::AuthBusAlgorithm;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

use crate::AuthBusAdmissionError;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;

impl HeptaEvidenceStore {
    /// Bind the trusted owner's AuthBus domain before initial checkpointing.
    /// The profile is immutable, including across process recovery and reconnect.
    pub async fn bind_authbus_profile(
        &self,
        algorithm: AuthBusAlgorithm,
    ) -> Result<(), AuthBusAdmissionError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let current = profile(&mut tx).await?;
        if current.is_none() {
            let used: bool = sqlx::query_scalar(
                "SELECT EXISTS(SELECT 1 FROM authbus_replay_sequences) OR
                 EXISTS(SELECT 1 FROM authbus_outbox) OR
                 EXISTS(SELECT 1 FROM authbus_retired_epochs) OR
                 EXISTS(SELECT 1 FROM authbus_restore_checkpoint)",
            )
            .fetch_one(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
            if used && algorithm != AuthBusAlgorithm::Ed25519V1 {
                return Err(AuthBusAdmissionError::CryptoProfileMismatch);
            }
            sqlx::query("INSERT INTO authbus_crypto_profile VALUES (1, ?)")
                .bind(i64::from(algorithm.schema_version()))
                .execute(&mut *tx)
                .await
                .map_err(classify_sqlx_error)?;
        }
        require_algorithm(&mut tx, algorithm).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(())
    }
}

pub(crate) async fn profile(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<Option<i64>, EvidenceError> {
    sqlx::query_scalar("SELECT auth_version FROM authbus_crypto_profile WHERE singleton = 1")
        .fetch_optional(&mut **tx)
        .await
        .map_err(classify_sqlx_error)
}

pub(crate) async fn require_algorithm(
    tx: &mut Transaction<'_, Sqlite>,
    algorithm: AuthBusAlgorithm,
) -> Result<(), AuthBusAdmissionError> {
    match profile(tx).await? {
        None if algorithm == AuthBusAlgorithm::Ed25519V1 => {
            sqlx::query("INSERT INTO authbus_crypto_profile VALUES (1, 1)")
                .execute(&mut **tx)
                .await
                .map_err(classify_sqlx_error)?;
        }
        Some(version) if version == i64::from(algorithm.schema_version()) => {}
        _ => return Err(AuthBusAdmissionError::CryptoProfileMismatch),
    }
    Ok(())
}

pub(crate) async fn verify_schema(pool: &SqlitePool) -> Result<(), EvidenceError> {
    // Exact definitions prevent a replacement trigger that merely contains a
    // marker string from masquerading as the immutable downgrade barrier.
    const DEFINITIONS: &[(&str, &str)] = &[
        (
            "authbus_crypto_profile",
            "CREATE TABLE authbus_crypto_profile (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), auth_version INTEGER NOT NULL CHECK (auth_version IN (1, 2))) WITHOUT ROWID",
        ),
        (
            "authbus_profile_immutable",
            "CREATE TRIGGER authbus_profile_immutable BEFORE UPDATE ON authbus_crypto_profile BEGIN SELECT RAISE(ABORT, 'AuthBus cryptographic profile is immutable'); END",
        ),
        (
            "authbus_profile_no_delete",
            "CREATE TRIGGER authbus_profile_no_delete BEFORE DELETE ON authbus_crypto_profile BEGIN SELECT RAISE(ABORT, 'AuthBus cryptographic profile cannot be deleted'); END",
        ),
        (
            "authbus_issuer_floor",
            "CREATE TABLE authbus_issuer_floor (issuer_id TEXT PRIMARY KEY, key_epoch BLOB NOT NULL CHECK (length(key_epoch) = 8), public_key BLOB NOT NULL CHECK (length(public_key) = 1974), revoked INTEGER NOT NULL CHECK (revoked IN (0, 1)), wall_time_floor_ms INTEGER NOT NULL CHECK (wall_time_floor_ms >= 0)) WITHOUT ROWID",
        ),
        (
            "authbus_issuer_floor_monotonic",
            "CREATE TRIGGER authbus_issuer_floor_monotonic BEFORE UPDATE ON authbus_issuer_floor WHEN NEW.issuer_id != OLD.issuer_id OR NEW.key_epoch < OLD.key_epoch OR NEW.wall_time_floor_ms < OLD.wall_time_floor_ms OR (NEW.key_epoch = OLD.key_epoch AND (NEW.public_key != OLD.public_key OR NEW.revoked < OLD.revoked)) BEGIN SELECT RAISE(ABORT, 'AuthBus issuer floor cannot regress'); END",
        ),
        (
            "authbus_issuer_floor_no_delete",
            "CREATE TRIGGER authbus_issuer_floor_no_delete BEFORE DELETE ON authbus_issuer_floor BEGIN SELECT RAISE(ABORT, 'AuthBus issuer floor cannot be deleted'); END",
        ),
    ];
    for (name, expected) in DEFINITIONS {
        let actual: Option<String> =
            sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = ?")
                .bind(name)
                .fetch_optional(pool)
                .await
                .map_err(classify_sqlx_error)?;
        let normalize = |text: &str| {
            text.chars()
                .filter(|ch| !ch.is_ascii_whitespace())
                .collect::<String>()
                .to_ascii_lowercase()
        };
        if actual.is_none_or(|actual| normalize(&actual) != normalize(expected)) {
            return Err(EvidenceError::Corrupt(
                "invalid AuthBus cryptographic profile schema".into(),
            ));
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "authbus_crypto_profile_tests.rs"]
mod tests;
