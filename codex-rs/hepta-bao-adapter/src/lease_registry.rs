//! Durable metadata-only SecretLease lifecycle registry.
//!
//! Secret values never enter this store. Provider effects are represented as
//! explicit operations so timeout/crash ambiguity is durable and cannot be
//! converted into a blind retry.

use std::fmt;
use std::path::Path;
use std::time::Duration;

use sqlx::Row;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;

const SCHEMA_VERSION: i64 = 1;
const MAX_ID_BYTES: usize = 512;
const MAX_PROVIDER_PATH_BYTES: usize = 2048;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LeaseState {
    Issuing,
    Active,
    Renewing,
    RevokePending,
    Revoked,
    Expired,
    Unknown,
}

impl LeaseState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Issuing => "issuing",
            Self::Active => "active",
            Self::Renewing => "renewing",
            Self::RevokePending => "revoke_pending",
            Self::Revoked => "revoked",
            Self::Expired => "expired",
            Self::Unknown => "unknown",
        }
    }

    fn parse(value: &str) -> Result<Self, LeaseRegistryError> {
        match value {
            "issuing" => Ok(Self::Issuing),
            "active" => Ok(Self::Active),
            "renewing" => Ok(Self::Renewing),
            "revoke_pending" => Ok(Self::RevokePending),
            "revoked" => Ok(Self::Revoked),
            "expired" => Ok(Self::Expired),
            "unknown" => Ok(Self::Unknown),
            _ => Err(LeaseRegistryError::CorruptState),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LeaseOperationKind {
    Issue,
    Renew,
    Revoke,
}

impl LeaseOperationKind {
    fn as_str(self) -> &'static str {
        match self {
            Self::Issue => "issue",
            Self::Renew => "renew",
            Self::Revoke => "revoke",
        }
    }

    fn parse(value: &str) -> Result<Self, LeaseRegistryError> {
        match value {
            "issue" => Ok(Self::Issue),
            "renew" => Ok(Self::Renew),
            "revoke" => Ok(Self::Revoke),
            _ => Err(LeaseRegistryError::CorruptState),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LeaseOperationState {
    Prepared,
    InFlight,
    Applied,
    Rejected,
    Unknown,
}

impl LeaseOperationState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Prepared => "prepared",
            Self::InFlight => "in_flight",
            Self::Applied => "applied",
            Self::Rejected => "rejected",
            Self::Unknown => "unknown",
        }
    }

    fn parse(value: &str) -> Result<Self, LeaseRegistryError> {
        match value {
            "prepared" => Ok(Self::Prepared),
            "in_flight" => Ok(Self::InFlight),
            "applied" => Ok(Self::Applied),
            "rejected" => Ok(Self::Rejected),
            "unknown" => Ok(Self::Unknown),
            _ => Err(LeaseRegistryError::CorruptState),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LeaseMetadata {
    pub lease_id: String,
    pub provider_path: String,
    pub consumer_id: String,
    pub scope_sha256: [u8; 32],
    pub renewable: bool,
    pub expires_at_ms: u64,
    pub state: LeaseState,
    pub revision: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LeaseOperationRecord {
    pub operation_id: String,
    pub kind: LeaseOperationKind,
    pub lease_id: Option<String>,
    pub semantic_sha256: [u8; 32],
    pub state: LeaseOperationState,
    pub observed_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperationAdmission {
    New,
    Existing(LeaseOperationRecord),
}

#[derive(Clone)]
pub struct LeaseRegistry {
    pool: SqlitePool,
}

impl fmt::Debug for LeaseRegistry {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("LeaseRegistry([DURABLE METADATA ONLY])")
    }
}

impl LeaseRegistry {
    pub async fn open(path: &Path) -> Result<Self, LeaseRegistryError> {
        let options = SqliteConnectOptions::new()
        .filename(path)
        .create_if_missing(true)
        .journal_mode(SqliteJournalMode::Wal)
        .synchronous(SqliteSynchronous::Full)
        .foreign_keys(true)
        .busy_timeout(Duration::from_secs(5));
        let pool = SqlitePoolOptions::new()
            .max_connections(4)
            .acquire_timeout(Duration::from_secs(5))
            .connect_with(options)
            .await
            .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        let registry = Self { pool };
        registry.initialize().await?;
        Ok(registry)
    }

    async fn initialize(&self) -> Result<(), LeaseRegistryError> {
        sqlx::query(
            r#"
            CREATE TABLE IF NOT EXISTS heptabao_meta(
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            );
            "#,
        )
        .execute(&self.pool)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        sqlx::query(
            r#"
            INSERT INTO heptabao_meta(key,value) VALUES('schema_version',?)
            ON CONFLICT(key) DO NOTHING
            "#,
        )
        .bind(SCHEMA_VERSION)
        .execute(&self.pool)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        let version: i64 = sqlx::query_scalar(
            "SELECT value FROM heptabao_meta WHERE key='schema_version'",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        if version != SCHEMA_VERSION {
            return Err(LeaseRegistryError::UnsupportedSchema);
        }
        sqlx::query(
            r#"
            CREATE TABLE IF NOT EXISTS secret_leases(
                lease_id TEXT PRIMARY KEY,
                provider_path TEXT NOT NULL,
                consumer_id TEXT NOT NULL,
                scope_sha256 BLOB NOT NULL CHECK(length(scope_sha256)=32),
                renewable INTEGER NOT NULL CHECK(renewable IN (0,1)),
                expires_at_ms INTEGER NOT NULL,
                state TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision >= 1),
                updated_at_ms INTEGER NOT NULL
            )
            "#,
        )
        .execute(&self.pool)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        sqlx::query(
            r#"
            CREATE TABLE IF NOT EXISTS lease_operations(
                operation_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                lease_id TEXT,
                semantic_sha256 BLOB NOT NULL CHECK(length(semantic_sha256)=32),
                state TEXT NOT NULL,
                observed_at_ms INTEGER NOT NULL
            )
            "#,
        )
        .execute(&self.pool)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        sqlx::query(
            "CREATE INDEX IF NOT EXISTS idx_lease_operations_lease ON lease_operations(lease_id, observed_at_ms)",
        )
        .execute(&self.pool)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        Ok(())
    }

    pub async fn begin_operation(
        &self,
        operation_id: &str,
        kind: LeaseOperationKind,
        lease_id: Option<&str>,
        semantic_sha256: [u8; 32],
        now_ms: u64,
    ) -> Result<OperationAdmission, LeaseRegistryError> {
        validate_id(operation_id)?;
        if let Some(value) = lease_id {
            validate_id(value)?;
        }
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        if let Some(row) = sqlx::query(
            "SELECT kind,lease_id,semantic_sha256,state,observed_at_ms FROM lease_operations WHERE operation_id=?",
        )
        .bind(operation_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?
        {
            let existing = decode_operation(operation_id, &row)?;
            if existing.kind != kind
                || existing.lease_id.as_deref() != lease_id
                || existing.semantic_sha256 != semantic_sha256
            {
                return Err(LeaseRegistryError::OperationConflict);
            }
            tx.commit()
                .await
                .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
            return Ok(OperationAdmission::Existing(existing));
        }
        sqlx::query(
            "INSERT INTO lease_operations(operation_id,kind,lease_id,semantic_sha256,state,observed_at_ms) VALUES(?,?,?,?,?,?)",
        )
        .bind(operation_id)
        .bind(kind.as_str())
        .bind(lease_id)
        .bind(semantic_sha256.as_slice())
        .bind(LeaseOperationState::Prepared.as_str())
        .bind(to_i64(now_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        tx.commit()
            .await
            .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        Ok(OperationAdmission::New)
    }

    pub async fn mark_in_flight(
        &self,
        operation_id: &str,
        now_ms: u64,
    ) -> Result<(), LeaseRegistryError> {
        self.transition_operation(
            operation_id,
            &[LeaseOperationState::Prepared],
            LeaseOperationState::InFlight,
            now_ms,
        )
        .await
    }

    pub async fn commit_issue(
        &self,
        operation_id: &str,
        lease: &LeaseMetadata,
        now_ms: u64,
    ) -> Result<(), LeaseRegistryError> {
        validate_metadata(lease)?;
        let mut tx = self.pool.begin().await.map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        ensure_operation_state(
            &mut tx,
            operation_id,
            LeaseOperationKind::Issue,
            &[LeaseOperationState::InFlight, LeaseOperationState::Unknown],
        )
        .await?;
        sqlx::query(
            r#"
            INSERT INTO secret_leases(
                lease_id,provider_path,consumer_id,scope_sha256,renewable,
                expires_at_ms,state,revision,updated_at_ms
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(lease_id) DO UPDATE SET
                provider_path=excluded.provider_path,
                consumer_id=excluded.consumer_id,
                scope_sha256=excluded.scope_sha256,
                renewable=excluded.renewable,
                expires_at_ms=excluded.expires_at_ms,
                state=excluded.state,
                revision=secret_leases.revision+1,
                updated_at_ms=excluded.updated_at_ms
            "#,
        )
        .bind(&lease.lease_id)
        .bind(&lease.provider_path)
        .bind(&lease.consumer_id)
        .bind(lease.scope_sha256.as_slice())
        .bind(if lease.renewable { 1_i64 } else { 0_i64 })
        .bind(to_i64(lease.expires_at_ms)?)
        .bind(LeaseState::Active.as_str())
        .bind(to_i64(lease.revision.max(1))?)
        .bind(to_i64(now_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        sqlx::query(
            "UPDATE lease_operations SET lease_id=?,state=?,observed_at_ms=? WHERE operation_id=?",
        )
        .bind(&lease.lease_id)
        .bind(LeaseOperationState::Applied.as_str())
        .bind(to_i64(now_ms)?)
        .bind(operation_id)
        .execute(&mut *tx)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        tx.commit().await.map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        Ok(())
    }

    pub async fn begin_lease_transition(
        &self,
        operation_id: &str,
        kind: LeaseOperationKind,
        lease_id: &str,
        semantic_sha256: [u8; 32],
        now_ms: u64,
    ) -> Result<OperationAdmission, LeaseRegistryError> {
        if !matches!(kind, LeaseOperationKind::Renew | LeaseOperationKind::Revoke) {
            return Err(LeaseRegistryError::InvalidInput);
        }
        validate_id(operation_id)?;
        validate_id(lease_id)?;
        let mut tx = self.pool.begin().await.map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        if let Some(row) = sqlx::query(
            "SELECT kind,lease_id,semantic_sha256,state,observed_at_ms FROM lease_operations WHERE operation_id=?",
        )
        .bind(operation_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?
        {
            let existing = decode_operation(operation_id, &row)?;
            if existing.kind != kind
                || existing.lease_id.as_deref() != Some(lease_id)
                || existing.semantic_sha256 != semantic_sha256
            {
                return Err(LeaseRegistryError::OperationConflict);
            }
            tx.commit().await.map_err(|_| LeaseRegistryError::StoreUnavailable)?;
            return Ok(OperationAdmission::Existing(existing));
        }

        let target = if kind == LeaseOperationKind::Renew {
            LeaseState::Renewing
        } else {
            LeaseState::RevokePending
        };
        let result = sqlx::query(
            "UPDATE secret_leases SET state=?,revision=revision+1,updated_at_ms=? WHERE lease_id=? AND state='active'",
        )
        .bind(target.as_str())
        .bind(to_i64(now_ms)?)
        .bind(lease_id)
        .execute(&mut *tx)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        if result.rows_affected() != 1 {
            return Err(LeaseRegistryError::InvalidLeaseState);
        }
        sqlx::query(
            "INSERT INTO lease_operations(operation_id,kind,lease_id,semantic_sha256,state,observed_at_ms) VALUES(?,?,?,?,?,?)",
        )
        .bind(operation_id)
        .bind(kind.as_str())
        .bind(lease_id)
        .bind(semantic_sha256.as_slice())
        .bind(LeaseOperationState::Prepared.as_str())
        .bind(to_i64(now_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        tx.commit().await.map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        Ok(OperationAdmission::New)
    }

    pub async fn commit_renew(
        &self,
        operation_id: &str,
        lease_id: &str,
        expires_at_ms: u64,
        renewable: bool,
        now_ms: u64,
    ) -> Result<(), LeaseRegistryError> {
        let mut tx = self.pool.begin().await.map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        ensure_operation_state(
            &mut tx,
            operation_id,
            LeaseOperationKind::Renew,
            &[LeaseOperationState::InFlight, LeaseOperationState::Unknown],
        )
        .await?;
        let result = sqlx::query(
            "UPDATE secret_leases SET renewable=?,expires_at_ms=?,state='active',revision=revision+1,updated_at_ms=? WHERE lease_id=?",
        )
        .bind(if renewable { 1_i64 } else { 0_i64 })
        .bind(to_i64(expires_at_ms)?)
        .bind(to_i64(now_ms)?)
        .bind(lease_id)
        .execute(&mut *tx)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        if result.rows_affected() != 1 {
            return Err(LeaseRegistryError::LeaseNotFound);
        }
        mark_operation_applied(&mut tx, operation_id, now_ms).await?;
        tx.commit().await.map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        Ok(())
    }

    pub async fn commit_revoke(
        &self,
        operation_id: &str,
        lease_id: &str,
        now_ms: u64,
    ) -> Result<(), LeaseRegistryError> {
        let mut tx = self.pool.begin().await.map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        ensure_operation_state(
            &mut tx,
            operation_id,
            LeaseOperationKind::Revoke,
            &[LeaseOperationState::InFlight, LeaseOperationState::Unknown],
        )
        .await?;
        let result = sqlx::query(
            "UPDATE secret_leases SET state='revoked',renewable=0,revision=revision+1,updated_at_ms=? WHERE lease_id=?",
        )
        .bind(to_i64(now_ms)?)
        .bind(lease_id)
        .execute(&mut *tx)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        if result.rows_affected() != 1 {
            return Err(LeaseRegistryError::LeaseNotFound);
        }
        mark_operation_applied(&mut tx, operation_id, now_ms).await?;
        tx.commit().await.map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        Ok(())
    }

    pub async fn mark_unknown(
        &self,
        operation_id: &str,
        now_ms: u64,
    ) -> Result<(), LeaseRegistryError> {
        let row = sqlx::query("SELECT lease_id FROM lease_operations WHERE operation_id=?")
            .bind(operation_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|_| LeaseRegistryError::StoreUnavailable)?
            .ok_or(LeaseRegistryError::OperationNotFound)?;
        let lease_id: Option<String> = row.try_get("lease_id").map_err(|_| LeaseRegistryError::CorruptState)?;
        self.transition_operation(
            operation_id,
            &[LeaseOperationState::InFlight],
            LeaseOperationState::Unknown,
            now_ms,
        )
        .await?;
        if let Some(lease_id) = lease_id {
            sqlx::query(
                "UPDATE secret_leases SET state='unknown',revision=revision+1,updated_at_ms=? WHERE lease_id=?",
            )
            .bind(to_i64(now_ms)?)
            .bind(lease_id)
            .execute(&self.pool)
            .await
            .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        }
        Ok(())
    }

    pub async fn reject_operation(
        &self,
        operation_id: &str,
        now_ms: u64,
    ) -> Result<(), LeaseRegistryError> {
        validate_id(operation_id)?;
        let mut tx = self.pool.begin().await.map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        let row = sqlx::query(
            "SELECT kind,lease_id,state FROM lease_operations WHERE operation_id=?",
        )
        .bind(operation_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?
        .ok_or(LeaseRegistryError::OperationNotFound)?;
        let kind = LeaseOperationKind::parse(
            row.try_get::<String, _>("kind").map_err(|_| LeaseRegistryError::CorruptState)?.as_str(),
        )?;
        let state = LeaseOperationState::parse(
            row.try_get::<String, _>("state").map_err(|_| LeaseRegistryError::CorruptState)?.as_str(),
        )?;
        if !matches!(state, LeaseOperationState::Prepared | LeaseOperationState::InFlight) {
            return Err(LeaseRegistryError::InvalidOperationState);
        }
        let lease_id: Option<String> = row.try_get("lease_id").map_err(|_| LeaseRegistryError::CorruptState)?;
        sqlx::query("UPDATE lease_operations SET state='rejected',observed_at_ms=? WHERE operation_id=?")
            .bind(to_i64(now_ms)?)
            .bind(operation_id)
            .execute(&mut *tx)
            .await
            .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        if let Some(lease_id) = lease_id {
            let transitional = match kind {
                LeaseOperationKind::Renew => Some(LeaseState::Renewing),
                LeaseOperationKind::Revoke => Some(LeaseState::RevokePending),
                LeaseOperationKind::Issue => None,
            };
            if let Some(transitional) = transitional {
                sqlx::query(
                    "UPDATE secret_leases SET state='active',revision=revision+1,updated_at_ms=? WHERE lease_id=? AND state=?",
                )
                .bind(to_i64(now_ms)?)
                .bind(lease_id)
                .bind(transitional.as_str())
                .execute(&mut *tx)
                .await
                .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
            }
        }
        tx.commit().await.map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        Ok(())
    }

    pub async fn get_operation(
        &self,
        operation_id: &str,
    ) -> Result<Option<LeaseOperationRecord>, LeaseRegistryError> {
        validate_id(operation_id)?;
        let Some(row) = sqlx::query(
            "SELECT kind,lease_id,semantic_sha256,state,observed_at_ms FROM lease_operations WHERE operation_id=?",
        )
        .bind(operation_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?
        else {
            return Ok(None);
        };
        Ok(Some(decode_operation(operation_id, &row)?))
    }

    pub async fn get_lease(
        &self,
        lease_id: &str,
        now_ms: u64,
    ) -> Result<Option<LeaseMetadata>, LeaseRegistryError> {
        validate_id(lease_id)?;
        let Some(row) = sqlx::query(
            "SELECT provider_path,consumer_id,scope_sha256,renewable,expires_at_ms,state,revision FROM secret_leases WHERE lease_id=?",
        )
        .bind(lease_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?
        else {
            return Ok(None);
        };
        let mut metadata = decode_lease(lease_id, &row)?;
        if matches!(metadata.state, LeaseState::Active) && now_ms >= metadata.expires_at_ms {
            sqlx::query(
                "UPDATE secret_leases SET state='expired',revision=revision+1,updated_at_ms=? WHERE lease_id=? AND state='active'",
            )
            .bind(to_i64(now_ms)?)
            .bind(lease_id)
            .execute(&self.pool)
            .await
            .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
            metadata.state = LeaseState::Expired;
            metadata.revision = metadata.revision.saturating_add(1);
        }
        Ok(Some(metadata))
    }

    async fn transition_operation(
        &self,
        operation_id: &str,
        allowed: &[LeaseOperationState],
        next: LeaseOperationState,
        now_ms: u64,
    ) -> Result<(), LeaseRegistryError> {
        validate_id(operation_id)?;
        let current: Option<String> =
            sqlx::query_scalar("SELECT state FROM lease_operations WHERE operation_id=?")
                .bind(operation_id)
                .fetch_optional(&self.pool)
                .await
                .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        let current = current.ok_or(LeaseRegistryError::OperationNotFound)?;
        let current = LeaseOperationState::parse(&current)?;
        if !allowed.contains(&current) {
            return Err(LeaseRegistryError::InvalidOperationState);
        }
        sqlx::query(
            "UPDATE lease_operations SET state=?,observed_at_ms=? WHERE operation_id=?",
        )
        .bind(next.as_str())
        .bind(to_i64(now_ms)?)
        .bind(operation_id)
        .execute(&self.pool)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
        Ok(())
    }
}

async fn ensure_operation_state(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    operation_id: &str,
    kind: LeaseOperationKind,
    allowed: &[LeaseOperationState],
) -> Result<(), LeaseRegistryError> {
    let row = sqlx::query("SELECT kind,state FROM lease_operations WHERE operation_id=?")
        .bind(operation_id)
        .fetch_optional(&mut **tx)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?
        .ok_or(LeaseRegistryError::OperationNotFound)?;
    let actual_kind = LeaseOperationKind::parse(
        row.try_get::<String, _>("kind")
            .map_err(|_| LeaseRegistryError::CorruptState)?
            .as_str(),
    )?;
    let state = LeaseOperationState::parse(
        row.try_get::<String, _>("state")
            .map_err(|_| LeaseRegistryError::CorruptState)?
            .as_str(),
    )?;
    if actual_kind != kind || !allowed.contains(&state) {
        return Err(LeaseRegistryError::InvalidOperationState);
    }
    Ok(())
}

async fn mark_operation_applied(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    operation_id: &str,
    now_ms: u64,
) -> Result<(), LeaseRegistryError> {
    sqlx::query("UPDATE lease_operations SET state='applied',observed_at_ms=? WHERE operation_id=?")
        .bind(to_i64(now_ms)?)
        .bind(operation_id)
        .execute(&mut **tx)
        .await
        .map_err(|_| LeaseRegistryError::StoreUnavailable)?;
    Ok(())
}

fn decode_operation(
    operation_id: &str,
    row: &sqlx::sqlite::SqliteRow,
) -> Result<LeaseOperationRecord, LeaseRegistryError> {
    let digest: Vec<u8> = row.try_get("semantic_sha256").map_err(|_| LeaseRegistryError::CorruptState)?;
    Ok(LeaseOperationRecord {
        operation_id: operation_id.to_owned(),
        kind: LeaseOperationKind::parse(
            row.try_get::<String, _>("kind").map_err(|_| LeaseRegistryError::CorruptState)?.as_str(),
        )?,
        lease_id: row.try_get("lease_id").map_err(|_| LeaseRegistryError::CorruptState)?,
        semantic_sha256: to_digest(&digest)?,
        state: LeaseOperationState::parse(
            row.try_get::<String, _>("state").map_err(|_| LeaseRegistryError::CorruptState)?.as_str(),
        )?,
        observed_at_ms: to_u64(
            row.try_get::<i64, _>("observed_at_ms").map_err(|_| LeaseRegistryError::CorruptState)?,
        )?,
    })
}

fn decode_lease(
    lease_id: &str,
    row: &sqlx::sqlite::SqliteRow,
) -> Result<LeaseMetadata, LeaseRegistryError> {
    let digest: Vec<u8> = row.try_get("scope_sha256").map_err(|_| LeaseRegistryError::CorruptState)?;
    Ok(LeaseMetadata {
        lease_id: lease_id.to_owned(),
        provider_path: row.try_get("provider_path").map_err(|_| LeaseRegistryError::CorruptState)?,
        consumer_id: row.try_get("consumer_id").map_err(|_| LeaseRegistryError::CorruptState)?,
        scope_sha256: to_digest(&digest)?,
        renewable: row.try_get::<i64, _>("renewable").map_err(|_| LeaseRegistryError::CorruptState)? == 1,
        expires_at_ms: to_u64(
            row.try_get::<i64, _>("expires_at_ms").map_err(|_| LeaseRegistryError::CorruptState)?,
        )?,
        state: LeaseState::parse(
            row.try_get::<String, _>("state").map_err(|_| LeaseRegistryError::CorruptState)?.as_str(),
        )?,
        revision: to_u64(
            row.try_get::<i64, _>("revision").map_err(|_| LeaseRegistryError::CorruptState)?,
        )?,
    })
}

fn validate_metadata(value: &LeaseMetadata) -> Result<(), LeaseRegistryError> {
    validate_id(&value.lease_id)?;
    validate_id(&value.consumer_id)?;
    if value.provider_path.is_empty()
        || value.provider_path.len() > MAX_PROVIDER_PATH_BYTES
        || value.scope_sha256 == [0; 32]
        || value.expires_at_ms == 0
    {
        return Err(LeaseRegistryError::InvalidInput);
    }
    Ok(())
}

fn validate_id(value: &str) -> Result<(), LeaseRegistryError> {
    if value.is_empty() || value.len() > MAX_ID_BYTES || value.bytes().any(|byte| byte == 0) {
        return Err(LeaseRegistryError::InvalidInput);
    }
    Ok(())
}

fn to_i64(value: u64) -> Result<i64, LeaseRegistryError> {
    i64::try_from(value).map_err(|_| LeaseRegistryError::InvalidInput)
}

fn to_u64(value: i64) -> Result<u64, LeaseRegistryError> {
    u64::try_from(value).map_err(|_| LeaseRegistryError::CorruptState)
}

fn to_digest(value: &[u8]) -> Result<[u8; 32], LeaseRegistryError> {
    value.try_into().map_err(|_| LeaseRegistryError::CorruptState)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LeaseRegistryError {
    InvalidInput,
    UnsupportedSchema,
    StoreUnavailable,
    CorruptState,
    OperationConflict,
    OperationNotFound,
    InvalidOperationState,
    LeaseNotFound,
    InvalidLeaseState,
}

impl fmt::Display for LeaseRegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for LeaseRegistryError {}

#[cfg(test)]
#[path = "lease_registry_tests.rs"]
mod tests;
