//! Durable issuer/time/frontier owner outside the replaceable runtime identity.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::SignedTrustedTimeAttestation;
use codex_hepta_authbus::TrustedTimeAttestationClaims;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

use crate::ConsumerPortError;
use crate::authority_role_config::AuthorityKeys;
use crate::authority_role_config::SecretsAuthorityServiceConfig;
use crate::role_storage::RoleCommitFence;
use crate::role_storage::open_role_pool;
use crate::role_storage::unavailable;

static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./authority_migrations");

pub(crate) struct AuthorityRoleOwner {
    pub(super) pool: SqlitePool,
    pub config: SecretsAuthorityServiceConfig,
    pub(super) keys: AuthorityKeys,
    pub(super) profile: [u8; 32],
    pub(super) fenced: Arc<AtomicBool>,
}

impl AuthorityRoleOwner {
    pub async fn open(config: SecretsAuthorityServiceConfig) -> Result<Self, ConsumerPortError> {
        let (keys, profile) = config.keys_and_profile()?;
        let pool = open_role_pool(&config.database_path, &MIGRATOR).await?;
        let result = async {
            let mut tx = pool.begin_with("BEGIN IMMEDIATE").await.map_err(unavailable)?;
            let observed: Option<Vec<u8>> = sqlx::query_scalar("SELECT profile_sha256 FROM authority_role_meta WHERE singleton = 1")
                .fetch_optional(&mut *tx).await.map_err(unavailable)?;
            if let Some(observed) = observed {
                if observed != profile { return Err(ConsumerPortError::Conflict); }
            } else {
                let retained: i64 = sqlx::query_scalar("SELECT (SELECT COUNT(*) FROM authority_role_grant) + (SELECT COUNT(*) FROM authority_role_frontier) + (SELECT COUNT(*) FROM authority_role_frontier_history)")
                    .fetch_one(&mut *tx).await.map_err(unavailable)?;
                if retained != 0 { return Err(ConsumerPortError::Unavailable); }
                let initial = FinalUseFrontier::for_initial_head(&config.initial_revocations).map_err(unavailable)?;
                sqlx::query("INSERT INTO authority_role_meta VALUES(1,?,0,1)")
                    .bind(profile.as_slice()).execute(&mut *tx).await.map_err(unavailable)?;
                sqlx::query("INSERT INTO authority_role_frontier VALUES(?,?,?,?,?)")
                    .bind(&config.issuer_id).bind(integer(initial.authority_epoch)?)
                    .bind(integer(initial.revocation_revision)?).bind(initial.state_sha256.as_slice())
                    .bind(serde_json::to_vec(&config.initial_revocations).map_err(unavailable)?)
                    .execute(&mut *tx).await.map_err(unavailable)?;
                sqlx::query("INSERT INTO authority_role_frontier_history VALUES(?)")
                    .bind(initial.state_sha256.as_slice()).execute(&mut *tx).await.map_err(unavailable)?;
            }
            tx.commit().await.map_err(unavailable)
        }.await;
        if let Err(error) = result {
            pool.close().await;
            return Err(error);
        }
        Ok(Self {
            pool,
            config,
            keys,
            profile,
            fenced: Arc::new(AtomicBool::new(false)),
        })
    }

    pub(super) async fn begin(
        &self,
    ) -> Result<(Transaction<'static, Sqlite>, RoleCommitFence), ConsumerPortError> {
        let guard = RoleCommitFence::arm(&self.fenced)?;
        let tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        self.ensure_writer()?;
        Ok((tx, guard))
    }
    fn ensure_writer(&self) -> Result<(), ConsumerPortError> {
        if self.fenced.load(Ordering::Acquire) {
            Err(ConsumerPortError::Unavailable)
        } else {
            Ok(())
        }
    }
    pub(super) async fn commit(
        &self,
        tx: Transaction<'static, Sqlite>,
        mut guard: RoleCommitFence,
    ) -> Result<(), ConsumerPortError> {
        self.ensure_writer()?;
        tx.commit().await.map_err(unavailable)?;
        guard.committed();
        Ok(())
    }

    pub(super) async fn protected_wall(
        &self,
        tx: &mut Transaction<'static, Sqlite>,
    ) -> Result<u64, ConsumerPortError> {
        let now = u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(unavailable)?
                .as_millis(),
        )
        .map_err(unavailable)?;
        let previous: i64 = sqlx::query_scalar(
            "SELECT last_wall_time_ms FROM authority_role_meta WHERE singleton = 1",
        )
        .fetch_one(&mut **tx)
        .await
        .map_err(unavailable)?;
        if integer(now)? < previous {
            return Err(ConsumerPortError::Unavailable);
        }
        sqlx::query("UPDATE authority_role_meta SET last_wall_time_ms = ? WHERE singleton = 1")
            .bind(integer(now)?)
            .execute(&mut **tx)
            .await
            .map_err(unavailable)?;
        Ok(now)
    }

    pub async fn time(&self) -> Result<SignedTrustedTimeAttestation, ConsumerPortError> {
        let (mut tx, guard) = self.begin().await?;
        let now = self.protected_wall(&mut tx).await?;
        let revision: i64 = sqlx::query_scalar(
            "SELECT next_time_revision FROM authority_role_meta WHERE singleton = 1",
        )
        .fetch_one(&mut *tx)
        .await
        .map_err(unavailable)?;
        let next = revision.checked_add(1).ok_or(ConsumerPortError::Capacity)?;
        let source = serde_json::to_vec(&(
            "hepta.secrets.protected-host-time.v1",
            self.profile,
            now,
            revision,
        ))
        .map_err(unavailable)?;
        let claims = TrustedTimeAttestationClaims {
            issuer_id: StableId::new(&self.config.time_issuer_id).map_err(unavailable)?,
            key_epoch: Generation::new(self.config.time_key_epoch).map_err(unavailable)?,
            wall_time_ms: now,
            source_revision: u64::try_from(revision).map_err(unavailable)?,
            source_digest: Digest32::of_bytes(&source),
        };
        let signature = self.keys.time.sign(&claims.signing_bytes()).to_bytes();
        let updated = sqlx::query("UPDATE authority_role_meta SET next_time_revision = ? WHERE singleton = 1 AND next_time_revision = ?")
            .bind(next).bind(revision).execute(&mut *tx).await.map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(ConsumerPortError::Unavailable);
        }
        self.commit(tx, guard).await?;
        Ok(SignedTrustedTimeAttestation { claims, signature })
    }

    pub fn fence(&self) {
        self.fenced.store(true, Ordering::Release);
    }
    pub async fn close(&self) {
        self.pool.close().await;
    }
}

pub(crate) fn original_id(operation: &str) -> Result<(), ConsumerPortError> {
    if operation.is_empty()
        || operation.len() > 200
        || !operation
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        Err(ConsumerPortError::Invalid)
    } else {
        Ok(())
    }
}
pub(super) fn integer(value: u64) -> Result<i64, ConsumerPortError> {
    i64::try_from(value).map_err(unavailable)
}
