//! Exact current-cut witness construction and fail-closed recovery admission.
//!
//! This is not a minimum-prefix journal anchor. Any subsequent owner mutation
//! needs a fresh, independently retained host witness. Capturing a witness from
//! a suspect backup cannot authenticate that backup. No witness is auto-saved,
//! no grant is issued, and no migration, repair or unanchored fallback occurs.
//! The pilot permits 65,536 logical rows, 64 MiB of framed values, 2 MiB per
//! row and 1 MiB of required schema definitions. Integrity checking still scans physical
//! database pages; these logical limits are not a host latency qualification.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaAgentLayout;
use codex_state::SqliteConfig;
use codex_state::SqliteRecoveryError;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::SqliteConnection;
use sqlx::TypeInfo;
use sqlx::ValueRef;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use super::COGNITIVE_DB_FILENAME;
use super::CognitiveStore;
use super::CognitiveStoreError;
use super::REQUIRED_SCHEMA_OBJECTS;
use super::REQUIRED_SCHEMA_ORACLE_SHA256;
use super::unavailable;
use crate::framing::frame_part;

#[path = "cognitive_store_recovery_read_only.rs"]
mod read_only;
pub use read_only::RecoveredCognitiveReadOnly;

const PROFILE: &str = "hepta:cognitive:exact-current-cut:v1";
const MAX_ROWS: i64 = 65_536;
const MAX_BYTES: i64 = 64 * 1024 * 1024;
const MAX_ROW_BYTES: i64 = 2 * 1024 * 1024;
const MAX_SCHEMA_BYTES: i64 = 1024 * 1024;

/// An exact logical state cut, including all registered owner tables and their
/// current tombstones/revocations. The host must independently persist and
/// authenticate this value and establish that it is CURRENT before recovery.
/// The digest is an integrity comparison, not a signature or write authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveRecoveryAnchor {
    pub profile: String,
    pub owner_agent_id: AgentId,
    pub schema_digest: Sha256Digest,
    pub state_digest: Sha256Digest,
}

const WRITER_FENCE_PROFILE: &str = "hepta:cognitive:writer-fence:v1";

/// Exact active writer head retained by the trusted host beside the current-cut
/// anchor. The lease-chain digest binds the fencing token without exposing it.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveRecoveryWriterFence {
    pub profile: String,
    pub owner_agent_id: AgentId,
    pub lease_id: String,
    pub lease_sequence: u64,
    pub generation: u64,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub lease_expires_at_unix_seconds: u64,
    pub lease_sha256: Sha256Digest,
}

impl CognitiveRecoveryWriterFence {
    fn validate(&self, owner: &AgentId) -> Result<(), CognitiveRecoveryError> {
        if self.profile != WRITER_FENCE_PROFILE {
            return Err(CognitiveRecoveryError::Invalid(
                "unsupported cognitive recovery writer-fence profile".to_string(),
            ));
        }
        if &self.owner_agent_id != owner {
            return Err(CognitiveRecoveryError::AccessDenied(
                "cognitive recovery writer-fence owner mismatch".to_string(),
            ));
        }
        if self.lease_id.trim().is_empty()
            || self.lease_id.len() > 512
            || self.lease_id.as_bytes().contains(&0)
            || self.lease_sequence == 0
            || self.generation == 0
            || self.authority_epoch == 0
            || self.owner_epoch == 0
            || self.lease_expires_at_unix_seconds == 0
        {
            return Err(CognitiveRecoveryError::Invalid(
                "invalid cognitive recovery writer fence".to_string(),
            ));
        }
        Sha256Digest::parse(self.lease_sha256.as_str().to_string()).map_err(|_| {
            CognitiveRecoveryError::Invalid(
                "invalid cognitive recovery writer-fence digest".to_string(),
            )
        })?;
        Ok(())
    }
}

/// Current recovery disposition supplied by the trusted host. Revocation wins
/// before any filesystem access. An exact witness is an integrity input, not a
/// grant. Cold-image reads require an exact comparison; writer recovery remains
/// unavailable until a descriptor-safe writer backend and fence exist.
#[derive(Clone, Copy)]
pub enum CognitiveRecoveryRequirement<'a> {
    ExactCurrentCut(&'a CognitiveRecoveryAnchor),
    ExactCurrentCutAndWriterFence {
        anchor: &'a CognitiveRecoveryAnchor,
        writer_fence: &'a CognitiveRecoveryWriterFence,
    },
    Revoked,
}

struct ValidatedRecoveryRequirement<'a> {
    anchor: &'a CognitiveRecoveryAnchor,
    writer_fence: Option<&'a CognitiveRecoveryWriterFence>,
}

/// Fail-closed recovery admission outcome.
///
/// This separate type preserves an indeterminate filesystem identity instead
/// of laundering it into ordinary storage unavailability. No variant carries
/// a recovered store or grants authority.
#[non_exhaustive]
#[derive(Debug, thiserror::Error)]
pub enum CognitiveRecoveryError {
    #[error("invalid cognitive recovery request: {0}")]
    Invalid(String),
    #[error("cognitive recovery access denied: {0}")]
    AccessDenied(String),
    #[error("cognitive recovery state is indeterminate: {0}")]
    Indeterminate(String),
    #[error("cognitive recovery is unavailable: {0}")]
    Unavailable(String),
}

impl CognitiveStore {
    /// Capture one coherent bounded owner cut. The host retains/authenticates it
    /// independently; this method does not publish an acknowledgement witness.
    pub async fn recovery_anchor(&self) -> Result<CognitiveRecoveryAnchor, CognitiveStoreError> {
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let anchor = capture(&mut transaction, &self.owner_agent_id).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(anchor)
    }

    /// Capture the exact active host-bound writer head that must accompany a
    /// writer recovery request. The host retains/authenticates this separately.
    pub async fn recovery_writer_fence(
        &self,
        lease_id: &str,
    ) -> Result<CognitiveRecoveryWriterFence, CognitiveStoreError> {
        if lease_id.trim().is_empty() || lease_id.len() > 512 || lease_id.as_bytes().contains(&0) {
            return Err(CognitiveStoreError::Invalid(
                "invalid cognitive recovery lease id".to_string(),
            ));
        }
        let row = sqlx::query(
            "SELECT lease_sequence, generation, state, authority_epoch, owner_epoch,
                    lease_expires_at_unix_seconds, lease_sha256
             FROM cognitive_local_leases
             WHERE lease_id = ? AND owner_agent_id = ?
             ORDER BY lease_sequence DESC LIMIT 1",
        )
        .bind(lease_id)
        .bind(self.owner_agent_id.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(unavailable)?
        .ok_or_else(|| CognitiveStoreError::AccessDenied(
            "cognitive recovery writer lease does not exist".to_string(),
        ))?;
        let state: String = row.try_get("state").map_err(unavailable)?;
        if state != "active" {
            return Err(CognitiveStoreError::AccessDenied(
                "cognitive recovery writer lease is not active".to_string(),
            ));
        }
        let lease_sequence = positive_u64(
            row.try_get("lease_sequence").map_err(unavailable)?,
            "lease sequence",
        )?;
        let generation = positive_u64(
            row.try_get("generation").map_err(unavailable)?,
            "lease generation",
        )?;
        let authority_epoch = positive_u64(
            row.try_get::<Option<i64>, _>("authority_epoch")
                .map_err(unavailable)?
                .ok_or_else(|| CognitiveStoreError::AccessDenied(
                    "cognitive recovery writer lease is not authority-bound".to_string(),
                ))?,
            "authority epoch",
        )?;
        let owner_epoch = positive_u64(
            row.try_get::<Option<i64>, _>("owner_epoch")
                .map_err(unavailable)?
                .ok_or_else(|| CognitiveStoreError::AccessDenied(
                    "cognitive recovery writer lease is not owner-bound".to_string(),
                ))?,
            "owner epoch",
        )?;
        let lease_expires_at_unix_seconds = positive_u64(
            row.try_get::<Option<i64>, _>("lease_expires_at_unix_seconds")
                .map_err(unavailable)?
                .ok_or_else(|| CognitiveStoreError::AccessDenied(
                    "cognitive recovery writer lease has no expiry".to_string(),
                ))?,
            "lease expiry",
        )?;
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?
            .as_secs();
        if now >= lease_expires_at_unix_seconds {
            return Err(CognitiveStoreError::AccessDenied(
                "cognitive recovery writer lease is expired".to_string(),
            ));
        }
        let lease_sha256: String = row.try_get("lease_sha256").map_err(unavailable)?;
        let lease_sha256 = Sha256Digest::parse(lease_sha256).map_err(CognitiveStoreError::Corrupt)?;
        Ok(CognitiveRecoveryWriterFence {
            profile: WRITER_FENCE_PROFILE.to_string(),
            owner_agent_id: self.owner_agent_id.clone(),
            lease_id: lease_id.to_string(),
            lease_sequence,
            generation,
            authority_epoch,
            owner_epoch,
            lease_expires_at_unix_seconds,
            lease_sha256,
        })
    }

    /// Validate an existing database's current cut and writer fence against a
    /// descriptor-bound cold image, then fail closed until the writable VFS is
    /// available. This never falls back to ordinary path-based opening.
    ///
    /// The state backend still has no descriptor-backed writable SQLite VFS or
    /// non-reconnecting writer connection. Before returning that one remaining
    /// unavailable result, this path proves the exact current cut and the
    /// independently retained active writer head against a cold descriptor copy.
    pub async fn open_with_recovery(
        layout: &HeptaAgentLayout,
        requirement: CognitiveRecoveryRequirement<'_>,
    ) -> Result<Self, CognitiveRecoveryError> {
        let validated = validate_requirement(layout, requirement)?;
        let writer_fence = validated.writer_fence.ok_or_else(|| {
            CognitiveRecoveryError::Unavailable(
                "cognitive writer recovery requires an independently retained current writer fence"
                    .to_string(),
            )
        })?;
        let recovered = Self::open_read_only_recovery(layout, requirement).await?;
        recovered.verify_writer_fence(writer_fence).await?;
        recovered.close().await;
        Err(CognitiveRecoveryError::Unavailable(
            "cognitive current cut and writer fence verified; descriptor-backed writable SQLite VFS is not implemented"
                .to_string(),
        ))
    }
}

fn validate_requirement<'a>(
    layout: &HeptaAgentLayout,
    requirement: CognitiveRecoveryRequirement<'a>,
) -> Result<ValidatedRecoveryRequirement<'a>, CognitiveRecoveryError> {
    let (expected, writer_fence) = match requirement {
        CognitiveRecoveryRequirement::Revoked => {
            return Err(CognitiveRecoveryError::AccessDenied(
                "cognitive recovery is revoked".to_string(),
            ));
        }
        CognitiveRecoveryRequirement::ExactCurrentCut(anchor) => (anchor, None),
        CognitiveRecoveryRequirement::ExactCurrentCutAndWriterFence {
            anchor,
            writer_fence,
        } => (anchor, Some(writer_fence)),
    };
    if expected.owner_agent_id != *layout.agent_id() {
        return Err(CognitiveRecoveryError::AccessDenied(
            "cognitive recovery owner mismatch".to_string(),
        ));
    }
    if expected.profile != PROFILE
        || expected.schema_digest.as_str() != REQUIRED_SCHEMA_ORACLE_SHA256
    {
        return Err(CognitiveRecoveryError::Invalid(
            "unsupported cognitive recovery profile or schema".to_string(),
        ));
    }
    if let Some(writer_fence) = writer_fence {
        writer_fence.validate(layout.agent_id())?;
    }
    Ok(ValidatedRecoveryRequirement {
        anchor: expected,
        writer_fence,
    })
}

fn positive_u64(value: i64, label: &str) -> Result<u64, CognitiveStoreError> {
    u64::try_from(value)
        .ok()
        .filter(|value| *value > 0)
        .ok_or_else(|| CognitiveStoreError::Corrupt(format!("invalid cognitive recovery {label}")))
}

fn recovery_error(error: SqliteRecoveryError) -> CognitiveRecoveryError {
    match error {
        SqliteRecoveryError::Unavailable => CognitiveRecoveryError::Unavailable(error.to_string()),
        SqliteRecoveryError::Indeterminate => {
            CognitiveRecoveryError::Indeterminate(error.to_string())
        }
        _ => CognitiveRecoveryError::Indeterminate(error.to_string()),
    }
}

async fn capture(
    connection: &mut SqliteConnection,
    owner: &AgentId,
) -> Result<CognitiveRecoveryAnchor, CognitiveStoreError> {
    let mut schema = REQUIRED_SCHEMA_OBJECTS.to_vec();
    schema.sort_unstable_by_key(|(name, _)| *name);
    let mut schema_hasher = Sha256::new();
    frame_part(
        &mut schema_hasher,
        b"hepta:cognitive:required-schema-oracle:v1",
    );
    frame_part(&mut schema_hasher, &(schema.len() as u64).to_be_bytes());
    let mut schema_bytes = 0_i64;
    for (name, kind) in &schema {
        let length: Option<i64> = sqlx::query_scalar(
            "SELECT length(CAST(sql AS BLOB)) FROM sqlite_schema WHERE name = ? AND type = ?",
        )
        .bind(name)
        .bind(kind)
        .fetch_optional(&mut *connection)
        .await
        .map_err(unavailable)?
        .flatten();
        let length = length.filter(|value| *value > 0).ok_or_else(|| {
            CognitiveStoreError::Corrupt("missing cognitive recovery schema object".to_string())
        })?;
        schema_bytes = schema_bytes
            .checked_add(length)
            .filter(|value| *value <= MAX_SCHEMA_BYTES)
            .ok_or_else(|| {
                CognitiveStoreError::Invalid("cognitive recovery schema exceeds bounds".to_string())
            })?;
        let sql: String = sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = ?")
            .bind(name)
            .fetch_one(&mut *connection)
            .await
            .map_err(unavailable)?;
        frame_part(&mut schema_hasher, name.as_bytes());
        frame_part(&mut schema_hasher, kind.as_bytes());
        frame_part(&mut schema_hasher, sql.as_bytes());
    }
    let schema_digest = Sha256Digest::from_sha256_output(schema_hasher.finalize());
    if schema_digest.as_str() != REQUIRED_SCHEMA_ORACLE_SHA256 {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive recovery schema mismatch".to_string(),
        ));
    }
    let stored_owner: String = sqlx::query_scalar("SELECT owner_agent_id FROM cognitive_meta WHERE singleton = 1 AND length(owner_agent_id) = 36")
        .fetch_one(&mut *connection).await.map_err(unavailable)?;
    if stored_owner != owner.as_str() {
        return Err(CognitiveStoreError::AccessDenied(
            "cognitive recovery database owner mismatch".to_string(),
        ));
    }
    let mut tables: Vec<&str> = schema
        .iter()
        .filter_map(|(name, kind)| (*kind == "table").then_some(*name))
        .collect();
    tables.push("_sqlx_migrations");
    tables.sort_unstable();
    let actual_tables: Vec<String> = sqlx::query_scalar(
        "SELECT substr(name, 1, 129) FROM pragma_table_list
         WHERE schema = 'main' AND type IN ('table', 'virtual')
           AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 256",
    )
    .fetch_all(&mut *connection)
    .await
    .map_err(unavailable)?;
    if actual_tables != tables {
        return Err(CognitiveStoreError::Corrupt(
            "unregistered cognitive recovery table".to_string(),
        ));
    }
    // Bind complete logical schema too, including extra triggers and indexes.
    // Physical root pages are deliberately excluded so checkpoint/backup does
    // not masquerade as an owner mutation. FTS shadows are covered through the
    // registered logical FTS tables rather than physical index pages.
    tables.push("sqlite_schema");
    let mut state = Sha256::new();
    frame_part(&mut state, PROFILE.as_bytes());
    frame_part(&mut state, owner.as_str().as_bytes());
    frame_part(&mut state, schema_digest.as_str().as_bytes());
    let mut remaining_rows = MAX_ROWS;
    let mut remaining_bytes = MAX_BYTES;
    for table in tables {
        let columns: Vec<String> = if table == "sqlite_schema" {
            ["type", "name", "tbl_name", "sql"]
                .into_iter()
                .map(str::to_string)
                .collect()
        } else {
            // Also bound metadata for the migration ledger before table_info
            // can materialize a maliciously oversized column name.
            let length: i64 = sqlx::query_scalar(
                "SELECT length(CAST(sql AS BLOB)) FROM sqlite_schema WHERE name = ?",
            )
            .bind(table)
            .fetch_one(&mut *connection)
            .await
            .map_err(unavailable)?;
            if !(1..=MAX_SCHEMA_BYTES).contains(&length) {
                return Err(CognitiveStoreError::Invalid(
                    "cognitive recovery table schema exceeds bounds".to_string(),
                ));
            }
            let columns = sqlx::query("SELECT name FROM pragma_table_info(?) ORDER BY cid")
                .bind(table)
                .fetch_all(&mut *connection)
                .await
                .map_err(unavailable)?;
            if columns.is_empty() || columns.len() > 64 {
                return Err(CognitiveStoreError::Corrupt(
                    "cognitive recovery table columns invalid".to_string(),
                ));
            }
            columns
                .iter()
                .map(|row| row.try_get("name"))
                .collect::<Result<_, _>>()
                .map_err(unavailable)?
        };
        let quoted: Vec<String> = columns
            .iter()
            .map(|column| format!("\"{}\"", column.replace('"', "\"\"")))
            .collect();
        let row_bytes = quoted.iter().map(|column| format!(
            "CASE typeof({column}) WHEN 'null' THEN 16 WHEN 'integer' THEN 32 WHEN 'real' THEN 32 ELSE 24 + length(CAST({column} AS BLOB)) END"
        )).collect::<Vec<_>>().join(" + ");
        // Check every encoded row's size and the cumulative budget inside the
        // locked snapshot BEFORE fetching any potentially large text or blob.
        // Dynamic fragments contain only fixed allowlisted table names and
        // double-quoted/escaped schema column identifiers, never input values.
        let mut bounds_query = sqlx::QueryBuilder::<sqlx::Sqlite>::new(
            "SELECT COUNT(*), COALESCE(SUM(row_size), 0), COALESCE(MAX(row_size), 0) FROM (SELECT ",
        );
        bounds_query
            .push(&row_bytes)
            .push(" AS row_size FROM \"")
            .push(table)
            .push("\" LIMIT ")
            .push_bind(remaining_rows + 1)
            .push(")");
        let (count, bytes, largest): (i64, i64, i64) = bounds_query
            .build_query_as()
            .fetch_one(&mut *connection)
            .await
            .map_err(unavailable)?;
        if count > remaining_rows || bytes > remaining_bytes || largest > MAX_ROW_BYTES {
            return Err(CognitiveStoreError::Invalid(
                "cognitive recovery state exceeds bounds".to_string(),
            ));
        }
        remaining_rows -= count;
        remaining_bytes -= bytes;
        frame_part(&mut state, table.as_bytes());
        frame_part(&mut state, &(columns.len() as u64).to_be_bytes());
        for column in &columns {
            frame_part(&mut state, column.as_bytes());
        }
        frame_part(&mut state, &count.to_be_bytes());
        let ordering = quoted
            .iter()
            .map(|column| format!("typeof({column}), {column} COLLATE BINARY"))
            .collect::<Vec<_>>()
            .join(", ");
        let selection = quoted.join(", ");
        let mut rows_query = sqlx::QueryBuilder::<sqlx::Sqlite>::new("SELECT ");
        rows_query
            .push(selection)
            .push(" FROM \"")
            .push(table)
            .push("\" ORDER BY ")
            .push(ordering);
        let rows = rows_query
            .build()
            .fetch_all(&mut *connection)
            .await
            .map_err(unavailable)?;
        for row in rows {
            for index in 0..columns.len() {
                let value = row.try_get_raw(index).map_err(unavailable)?;
                if value.is_null() {
                    frame_part(&mut state, b"null");
                    continue;
                }
                match value.type_info().name() {
                    "INTEGER" => {
                        frame_part(&mut state, b"integer");
                        frame_part(
                            &mut state,
                            &row.try_get::<i64, _>(index)
                                .map_err(unavailable)?
                                .to_be_bytes(),
                        );
                    }
                    "REAL" => {
                        frame_part(&mut state, b"real");
                        frame_part(
                            &mut state,
                            &row.try_get::<f64, _>(index)
                                .map_err(unavailable)?
                                .to_bits()
                                .to_be_bytes(),
                        );
                    }
                    "TEXT" => {
                        frame_part(&mut state, b"text");
                        frame_part(
                            &mut state,
                            row.try_get::<&str, _>(index)
                                .map_err(unavailable)?
                                .as_bytes(),
                        );
                    }
                    "BLOB" => {
                        frame_part(&mut state, b"blob");
                        frame_part(
                            &mut state,
                            row.try_get::<&[u8], _>(index).map_err(unavailable)?,
                        );
                    }
                    _ => {
                        return Err(CognitiveStoreError::Corrupt(
                            "unsupported cognitive recovery value type".to_string(),
                        ));
                    }
                }
            }
        }
    }
    // Keep both integrity gates in the same serialized snapshot. Run them only
    // after bounded logical reads, which also establish the current FTS view on
    // pooled connections; never expose the calculated digest before they pass.
    let check: String = sqlx::query_scalar("PRAGMA quick_check(1)")
        .fetch_one(&mut *connection)
        .await
        .map_err(unavailable)?;
    if check != "ok" {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive recovery quick_check failed".to_string(),
        ));
    }
    if sqlx::query("SELECT 1 FROM pragma_foreign_key_check LIMIT 1")
        .fetch_optional(&mut *connection)
        .await
        .map_err(unavailable)?
        .is_some()
    {
        return Err(CognitiveStoreError::Corrupt(
            "cognitive recovery foreign-key check failed".to_string(),
        ));
    }
    Ok(CognitiveRecoveryAnchor {
        profile: PROFILE.to_string(),
        owner_agent_id: owner.clone(),
        schema_digest,
        state_digest: Sha256Digest::from_sha256_output(state.finalize()),
    })
}

#[cfg(test)]
#[path = "cognitive_store_recovery_tests.rs"]
mod tests;
