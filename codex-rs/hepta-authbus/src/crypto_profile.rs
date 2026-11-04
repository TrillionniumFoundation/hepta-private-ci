use sqlx::SqlitePool;

use crate::AuthBusAlgorithm;
use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::AuthBusVerifyingKey;
use crate::authority_store::begin;
use crate::authority_store::storage;

impl AuthBusAuthorityStore {
    /// Open an authority domain whose persisted issuer policy requires ML-DSA-65.
    /// Existing classical domains cannot be relabeled or downgraded on reopen.
    pub async fn open_pq(path: &std::path::Path) -> Result<Self, AuthBusAuthorityError> {
        Self::open_with_algorithm(path, AuthBusAlgorithm::MlDsa65V2).await
    }

    pub fn algorithm(&self) -> AuthBusAlgorithm {
        self.algorithm
    }

    pub(crate) fn require_key(
        &self,
        key: &AuthBusVerifyingKey,
    ) -> Result<(), AuthBusAuthorityError> {
        if key.algorithm() != self.algorithm {
            return Err(AuthBusAuthorityError::CryptoProfileMismatch);
        }
        AuthBusVerifyingKey::from_bytes(self.algorithm, key.as_bytes())
            .map_err(|_| AuthBusAuthorityError::InvalidInput("invalid issuer public key"))?;
        Ok(())
    }
}

pub(crate) async fn bind_profile(
    pool: &SqlitePool,
    algorithm: AuthBusAlgorithm,
) -> Result<(), AuthBusAuthorityError> {
    let mut tx = begin(pool).await?;
    let persisted: Option<i64> =
        sqlx::query_scalar("SELECT auth_version FROM authbus_crypto_profile WHERE singleton = 1")
            .fetch_optional(&mut *tx)
            .await
            .map_err(storage)?;
    match persisted {
        Some(version) if version != i64::from(algorithm.schema_version()) => {
            return Err(AuthBusAuthorityError::CryptoProfileMismatch);
        }
        Some(_) => {}
        None => {
            sqlx::query(
                "INSERT INTO authbus_crypto_profile(singleton, auth_version) VALUES (1, ?)",
            )
            .bind(i64::from(algorithm.schema_version()))
            .execute(&mut *tx)
            .await
            .map_err(storage)?;
        }
    }
    tx.commit().await.map_err(storage)
}

#[cfg(test)]
#[path = "crypto_profile_tests.rs"]
mod tests;
