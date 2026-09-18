use std::fmt;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

pub const SECRET_LEASE_SCHEMA_VERSION_V1: u32 = 1;
const SECRET_LEASE_DB_FILENAME: &str = "heptabao_leases_1.sqlite3";
const MAX_OPERATION_ROWS: i64 = 1_000_000;
const MAX_LEASE_ROWS: i64 = 250_000;
static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SecretLeaseStateV1 {
    Active,
    RenewIndeterminate,
    RevokeIndeterminate,
    Revoked,
    Expired,
}

impl SecretLeaseStateV1 {
    fn as_str(self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::RenewIndeterminate => "renew_indeterminate",
            Self::RevokeIndeterminate => "revoke_indeterminate",
            Self::Revoked => "revoked",
            Self::Expired => "expired",
        }
    }

    fn parse(value: &str) -> Result<Self, SecretLeaseStoreError> {
        match value {
            "active" => Ok(Self::Active),
            "renew_indeterminate" => Ok(Self::RenewIndeterminate),
            "revoke_indeterminate" => Ok(Self::RevokeIndeterminate),
            "revoked" => Ok(Self::Revoked),
            "expired" => Ok(Self::Expired),
            _ => Err(SecretLeaseStoreError::Corrupt),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SecretLeaseOperationKindV1 {
    Issue,
    Renew,
    Revoke,
}

impl SecretLeaseOperationKindV1 {
    fn as_str(self) -> &'static str {
        match self {
            Self::Issue => "issue",
            Self::Renew => "renew",
            Self::Revoke => "revoke",
        }
    }

    fn parse(value: &str) -> Result<Self, SecretLeaseStoreError> {
        match value {
            "issue" => Ok(Self::Issue),
            "renew" => Ok(Self::Renew),
            "revoke" => Ok(Self::Revoke),
            _ => Err(SecretLeaseStoreError::Corrupt),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SecretLeaseOperationStateV1 {
    Prepared,
    Dispatching,
    Applied,
    NotApplied,
    Indeterminate,
}

impl SecretLeaseOperationStateV1 {
    fn as_str(self) -> &'static str {
        match self {
            Self::Prepared => "prepared",
            Self::Dispatching => "dispatching",
            Self::Applied => "applied",
            Self::NotApplied => "not_applied",
            Self::Indeterminate => "indeterminate",
        }
    }

    fn parse(value: &str) -> Result<Self, SecretLeaseStoreError> {
        match value {
            "prepared" => Ok(Self::Prepared),
            "dispatching" => Ok(Self::Dispatching),
            "applied" => Ok(Self::Applied),
            "not_applied" => Ok(Self::NotApplied),
            "indeterminate" => Ok(Self::Indeterminate),
            _ => Err(SecretLeaseStoreError::Corrupt),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretLeaseMetadataV1 {
    pub schema_version: u32,
    pub lease_id: String,
    pub provider_mount: String,
    pub consumer_id: String,
    pub scope_sha256: [u8; 32],
    pub request_sha256: [u8; 32],
    pub fingerprint_key_id: String,
    pub secret_fingerprint: [u8; 32],
    pub renewable: bool,
    pub issued_at_ms: u64,
    pub expires_at_ms: u64,
    pub rotation_generation: u64,
    pub state: SecretLeaseStateV1,
    pub revision: u64,
}

impl SecretLeaseMetadataV1 {
    pub fn is_usable_at(&self, now_ms: u64) -> bool {
        self.schema_version == SECRET_LEASE_SCHEMA_VERSION_V1
            && self.state == SecretLeaseStateV1::Active
            && now_ms < self.expires_at_ms
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretLeaseOperationV1 {
    pub operation_id: String,
    pub kind: SecretLeaseOperationKindV1,
    pub lease_id: Option<String>,
    pub semantic_sha256: [u8; 32],
    pub state: SecretLeaseOperationStateV1,
    pub observed_sha256: Option<[u8; 32]>,
    pub created_at_ms: u64,
    pub updated_at_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SecretLeaseOperationAdmissionV1 {
    Prepared,
    AlreadyPrepared,
    AlreadyApplied,
    NotApplied,
    Indeterminate,
    Dispatching,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SecretLeaseIssueObservationV1 {
    Applied(SecretLeaseMetadataV1),
    NotApplied,
    Unknown,
}

#[derive(Clone)]
pub struct SecretLeaseStore {
    pool: SqlitePool,
    path: PathBuf,
}

impl fmt::Debug for SecretLeaseStore {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SecretLeaseStore")
            .field("path", &self.path)
            .field("pool", &"[DURABLE SQLITE]")
            .finish()
    }
}

impl SecretLeaseStore {
    pub async fn open(root: impl AsRef<Path>) -> Result<Self, SecretLeaseStoreError> {
        let root = root.as_ref();
        create_private_directory(root)?;
        let sqlite_home = AbsolutePathBuf::try_from(root.to_path_buf())
            .map_err(|_| SecretLeaseStoreError::Invalid)?;
        let path = root.join(SECRET_LEASE_DB_FILENAME);
        let pool = SqliteConfig::from_sqlite_home(sqlite_home)
            .open_durable_evidence_pool(&path)
            .await
            .map_err(unavailable)?;
        if MIGRATOR.run(&pool).await.is_err() {
            pool.close().await;
            return Err(SecretLeaseStoreError::Unavailable);
        }
        protect_database_file(&path)?;
        sqlx::query(
            "INSERT INTO secret_lease_meta (singleton, schema_version)
             VALUES (1, ?) ON CONFLICT(singleton) DO NOTHING",
        )
        .bind(i64::from(SECRET_LEASE_SCHEMA_VERSION_V1))
        .execute(&pool)
        .await
        .map_err(unavailable)?;
        if let Err(error) = verify_store(&pool).await {
            pool.close().await;
            return Err(error);
        }
        Ok(Self { pool, path })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub async fn close(&self) {
        self.pool.close().await;
    }

    pub async fn prepare_operation(
        &self,
        operation_id: &str,
        kind: SecretLeaseOperationKindV1,
        lease_id: Option<&str>,
        semantic_sha256: [u8; 32],
        now_ms: u64,
    ) -> Result<SecretLeaseOperationAdmissionV1, SecretLeaseStoreError> {
        validate_operation_id(operation_id)?;
        if semantic_sha256 == [0; 32] {
            return Err(SecretLeaseStoreError::Invalid);
        }
        if let Some(lease_id) = lease_id {
            validate_provider_lease_id(lease_id)?;
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        if let Some(existing) = load_operation_tx(&mut transaction, operation_id).await? {
            if existing.kind != kind
                || existing.lease_id.as_deref() != lease_id
                || existing.semantic_sha256 != semantic_sha256
            {
                return Err(SecretLeaseStoreError::Conflict);
            }
            transaction.commit().await.map_err(unavailable)?;
            return Ok(match existing.state {
                SecretLeaseOperationStateV1::Prepared => {
                    SecretLeaseOperationAdmissionV1::AlreadyPrepared
                }
                SecretLeaseOperationStateV1::Dispatching => {
                    SecretLeaseOperationAdmissionV1::Dispatching
                }
                SecretLeaseOperationStateV1::Applied => {
                    SecretLeaseOperationAdmissionV1::AlreadyApplied
                }
                SecretLeaseOperationStateV1::NotApplied => {
                    SecretLeaseOperationAdmissionV1::NotApplied
                }
                SecretLeaseOperationStateV1::Indeterminate => {
                    SecretLeaseOperationAdmissionV1::Indeterminate
                }
            });
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM secret_lease_operations")
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
        if count >= MAX_OPERATION_ROWS {
            return Err(SecretLeaseStoreError::CapacityExceeded);
        }
        sqlx::query(
            "INSERT INTO secret_lease_operations (
                operation_id, kind, lease_id, semantic_sha256, state,
                observed_sha256, created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, 'prepared', NULL, ?, ?)",
        )
        .bind(operation_id)
        .bind(kind.as_str())
        .bind(lease_id)
        .bind(semantic_sha256.as_slice())
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(SecretLeaseOperationAdmissionV1::Prepared)
    }

    /// Durably crosses the local pre-dispatch line. Only a prepared operation
    /// may win. A restart that finds dispatching must reconcile and never
    /// blindly retry the provider operation.
    pub async fn claim_dispatch(
        &self,
        operation_id: &str,
        now_ms: u64,
    ) -> Result<bool, SecretLeaseStoreError> {
        validate_operation_id(operation_id)?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let updated = sqlx::query(
            "UPDATE secret_lease_operations
             SET state = 'dispatching', updated_at_ms = ?
             WHERE operation_id = ? AND state = 'prepared'",
        )
        .bind(to_i64(now_ms)?)
        .bind(operation_id)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() == 0
            && load_operation_tx(&mut transaction, operation_id)
                .await?
                .is_none()
        {
            return Err(SecretLeaseStoreError::NotFound);
        }
        transaction.commit().await.map_err(unavailable)?;
        Ok(updated.rows_affected() == 1)
    }

    pub async fn mark_not_applied(
        &self,
        operation_id: &str,
        observed_sha256: Option<[u8; 32]>,
        now_ms: u64,
    ) -> Result<(), SecretLeaseStoreError> {
        self.finish_operation(
            operation_id,
            SecretLeaseOperationStateV1::NotApplied,
            observed_sha256,
            now_ms,
        )
        .await
    }

    pub async fn mark_issue_indeterminate(
        &self,
        operation_id: &str,
        observed_sha256: Option<[u8; 32]>,
        now_ms: u64,
    ) -> Result<(), SecretLeaseStoreError> {
        self.finish_operation(
            operation_id,
            SecretLeaseOperationStateV1::Indeterminate,
            observed_sha256,
            now_ms,
        )
        .await
    }

    pub async fn mark_lease_indeterminate(
        &self,
        operation_id: &str,
        lease_id: &str,
        lease_state: SecretLeaseStateV1,
        observed_sha256: Option<[u8; 32]>,
        now_ms: u64,
    ) -> Result<(), SecretLeaseStoreError> {
        if !matches!(
            lease_state,
            SecretLeaseStateV1::RenewIndeterminate | SecretLeaseStateV1::RevokeIndeterminate
        ) {
            return Err(SecretLeaseStoreError::Invalid);
        }
        validate_operation_id(operation_id)?;
        validate_provider_lease_id(lease_id)?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let operation = load_operation_tx(&mut transaction, operation_id)
            .await?
            .ok_or(SecretLeaseStoreError::NotFound)?;
        if operation.lease_id.as_deref() != Some(lease_id)
            || !matches!(
                operation.state,
                SecretLeaseOperationStateV1::Dispatching
                    | SecretLeaseOperationStateV1::Indeterminate
            )
        {
            return Err(SecretLeaseStoreError::Conflict);
        }
        let lease = load_lease_tx(&mut transaction, lease_id)
            .await?
            .ok_or(SecretLeaseStoreError::NotFound)?;
        if matches!(
            lease.state,
            SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
        ) {
            return Err(SecretLeaseStoreError::Conflict);
        }
        sqlx::query(
            "UPDATE secret_leases
             SET state = ?, revision = revision + 1, updated_at_ms = ?
             WHERE lease_id = ?",
        )
        .bind(lease_state.as_str())
        .bind(to_i64(now_ms)?)
        .bind(lease_id)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        update_operation_state_tx(
            &mut transaction,
            operation_id,
            SecretLeaseOperationStateV1::Indeterminate,
            observed_sha256,
            now_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)
    }

    pub async fn commit_issue(
        &self,
        operation_id: &str,
        metadata: &SecretLeaseMetadataV1,
        observed_sha256: [u8; 32],
        now_ms: u64,
    ) -> Result<(), SecretLeaseStoreError> {
        validate_metadata(metadata)?;
        validate_operation_id(operation_id)?;
        if observed_sha256 == [0; 32] {
            return Err(SecretLeaseStoreError::Invalid);
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let operation = load_operation_tx(&mut transaction, operation_id)
            .await?
            .ok_or(SecretLeaseStoreError::NotFound)?;
        if operation.kind != SecretLeaseOperationKindV1::Issue
            || !matches!(
                operation.state,
                SecretLeaseOperationStateV1::Dispatching
                    | SecretLeaseOperationStateV1::Indeterminate
            )
        {
            return Err(SecretLeaseStoreError::Conflict);
        }
        let lease_count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM secret_leases")
            .fetch_one(&mut *transaction)
            .await
            .map_err(unavailable)?;
        if lease_count >= MAX_LEASE_ROWS
            && load_lease_tx(&mut transaction, &metadata.lease_id)
                .await?
                .is_none()
        {
            return Err(SecretLeaseStoreError::CapacityExceeded);
        }
        if let Some(existing) = load_lease_tx(&mut transaction, &metadata.lease_id).await? {
            if existing != *metadata {
                return Err(SecretLeaseStoreError::Conflict);
            }
        } else {
            insert_lease_tx(&mut transaction, metadata, now_ms).await?;
        }
        sqlx::query(
            "UPDATE secret_lease_operations
             SET lease_id = ?, state = 'applied', observed_sha256 = ?, updated_at_ms = ?
             WHERE operation_id = ?",
        )
        .bind(&metadata.lease_id)
        .bind(observed_sha256.as_slice())
        .bind(to_i64(now_ms)?)
        .bind(operation_id)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        transaction.commit().await.map_err(unavailable)
    }

    pub async fn commit_renew(
        &self,
        operation_id: &str,
        lease_id: &str,
        renewable: bool,
        expires_at_ms: u64,
        observed_sha256: [u8; 32],
        now_ms: u64,
    ) -> Result<SecretLeaseMetadataV1, SecretLeaseStoreError> {
        validate_operation_id(operation_id)?;
        validate_provider_lease_id(lease_id)?;
        if expires_at_ms <= now_ms || observed_sha256 == [0; 32] {
            return Err(SecretLeaseStoreError::Invalid);
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let operation = load_operation_tx(&mut transaction, operation_id)
            .await?
            .ok_or(SecretLeaseStoreError::NotFound)?;
        if operation.kind != SecretLeaseOperationKindV1::Renew
            || operation.lease_id.as_deref() != Some(lease_id)
            || !matches!(
                operation.state,
                SecretLeaseOperationStateV1::Dispatching
                    | SecretLeaseOperationStateV1::Indeterminate
            )
        {
            return Err(SecretLeaseStoreError::Conflict);
        }
        let lease = load_lease_tx(&mut transaction, lease_id)
            .await?
            .ok_or(SecretLeaseStoreError::NotFound)?;
        if matches!(
            lease.state,
            SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
        ) {
            return Err(SecretLeaseStoreError::Conflict);
        }
        sqlx::query(
            "UPDATE secret_leases
             SET renewable = ?, expires_at_ms = ?, state = 'active',
                 revision = revision + 1, updated_at_ms = ?
             WHERE lease_id = ?",
        )
        .bind(if renewable { 1_i64 } else { 0_i64 })
        .bind(to_i64(expires_at_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(lease_id)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        update_operation_state_tx(
            &mut transaction,
            operation_id,
            SecretLeaseOperationStateV1::Applied,
            Some(observed_sha256),
            now_ms,
        )
        .await?;
        let updated = load_lease_tx(&mut transaction, lease_id)
            .await?
            .ok_or(SecretLeaseStoreError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(updated)
    }

    pub async fn commit_revoke(
        &self,
        operation_id: &str,
        lease_id: &str,
        observed_sha256: [u8; 32],
        now_ms: u64,
    ) -> Result<SecretLeaseMetadataV1, SecretLeaseStoreError> {
        validate_operation_id(operation_id)?;
        validate_provider_lease_id(lease_id)?;
        if observed_sha256 == [0; 32] {
            return Err(SecretLeaseStoreError::Invalid);
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let operation = load_operation_tx(&mut transaction, operation_id)
            .await?
            .ok_or(SecretLeaseStoreError::NotFound)?;
        if operation.kind != SecretLeaseOperationKindV1::Revoke
            || operation.lease_id.as_deref() != Some(lease_id)
            || !matches!(
                operation.state,
                SecretLeaseOperationStateV1::Dispatching
                    | SecretLeaseOperationStateV1::Indeterminate
            )
        {
            return Err(SecretLeaseStoreError::Conflict);
        }
        if load_lease_tx(&mut transaction, lease_id).await?.is_none() {
            return Err(SecretLeaseStoreError::NotFound);
        }
        sqlx::query(
            "UPDATE secret_leases
             SET state = 'revoked', revision = revision + 1, updated_at_ms = ?
             WHERE lease_id = ?",
        )
        .bind(to_i64(now_ms)?)
        .bind(lease_id)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        update_operation_state_tx(
            &mut transaction,
            operation_id,
            SecretLeaseOperationStateV1::Applied,
            Some(observed_sha256),
            now_ms,
        )
        .await?;
        let updated = load_lease_tx(&mut transaction, lease_id)
            .await?
            .ok_or(SecretLeaseStoreError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(updated)
    }

    pub async fn reconcile_known_active(
        &self,
        operation_id: &str,
        lease_id: &str,
        renewable: bool,
        expires_at_ms: u64,
        observed_sha256: [u8; 32],
        now_ms: u64,
    ) -> Result<SecretLeaseMetadataV1, SecretLeaseStoreError> {
        if expires_at_ms <= now_ms || observed_sha256 == [0; 32] {
            return Err(SecretLeaseStoreError::Invalid);
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let operation = load_operation_tx(&mut transaction, operation_id)
            .await?
            .ok_or(SecretLeaseStoreError::NotFound)?;
        if operation.lease_id.as_deref() != Some(lease_id)
            || operation.state != SecretLeaseOperationStateV1::Indeterminate
            || !matches!(
                operation.kind,
                SecretLeaseOperationKindV1::Renew | SecretLeaseOperationKindV1::Revoke
            )
        {
            return Err(SecretLeaseStoreError::Conflict);
        }
        if load_lease_tx(&mut transaction, lease_id).await?.is_none() {
            return Err(SecretLeaseStoreError::NotFound);
        }
        sqlx::query(
            "UPDATE secret_leases
             SET renewable = ?, expires_at_ms = ?, state = 'active',
                 revision = revision + 1, updated_at_ms = ?
             WHERE lease_id = ?",
        )
        .bind(if renewable { 1_i64 } else { 0_i64 })
        .bind(to_i64(expires_at_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(lease_id)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let next_operation_state = match operation.kind {
            SecretLeaseOperationKindV1::Renew => SecretLeaseOperationStateV1::Applied,
            SecretLeaseOperationKindV1::Revoke => SecretLeaseOperationStateV1::NotApplied,
            SecretLeaseOperationKindV1::Issue => return Err(SecretLeaseStoreError::Conflict),
        };
        update_operation_state_tx(
            &mut transaction,
            operation_id,
            next_operation_state,
            Some(observed_sha256),
            now_ms,
        )
        .await?;
        let updated = load_lease_tx(&mut transaction, lease_id)
            .await?
            .ok_or(SecretLeaseStoreError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(updated)
    }

    pub async fn reconcile_known_absent(
        &self,
        operation_id: &str,
        lease_id: &str,
        observed_sha256: [u8; 32],
        now_ms: u64,
    ) -> Result<SecretLeaseMetadataV1, SecretLeaseStoreError> {
        if observed_sha256 == [0; 32] {
            return Err(SecretLeaseStoreError::Invalid);
        }
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let operation = load_operation_tx(&mut transaction, operation_id)
            .await?
            .ok_or(SecretLeaseStoreError::NotFound)?;
        if operation.lease_id.as_deref() != Some(lease_id)
            || operation.state != SecretLeaseOperationStateV1::Indeterminate
        {
            return Err(SecretLeaseStoreError::Conflict);
        }
        if load_lease_tx(&mut transaction, lease_id).await?.is_none() {
            return Err(SecretLeaseStoreError::NotFound);
        }
        sqlx::query(
            "UPDATE secret_leases
             SET state = 'revoked', revision = revision + 1, updated_at_ms = ?
             WHERE lease_id = ?",
        )
        .bind(to_i64(now_ms)?)
        .bind(lease_id)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let next_operation_state = if operation.kind == SecretLeaseOperationKindV1::Revoke {
            SecretLeaseOperationStateV1::Applied
        } else {
            SecretLeaseOperationStateV1::NotApplied
        };
        update_operation_state_tx(
            &mut transaction,
            operation_id,
            next_operation_state,
            Some(observed_sha256),
            now_ms,
        )
        .await?;
        let updated = load_lease_tx(&mut transaction, lease_id)
            .await?
            .ok_or(SecretLeaseStoreError::Corrupt)?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(updated)
    }

    /// OpenBao cannot generically look up an issuance timeout when no lease id
    /// reached the caller. Only an independently trusted provider/audit
    /// observation may close that ambiguity.
    pub async fn reconcile_issue_observation(
        &self,
        operation_id: &str,
        observation: SecretLeaseIssueObservationV1,
        observed_sha256: [u8; 32],
        now_ms: u64,
    ) -> Result<Option<SecretLeaseMetadataV1>, SecretLeaseStoreError> {
        match observation {
            SecretLeaseIssueObservationV1::Applied(metadata) => {
                self.commit_issue(operation_id, &metadata, observed_sha256, now_ms)
                    .await?;
                Ok(Some(metadata))
            }
            SecretLeaseIssueObservationV1::NotApplied => {
                self.mark_not_applied(operation_id, Some(observed_sha256), now_ms)
                    .await?;
                Ok(None)
            }
            SecretLeaseIssueObservationV1::Unknown => {
                self.mark_issue_indeterminate(operation_id, Some(observed_sha256), now_ms)
                    .await?;
                Ok(None)
            }
        }
    }

    pub async fn lease(
        &self,
        lease_id: &str,
    ) -> Result<Option<SecretLeaseMetadataV1>, SecretLeaseStoreError> {
        validate_provider_lease_id(lease_id)?;
        load_lease(&self.pool, lease_id).await
    }

    pub async fn operation(
        &self,
        operation_id: &str,
    ) -> Result<Option<SecretLeaseOperationV1>, SecretLeaseStoreError> {
        validate_operation_id(operation_id)?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let operation = load_operation_tx(&mut transaction, operation_id).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(operation)
    }

    pub async fn indeterminate_operations(
        &self,
        limit: u32,
    ) -> Result<Vec<SecretLeaseOperationV1>, SecretLeaseStoreError> {
        if !(1..=1_024).contains(&limit) {
            return Err(SecretLeaseStoreError::Invalid);
        }
        let rows = sqlx::query(
            "SELECT operation_id, kind, lease_id, semantic_sha256, state,
                    observed_sha256, created_at_ms, updated_at_ms
             FROM secret_lease_operations
             WHERE state IN ('dispatching', 'indeterminate')
             ORDER BY created_at_ms, operation_id LIMIT ?",
        )
        .bind(i64::from(limit))
        .fetch_all(&self.pool)
        .await
        .map_err(unavailable)?;
        rows.iter().map(operation_from_row).collect()
    }

    pub async fn expire_due(&self, now_ms: u64) -> Result<u64, SecretLeaseStoreError> {
        let result = sqlx::query(
            "UPDATE secret_leases
             SET state = 'expired', revision = revision + 1, updated_at_ms = ?
             WHERE state = 'active' AND expires_at_ms <= ?",
        )
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .execute(&self.pool)
        .await
        .map_err(unavailable)?;
        Ok(result.rows_affected())
    }

    async fn finish_operation(
        &self,
        operation_id: &str,
        state: SecretLeaseOperationStateV1,
        observed_sha256: Option<[u8; 32]>,
        now_ms: u64,
    ) -> Result<(), SecretLeaseStoreError> {
        validate_operation_id(operation_id)?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let current = load_operation_tx(&mut transaction, operation_id)
            .await?
            .ok_or(SecretLeaseStoreError::NotFound)?;
        if current.state == SecretLeaseOperationStateV1::Applied
            && state != SecretLeaseOperationStateV1::Applied
        {
            return Err(SecretLeaseStoreError::Conflict);
        }
        update_operation_state_tx(
            &mut transaction,
            operation_id,
            state,
            observed_sha256,
            now_ms,
        )
        .await?;
        transaction.commit().await.map_err(unavailable)
    }
}

async fn insert_lease_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    metadata: &SecretLeaseMetadataV1,
    now_ms: u64,
) -> Result<(), SecretLeaseStoreError> {
    sqlx::query(
        "INSERT INTO secret_leases (
            lease_id, schema_version, provider_mount, consumer_id,
            scope_sha256, request_sha256, fingerprint_key_id, secret_fingerprint,
            renewable, issued_at_ms, expires_at_ms, rotation_generation,
            state, revision, updated_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&metadata.lease_id)
    .bind(i64::from(metadata.schema_version))
    .bind(&metadata.provider_mount)
    .bind(&metadata.consumer_id)
    .bind(metadata.scope_sha256.as_slice())
    .bind(metadata.request_sha256.as_slice())
    .bind(&metadata.fingerprint_key_id)
    .bind(metadata.secret_fingerprint.as_slice())
    .bind(if metadata.renewable { 1_i64 } else { 0_i64 })
    .bind(to_i64(metadata.issued_at_ms)?)
    .bind(to_i64(metadata.expires_at_ms)?)
    .bind(to_i64(metadata.rotation_generation)?)
    .bind(metadata.state.as_str())
    .bind(to_i64(metadata.revision)?)
    .bind(to_i64(now_ms)?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

async fn load_lease(
    pool: &SqlitePool,
    lease_id: &str,
) -> Result<Option<SecretLeaseMetadataV1>, SecretLeaseStoreError> {
    let row = sqlx::query(LEASE_SELECT)
        .bind(lease_id)
        .fetch_optional(pool)
        .await
        .map_err(unavailable)?;
    row.as_ref().map(lease_from_row).transpose()
}

async fn load_lease_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
) -> Result<Option<SecretLeaseMetadataV1>, SecretLeaseStoreError> {
    let row = sqlx::query(LEASE_SELECT)
        .bind(lease_id)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(unavailable)?;
    row.as_ref().map(lease_from_row).transpose()
}

const LEASE_SELECT: &str = "SELECT lease_id, schema_version, provider_mount, consumer_id,
    scope_sha256, request_sha256, fingerprint_key_id, secret_fingerprint,
    renewable, issued_at_ms, expires_at_ms, rotation_generation, state, revision
    FROM secret_leases WHERE lease_id = ?";

fn lease_from_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<SecretLeaseMetadataV1, SecretLeaseStoreError> {
    let metadata = SecretLeaseMetadataV1 {
        schema_version: to_u32(row.try_get::<i64, _>("schema_version").map_err(unavailable)?)?,
        lease_id: row.try_get("lease_id").map_err(unavailable)?,
        provider_mount: row.try_get("provider_mount").map_err(unavailable)?,
        consumer_id: row.try_get("consumer_id").map_err(unavailable)?,
        scope_sha256: digest_column(row, "scope_sha256")?,
        request_sha256: digest_column(row, "request_sha256")?,
        fingerprint_key_id: row.try_get("fingerprint_key_id").map_err(unavailable)?,
        secret_fingerprint: digest_column(row, "secret_fingerprint")?,
        renewable: row.try_get::<i64, _>("renewable").map_err(unavailable)? == 1,
        issued_at_ms: to_u64(row.try_get("issued_at_ms").map_err(unavailable)?)?,
        expires_at_ms: to_u64(row.try_get("expires_at_ms").map_err(unavailable)?)?,
        rotation_generation: to_u64(
            row.try_get("rotation_generation").map_err(unavailable)?,
        )?,
        state: SecretLeaseStateV1::parse(
            &row.try_get::<String, _>("state").map_err(unavailable)?,
        )?,
        revision: to_u64(row.try_get("revision").map_err(unavailable)?)?,
    };
    validate_metadata(&metadata).map(|()| metadata)
}

async fn load_operation_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
) -> Result<Option<SecretLeaseOperationV1>, SecretLeaseStoreError> {
    let row = sqlx::query(
        "SELECT operation_id, kind, lease_id, semantic_sha256, state,
                observed_sha256, created_at_ms, updated_at_ms
         FROM secret_lease_operations WHERE operation_id = ?",
    )
    .bind(operation_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?;
    row.as_ref().map(operation_from_row).transpose()
}

fn operation_from_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<SecretLeaseOperationV1, SecretLeaseStoreError> {
    let observed: Option<Vec<u8>> = row.try_get("observed_sha256").map_err(unavailable)?;
    Ok(SecretLeaseOperationV1 {
        operation_id: row.try_get("operation_id").map_err(unavailable)?,
        kind: SecretLeaseOperationKindV1::parse(
            &row.try_get::<String, _>("kind").map_err(unavailable)?,
        )?,
        lease_id: row.try_get("lease_id").map_err(unavailable)?,
        semantic_sha256: digest_column(row, "semantic_sha256")?,
        state: SecretLeaseOperationStateV1::parse(
            &row.try_get::<String, _>("state").map_err(unavailable)?,
        )?,
        observed_sha256: observed.map(digest_vec).transpose()?,
        created_at_ms: to_u64(row.try_get("created_at_ms").map_err(unavailable)?)?,
        updated_at_ms: to_u64(row.try_get("updated_at_ms").map_err(unavailable)?)?,
    })
}

async fn update_operation_state_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    operation_id: &str,
    state: SecretLeaseOperationStateV1,
    observed_sha256: Option<[u8; 32]>,
    now_ms: u64,
) -> Result<(), SecretLeaseStoreError> {
    let result = sqlx::query(
        "UPDATE secret_lease_operations
         SET state = ?, observed_sha256 = COALESCE(?, observed_sha256), updated_at_ms = ?
         WHERE operation_id = ?",
    )
    .bind(state.as_str())
    .bind(observed_sha256.map(|value| value.to_vec()))
    .bind(to_i64(now_ms)?)
    .bind(operation_id)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    if result.rows_affected() != 1 {
        return Err(SecretLeaseStoreError::NotFound);
    }
    Ok(())
}

async fn verify_store(pool: &SqlitePool) -> Result<(), SecretLeaseStoreError> {
    let quick: String = sqlx::query_scalar("PRAGMA quick_check")
        .fetch_one(pool)
        .await
        .map_err(unavailable)?;
    if quick != "ok" {
        return Err(SecretLeaseStoreError::Corrupt);
    }
    let version: i64 =
        sqlx::query_scalar("SELECT schema_version FROM secret_lease_meta WHERE singleton = 1")
            .fetch_one(pool)
            .await
            .map_err(unavailable)?;
    if version != i64::from(SECRET_LEASE_SCHEMA_VERSION_V1) {
        return Err(SecretLeaseStoreError::Corrupt);
    }
    Ok(())
}

fn validate_metadata(metadata: &SecretLeaseMetadataV1) -> Result<(), SecretLeaseStoreError> {
    if metadata.schema_version != SECRET_LEASE_SCHEMA_VERSION_V1
        || !component(&metadata.provider_mount)
        || !component(&metadata.consumer_id)
        || !component(&metadata.fingerprint_key_id)
        || metadata.scope_sha256 == [0; 32]
        || metadata.request_sha256 == [0; 32]
        || metadata.secret_fingerprint == [0; 32]
        || metadata.issued_at_ms >= metadata.expires_at_ms
        || metadata.rotation_generation == 0
        || metadata.revision == 0
    {
        return Err(SecretLeaseStoreError::Invalid);
    }
    validate_provider_lease_id(&metadata.lease_id)
}

pub(crate) fn validate_operation_id(value: &str) -> Result<(), SecretLeaseStoreError> {
    if component(value) {
        Ok(())
    } else {
        Err(SecretLeaseStoreError::Invalid)
    }
}

pub(crate) fn validate_provider_lease_id(value: &str) -> Result<(), SecretLeaseStoreError> {
    if value.is_empty()
        || value.len() > 2_048
        || value
            .bytes()
            .any(|byte| byte == 0 || byte.is_ascii_control())
    {
        Err(SecretLeaseStoreError::Invalid)
    } else {
        Ok(())
    }
}

fn component(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "."
        && value != ".."
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:".contains(&byte))
}

fn digest_column(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<[u8; 32], SecretLeaseStoreError> {
    digest_vec(row.try_get::<Vec<u8>, _>(column).map_err(unavailable)?)
}

fn digest_vec(value: Vec<u8>) -> Result<[u8; 32], SecretLeaseStoreError> {
    value
        .try_into()
        .map_err(|_| SecretLeaseStoreError::Corrupt)
}

fn to_i64(value: u64) -> Result<i64, SecretLeaseStoreError> {
    i64::try_from(value).map_err(|_| SecretLeaseStoreError::Invalid)
}

fn to_u64(value: i64) -> Result<u64, SecretLeaseStoreError> {
    u64::try_from(value).map_err(|_| SecretLeaseStoreError::Corrupt)
}

fn to_u32(value: i64) -> Result<u32, SecretLeaseStoreError> {
    u32::try_from(value).map_err(|_| SecretLeaseStoreError::Corrupt)
}

pub(crate) fn now_millis() -> Result<u64, SecretLeaseStoreError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(unavailable)?
        .as_millis();
    u64::try_from(millis).map_err(|_| SecretLeaseStoreError::Unavailable)
}

fn unavailable(_error: impl fmt::Display) -> SecretLeaseStoreError {
    SecretLeaseStoreError::Unavailable
}

fn create_private_directory(path: &Path) -> Result<(), SecretLeaseStoreError> {
    fs::create_dir_all(path).map_err(unavailable)?;
    if path.canonicalize().map_err(unavailable)? != path {
        return Err(SecretLeaseStoreError::Invalid);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700)).map_err(unavailable)?;
    }
    Ok(())
}

fn protect_database_file(path: &Path) -> Result<(), SecretLeaseStoreError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o600)).map_err(unavailable)?;
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SecretLeaseStoreError {
    Invalid,
    Conflict,
    NotFound,
    CapacityExceeded,
    Unavailable,
    Corrupt,
}

impl fmt::Display for SecretLeaseStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for SecretLeaseStoreError {}

#[cfg(test)]
#[path = "lease_store_tests.rs"]
mod tests;
