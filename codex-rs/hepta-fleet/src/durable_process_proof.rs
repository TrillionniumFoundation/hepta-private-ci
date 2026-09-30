//! Read-only verification of the existing Fleet owner's native execution holds.

use std::fs;
use std::path::Path;
use std::time::Duration;

use sqlx::Row;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteRow;

use crate::DurableFleetError;
use crate::FleetExecutionContextV1;
use crate::durable_execution::native_boot_identity;
use crate::durable_execution::native_containment;
use crate::durable_execution::native_process;
use crate::durable_rows::decode_json;
use crate::durable_rows::to_i64;
use crate::durable_rows::to_u64;
use crate::durable_rows::validate_identity;
use crate::durable_schema::sqlx_error;

pub(crate) const PROCESS_PROOF_QUERY: &str = "SELECT context_json, boot_identity, state, process_id, process_group, process_start_ticks, containment_dev, containment_ino FROM fleet_execution_holds WHERE execution_id = ?";

/// A prepared launch may execute its initialization before the parent commits
/// the native PID binding. Only `Bound` establishes the enrolled main process.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FleetProcessBinding {
    PendingBinding,
    Bound(FleetExecutionContextV1),
}

impl FleetProcessBinding {
    pub(crate) fn bound_context(self) -> Result<FleetExecutionContextV1, DurableFleetError> {
        match self {
            Self::Bound(context) => Ok(context),
            Self::PendingBinding => Err(DurableFleetError::Stale),
        }
    }
}

/// An independent authority reads the Fleet owner's protected SQLite records.
/// Opening this reader does not initialize schema, register a clock, admit a
/// resource grant or create an alternate process identity ledger.
pub struct FleetExecutionVerifier {
    pool: SqlitePool,
}

impl FleetExecutionVerifier {
    pub async fn open(database: &Path) -> Result<Self, DurableFleetError> {
        validate_database(database)?;
        let options = SqliteConnectOptions::new()
            .filename(database)
            .create_if_missing(false)
            .read_only(true)
            .busy_timeout(Duration::from_secs(1));
        let pool = SqlitePoolOptions::new()
            .max_connections(2)
            .connect_with(options)
            .await
            .map_err(sqlx_error)?;
        Ok(Self { pool })
    }

    /// Verify a currently running main process against root-owned persisted
    /// PID/start/boot/cgroup identity and the actual kernel task. An issuer may
    /// wait on `PendingBinding` within the same bounded request deadline; it
    /// must never grant authority before observing `Bound`.
    pub async fn verify_bound_local_process(
        &self,
        execution_id: &str,
        principal_id: &str,
        peer_pid: u32,
    ) -> Result<FleetProcessBinding, DurableFleetError> {
        validate_identity(execution_id, "execution")?;
        validate_identity(principal_id, "principal")?;
        let row = sqlx::query(PROCESS_PROOF_QUERY)
            .bind(execution_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(sqlx_error)?
            .ok_or_else(|| DurableFleetError::Missing(execution_id.into()))?;
        let context: FleetExecutionContextV1 = decode_json(
            &row.try_get::<String, _>("context_json")
                .map_err(sqlx_error)?,
        )?;
        let state: String = row.try_get("state").map_err(sqlx_error)?;
        if context.principal_id != principal_id || !matches!(state.as_str(), "prepared" | "running")
        {
            return Err(DurableFleetError::Stale);
        }
        verify_record(&row, execution_id, peer_pid)
    }
}

pub(crate) fn verify_record(
    row: &SqliteRow,
    execution_id: &str,
    pid: u32,
) -> Result<FleetProcessBinding, DurableFleetError> {
    validate_identity(execution_id, "execution")?;
    let state: String = row.try_get("state").map_err(sqlx_error)?;
    let boot: String = row.try_get("boot_identity").map_err(sqlx_error)?;
    let saved_pid: Option<i64> = row.try_get("process_id").map_err(sqlx_error)?;
    let group: Option<i64> = row.try_get("process_group").map_err(sqlx_error)?;
    let ticks: Option<i64> = row.try_get("process_start_ticks").map_err(sqlx_error)?;
    if !matches!(state.as_str(), "prepared" | "running" | "stop_requested")
        || boot != native_boot_identity()?
    {
        return Err(DurableFleetError::Stale);
    }
    let context: FleetExecutionContextV1 = decode_json(
        &row.try_get::<String, _>("context_json")
            .map_err(sqlx_error)?,
    )?;
    let dev = to_u64(row.try_get("containment_dev").map_err(sqlx_error)?)?;
    let ino = to_u64(row.try_get("containment_ino").map_err(sqlx_error)?)?;
    if context.execution_id != execution_id
        || native_containment(&context.containment)? != (dev, ino)
    {
        return Err(DurableFleetError::Stale);
    }
    let native = native_process(pid)?.ok_or(DurableFleetError::Stale)?;
    if native.group != u64::from(pid) {
        return Err(DurableFleetError::Stale);
    }
    let pending = saved_pid.is_none() && group.is_none() && ticks.is_none() && state == "prepared";
    if !pending
        && (saved_pid != Some(i64::from(pid))
            || group != Some(to_i64(native.group)?)
            || ticks != Some(to_i64(native.start_ticks)?))
    {
        return Err(DurableFleetError::Stale);
    }
    let marker = format!("HEPTA_FLEET_EXECUTION_ID={execution_id}");
    let environ = fs::read(format!("/proc/{pid}/environ"))
        .map_err(|error| DurableFleetError::Unavailable(error.to_string()))?;
    let membership = fs::read_to_string(format!("/proc/{pid}/cgroup"))
        .map_err(|error| DurableFleetError::Unavailable(error.to_string()))?;
    if !environ
        .split(|byte| *byte == 0)
        .any(|entry| entry == marker.as_bytes())
        || !membership
            .lines()
            .any(|line| line == format!("0::/{}", context.containment))
        || native_process(pid)?.map(|p| (p.group, p.start_ticks))
            != Some((native.group, native.start_ticks))
    {
        return Err(DurableFleetError::Stale);
    }
    Ok(if pending {
        FleetProcessBinding::PendingBinding
    } else {
        FleetProcessBinding::Bound(context)
    })
}

#[cfg(unix)]
fn validate_database(database: &Path) -> Result<(), DurableFleetError> {
    use std::os::unix::fs::MetadataExt;
    if !database.is_absolute()
        || database
            .canonicalize()
            .map_err(|error| DurableFleetError::Unavailable(error.to_string()))?
            != database
    {
        return Err(DurableFleetError::Invalid(
            "Fleet database must be absolute without links".into(),
        ));
    }
    for ancestor in database.ancestors() {
        let metadata = fs::symlink_metadata(ancestor)
            .map_err(|error| DurableFleetError::Unavailable(error.to_string()))?;
        if metadata.uid() != 0
            || metadata.mode() & 0o022 != 0
            || (ancestor == database && !metadata.is_file())
            || (ancestor != database && !metadata.is_dir())
        {
            return Err(DurableFleetError::Invalid(
                "Fleet proof database and ancestors must be root protected".into(),
            ));
        }
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_database(_database: &Path) -> Result<(), DurableFleetError> {
    Err(DurableFleetError::Unavailable(
        "protected Fleet proof requires Unix".into(),
    ))
}
