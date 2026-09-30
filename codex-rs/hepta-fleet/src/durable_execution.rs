//! Execution occupancy belongs to the existing durable owner, not a second ledger.
//!
//! An unusable lease is not proof of process exit. Reservations for prepared or
//! running executions survive expiry, revocation and owner restart. The process
//! owner must reconcile an indeterminate launch; an absent PID is not permission
//! to release capacity or launch again. These records are accounting state, not
//! generic authority or production acceptance.

use std::fs;
use std::io::ErrorKind;

use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;

use crate::DurableFleetError;
use crate::DurableFleetStore;
use crate::ResourceVectorV1;
use crate::durable_grant_tx::load_total_tx;
use crate::durable_grant_tx::retire_grant_tx;
use crate::durable_grant_tx::select_grant_tx;
use crate::durable_grant_tx::select_host_tx;
use crate::durable_grant_tx::write_total_tx;
use crate::durable_rows::decode_json;
use crate::durable_rows::encode_json;
use crate::durable_rows::to_i64;
use crate::durable_rows::to_u64;
use crate::durable_rows::validate_digest;
use crate::durable_rows::validate_identity;
use crate::durable_schema::sqlx_error;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetExecutionContextV1 {
    pub execution_id: String,
    pub allocation_id: String,
    pub principal_id: String,
    /// Selected execution-host identity, independently supplied by its owner.
    pub host_id: String,
    pub host_generation: u64,
    pub lease_generation: u64,
    /// Digest of the actual immutable execution configuration.
    pub manifest_digest: String,
    /// Exact budget consumed by that configuration, including logical axes.
    pub resources: ResourceVectorV1,
    /// Root-owned cgroup v2 relative path, not writable by the workload.
    pub containment: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetExecutionHoldV1 {
    pub context: FleetExecutionContextV1,
    pub state: String,
    pub process_id: Option<u64>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FleetFailureDispositionV1 {
    RetryWithoutNewAdmissions,
    ReconcileBeforeRetry,
    RejectRequest,
    QuarantineOwner,
}

impl DurableFleetError {
    pub fn disposition(&self) -> FleetFailureDispositionV1 {
        match self {
            Self::Capacity | Self::Unavailable(_) | Self::ClockUnavailable => {
                FleetFailureDispositionV1::RetryWithoutNewAdmissions
            }
            Self::IndeterminateCommit { .. } => FleetFailureDispositionV1::ReconcileBeforeRetry,
            Self::Invalid(_)
            | Self::Conflict(_)
            | Self::Missing(_)
            | Self::Stale
            | Self::Authority(_) => FleetFailureDispositionV1::RejectRequest,
            Self::Corrupt(_) | Self::ClockRollback => FleetFailureDispositionV1::QuarantineOwner,
        }
    }
}

impl DurableFleetStore {
    /// Allocate an ordered incarnation from native boot identity in the same
    /// SQLite writer boundary as the fleet's capacity and grants.
    pub async fn register_local_boot(&self, host_id: &str) -> Result<u64, DurableFleetError> {
        self.register_boot_identity(host_id, &native_boot_identity()?)
            .await
    }

    pub(crate) async fn register_boot_identity(
        &self,
        host_id: &str,
        boot_identity: &str,
    ) -> Result<u64, DurableFleetError> {
        validate_identity(host_id, "host")?;
        validate_identity(boot_identity, "boot identity")?;
        let now_ms = self.owner_now_ms()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        let current = sqlx::query(
            "SELECT boot_identity, generation FROM fleet_host_incarnations WHERE host_id = ?",
        )
        .bind(host_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        let observed: Option<i64> =
            sqlx::query_scalar("SELECT generation FROM fleet_hosts WHERE host_id = ?")
                .bind(host_id)
                .fetch_optional(&mut *tx)
                .await
                .map_err(sqlx_error)?;
        let generation = if let Some(row) = current {
            let accepted_boot: String = row.try_get("boot_identity").map_err(sqlx_error)?;
            let generation: i64 = row.try_get("generation").map_err(sqlx_error)?;
            if accepted_boot == boot_identity && observed.unwrap_or(0) <= generation {
                tx.commit().await.map_err(sqlx_error)?;
                return to_u64(generation);
            }
            let seen: bool = sqlx::query_scalar(
                "SELECT EXISTS(SELECT 1 FROM fleet_seen_boots
                 WHERE host_id = ? AND boot_identity = ?)",
            )
            .bind(host_id)
            .bind(boot_identity)
            .fetch_one(&mut *tx)
            .await
            .map_err(sqlx_error)?;
            if seen && accepted_boot != boot_identity {
                return Err(DurableFleetError::Stale);
            }
            // Upgrade recovery for predecessor capacity writers which advanced
            // a snapshot generation independently of the boot fence. Never
            // adopt their grants as current authority: advance and retire them.
            generation
                .max(observed.unwrap_or(0))
                .checked_add(1)
                .ok_or_else(|| DurableFleetError::Invalid("host incarnation exhausted".into()))?
        } else {
            observed
                .unwrap_or(0)
                .checked_add(1)
                .ok_or_else(|| DurableFleetError::Invalid("host incarnation exhausted".into()))?
        };
        sqlx::query(
            "INSERT INTO fleet_seen_boots(host_id, boot_identity, generation) VALUES(?, ?, ?)
             ON CONFLICT(host_id, boot_identity) DO UPDATE SET generation = excluded.generation",
        )
        .bind(host_id)
        .bind(boot_identity)
        .bind(generation)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        sqlx::query(
            "INSERT INTO fleet_host_incarnations(host_id, boot_identity, generation, updated_at_ms)
             VALUES(?, ?, ?, ?) ON CONFLICT(host_id) DO UPDATE SET
             boot_identity = excluded.boot_identity, generation = excluded.generation,
             updated_at_ms = excluded.updated_at_ms",
        )
        .bind(host_id)
        .bind(boot_identity)
        .bind(generation)
        .bind(to_i64(now_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        // A real boot change immediately invalidates old admissions. Prepared
        // or running execution holds retain occupancy and require native stop
        // reconciliation; boot identity is not process-exit evidence.
        self.retire_host_generation_tx(&mut tx, host_id, to_u64(generation)?, now_ms)
            .await?;
        tx.commit().await.map_err(|_| {
            self.indeterminate(
                format!("incarnation:{host_id}:{generation}"),
                host_id.into(),
            )
        })?;
        to_u64(generation)
    }

    /// Commit a fresh hold before spawn. A retry must inspect pending state,
    /// never launch again merely because an earlier preparation succeeded.
    /// The caller still needs independent generic authority at its effect boundary.
    pub async fn prepare_local_execution(
        &self,
        context: &FleetExecutionContextV1,
    ) -> Result<FleetExecutionHoldV1, DurableFleetError> {
        for (value, label) in [
            (context.execution_id.as_str(), "execution"),
            (context.allocation_id.as_str(), "allocation"),
            (context.principal_id.as_str(), "principal"),
            (context.host_id.as_str(), "actual host"),
        ] {
            validate_identity(value, label)?;
        }
        validate_digest(&context.manifest_digest)?;
        context
            .resources
            .validate_nonzero()
            .map_err(|error| DurableFleetError::Invalid(error.to_string()))?;
        let boot = native_boot_identity()?;
        let now_ms = self.owner_now_ms()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        let incarnation = sqlx::query(
            "SELECT boot_identity, generation FROM fleet_host_incarnations WHERE host_id = ?",
        )
        .bind(&context.host_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(sqlx_error)?
        .ok_or(DurableFleetError::Stale)?;
        let accepted_boot: String = incarnation.try_get("boot_identity").map_err(sqlx_error)?;
        let generation = to_u64(incarnation.try_get("generation").map_err(sqlx_error)?)?;
        if boot != accepted_boot || generation != context.host_generation {
            return Err(DurableFleetError::Stale);
        }
        let grant = select_grant_tx(&mut tx, &context.allocation_id)
            .await?
            .ok_or(DurableFleetError::Stale)?;
        let host = select_host_tx(&mut tx, &context.host_id)
            .await?
            .ok_or(DurableFleetError::Stale)?;
        if grant.principal_id != context.principal_id
            || grant.host_id != context.host_id
            || grant.host_generation != context.host_generation
            || grant.lease_generation != context.lease_generation
            || grant.semantic_digest != context.manifest_digest
            || grant.resources != context.resources
            || grant.failure_domain_id != host.failure_domain_id
            || grant.revoked
            || now_ms >= grant.expires_at_ms
            || host.generation != context.host_generation
            || now_ms < host.observed_at_ms
            || now_ms >= host.valid_until_ms
        {
            return Err(DurableFleetError::Stale);
        }
        let containment = native_containment(&context.containment)?;
        let exists: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM fleet_execution_holds WHERE execution_id = ?)",
        )
        .bind(&context.execution_id)
        .fetch_one(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        if exists {
            return Err(DurableFleetError::Conflict(
                "launch identity already prepared; reconcile instead of respawning".into(),
            ));
        }
        require_empty_containment(&context.containment)?;
        sqlx::query(
            "INSERT INTO fleet_execution_holds(execution_id, allocation_id, host_id, boot_identity,
             context_json, state, prepared_at_ms, containment_dev, containment_ino)
             VALUES(?, ?, ?, ?, ?, 'prepared', ?, ?, ?)",
        )
        .bind(&context.execution_id)
        .bind(&context.allocation_id)
        .bind(&context.host_id)
        .bind(boot)
        .bind(encode_json(context)?)
        .bind(to_i64(now_ms)?)
        .bind(to_i64(containment.0)?)
        .bind(to_i64(containment.1)?)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        tx.commit().await.map_err(|_| {
            self.indeterminate(context.execution_id.clone(), context.allocation_id.clone())
        })?;
        Ok(FleetExecutionHoldV1 {
            context: context.clone(),
            state: "prepared".into(),
            process_id: None,
        })
    }

    /// Bind a native group leader. The process driver must install the launch
    /// marker before spawn and place the child in the protected containment.
    pub async fn bind_local_process(
        &self,
        execution_id: &str,
        process_id: u32,
    ) -> Result<(), DurableFleetError> {
        validate_identity(execution_id, "execution")?;
        let native = native_process(process_id)?.ok_or(DurableFleetError::Stale)?;
        if native.group != u64::from(process_id) {
            return Err(DurableFleetError::Invalid(
                "execution must own a dedicated process group".into(),
            ));
        }
        let environ = fs::read(format!("/proc/{process_id}/environ")).map_err(native_io)?;
        let marker = format!("HEPTA_FLEET_EXECUTION_ID={execution_id}");
        if !environ
            .split(|byte| *byte == 0)
            .any(|entry| entry == marker.as_bytes())
        {
            return Err(DurableFleetError::Stale);
        }
        let boot = native_boot_identity()?;
        let now_ms = self.owner_now_ms()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        let hold = sqlx::query(
            "SELECT context_json, containment_dev, containment_ino FROM fleet_execution_holds
             WHERE execution_id = ?",
        )
        .bind(execution_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(sqlx_error)?
        .ok_or(DurableFleetError::Stale)?;
        let json: String = hold.try_get("context_json").map_err(sqlx_error)?;
        let context: FleetExecutionContextV1 = decode_json(&json)?;
        let dev = to_u64(hold.try_get("containment_dev").map_err(sqlx_error)?)?;
        let ino = to_u64(hold.try_get("containment_ino").map_err(sqlx_error)?)?;
        if native_containment(&context.containment)? != (dev, ino) {
            return Err(DurableFleetError::Stale);
        }
        let memberships =
            fs::read_to_string(format!("/proc/{process_id}/cgroup")).map_err(native_io)?;
        let expected = format!("0::/{}", context.containment);
        if !memberships.lines().any(|line| line == expected) {
            return Err(DurableFleetError::Stale);
        }
        if native_process(process_id)?.map(|process| (process.group, process.start_ticks))
            != Some((native.group, native.start_ticks))
        {
            return Err(DurableFleetError::Stale);
        }
        let changed = sqlx::query(
            "UPDATE fleet_execution_holds SET process_id = ?, process_group = ?, process_start_ticks = ?,
             state = CASE WHEN state = 'prepared' THEN 'running' ELSE state END
             WHERE execution_id = ? AND boot_identity = ? AND process_id IS NULL
             AND state IN ('prepared', 'stop_requested')",
        )
        .bind(i64::from(process_id))
        .bind(to_i64(native.group)?)
        .bind(to_i64(native.start_ticks)?)
        .bind(execution_id)
        .bind(boot)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?
        .rows_affected();
        if changed != 1 {
            return Err(DurableFleetError::Conflict(execution_id.into()));
        }
        tx.commit()
            .await
            .map_err(|_| self.indeterminate(format!("bind:{execution_id}"), execution_id.into()))
    }

    pub async fn pending_executions(&self) -> Result<Vec<FleetExecutionHoldV1>, DurableFleetError> {
        let rows = sqlx::query(
            "SELECT context_json, state, process_id FROM fleet_execution_holds
             WHERE state != 'stopped' ORDER BY prepared_at_ms, execution_id",
        )
        .fetch_all(&self.pool)
        .await
        .map_err(sqlx_error)?;
        rows.into_iter()
            .map(|row| {
                let json: String = row.try_get("context_json").map_err(sqlx_error)?;
                let pid: Option<i64> = row.try_get("process_id").map_err(sqlx_error)?;
                Ok(FleetExecutionHoldV1 {
                    context: decode_json(&json)?,
                    state: row.try_get("state").map_err(sqlx_error)?,
                    process_id: pid.map(to_u64).transpose()?,
                })
            })
            .collect()
    }

    /// TTL and revocation never call this themselves. Require native absence of
    /// the recorded process, its process group and its protected cgroup subtree.
    pub async fn confirm_local_exit(&self, execution_id: &str) -> Result<(), DurableFleetError> {
        let now_ms = self.owner_now_ms()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sqlx_error)?;
        Self::advance_clock_tx(&mut tx, now_ms).await?;
        let row = sqlx::query(
            "SELECT context_json, boot_identity, state, process_id, process_group,
             process_start_ticks, containment_dev, containment_ino
             FROM fleet_execution_holds WHERE execution_id = ?",
        )
        .bind(execution_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(sqlx_error)?
        .ok_or_else(|| DurableFleetError::Missing(execution_id.into()))?;
        let state: String = row.try_get("state").map_err(sqlx_error)?;
        if state == "stopped" {
            tx.commit().await.map_err(sqlx_error)?;
            return Ok(());
        }
        let json: String = row.try_get("context_json").map_err(sqlx_error)?;
        let context: FleetExecutionContextV1 = decode_json(&json)?;
        let boot: String = row.try_get("boot_identity").map_err(sqlx_error)?;
        let current_boot = native_boot_identity()?;
        if boot == current_boot {
            let dev = to_u64(row.try_get("containment_dev").map_err(sqlx_error)?)?;
            let ino = to_u64(row.try_get("containment_ino").map_err(sqlx_error)?)?;
            if native_containment(&context.containment)? != (dev, ino) {
                return Err(DurableFleetError::Stale);
            }
            require_empty_containment(&context.containment)?;
            let pid: Option<i64> = row.try_get("process_id").map_err(sqlx_error)?;
            let group: Option<i64> = row.try_get("process_group").map_err(sqlx_error)?;
            let ticks: Option<i64> = row.try_get("process_start_ticks").map_err(sqlx_error)?;
            let (Some(pid), Some(group), Some(ticks)) = (pid, group, ticks) else {
                return Err(DurableFleetError::Conflict(
                    "unbound launch requires recovery, not capacity release".into(),
                ));
            };
            let pid = u32::try_from(pid)
                .map_err(|_| DurableFleetError::Corrupt("invalid process ID".into()))?;
            if let Some(process) = native_process(pid)?
                && process.start_ticks == to_u64(ticks)?
            {
                return Err(DurableFleetError::Conflict(
                    "execution process has not been reaped".into(),
                ));
            }
            if process_group_exists(to_u64(group)?)? {
                return Err(DurableFleetError::Conflict(
                    "execution descendants have not stopped".into(),
                ));
            }
        } else {
            // Native reboot proves old OS processes are gone only after the
            // local owner has recorded this new boot, never from a caller DTO.
            let accepted: Option<String> = sqlx::query_scalar(
                "SELECT boot_identity FROM fleet_host_incarnations WHERE host_id = ?",
            )
            .bind(&context.host_id)
            .fetch_optional(&mut *tx)
            .await
            .map_err(sqlx_error)?;
            if accepted.as_deref() != Some(current_boot.as_str()) {
                return Err(DurableFleetError::Stale);
            }
        }
        sqlx::query(
            "UPDATE fleet_execution_holds SET state = 'stopped', stopped_at_ms = ?
             WHERE execution_id = ?",
        )
        .bind(to_i64(now_ms)?)
        .bind(execution_id)
        .execute(&mut *tx)
        .await
        .map_err(sqlx_error)?;
        if let Some(grant) = select_grant_tx(&mut tx, &context.allocation_id).await? {
            retire_grant_tx(&mut tx, &grant, "execution_stopped", now_ms).await?;
        } else {
            let total = load_total_tx(&mut tx, &context.host_id).await?;
            let next = total
                .checked_sub(context.resources)
                .map_err(|error| DurableFleetError::Corrupt(error.to_string()))?;
            write_total_tx(&mut tx, &context.host_id, next, now_ms).await?;
        }
        tx.commit()
            .await
            .map_err(|_| self.indeterminate(format!("stopped:{execution_id}"), execution_id.into()))
    }
}

#[cfg(target_os = "linux")]
fn native_containment(relative: &str) -> Result<(u64, u64), DurableFleetError> {
    use std::os::unix::fs::MetadataExt;

    if relative.is_empty()
        || relative.len() > 512
        || relative.split('/').any(|part| {
            part.is_empty()
                || part == "."
                || part == ".."
                || !part
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:".contains(&byte))
        })
    {
        return Err(DurableFleetError::Invalid(
            "invalid execution containment path".into(),
        ));
    }
    let root = std::path::Path::new("/sys/fs/cgroup");
    let path = root.join(relative);
    if path.canonicalize().map_err(native_io)? != path {
        return Err(DurableFleetError::Invalid(
            "containment symlink is forbidden".into(),
        ));
    }
    for ancestor in path
        .ancestors()
        .take_while(|ancestor| ancestor.starts_with(root))
    {
        let metadata = fs::symlink_metadata(ancestor).map_err(native_io)?;
        if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
            return Err(DurableFleetError::Invalid(
                "containment must be protected from workload writes".into(),
            ));
        }
    }
    for name in ["cgroup.procs", "cgroup.events"] {
        let metadata = fs::symlink_metadata(path.join(name)).map_err(native_io)?;
        if !metadata.is_file() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
            return Err(DurableFleetError::Invalid(
                "unprotected execution containment".into(),
            ));
        }
    }
    let metadata = fs::symlink_metadata(path).map_err(native_io)?;
    Ok((metadata.dev(), metadata.ino()))
}

#[cfg(not(target_os = "linux"))]
fn native_containment(_relative: &str) -> Result<(u64, u64), DurableFleetError> {
    Err(DurableFleetError::Unavailable(
        "native containment proof requires Linux".into(),
    ))
}

fn require_empty_containment(relative: &str) -> Result<(), DurableFleetError> {
    let events = fs::read_to_string(format!("/sys/fs/cgroup/{relative}/cgroup.events"))
        .map_err(native_io)?;
    if events
        .lines()
        .filter(|line| line.starts_with("populated "))
        .collect::<Vec<_>>()
        != ["populated 0"]
    {
        return Err(DurableFleetError::Conflict(
            "execution containment is not proven empty".into(),
        ));
    }
    Ok(())
}

fn native_io(error: std::io::Error) -> DurableFleetError {
    DurableFleetError::Unavailable(error.to_string())
}

pub(crate) fn native_boot_identity() -> Result<String, DurableFleetError> {
    if !cfg!(target_os = "linux") {
        return Err(DurableFleetError::Unavailable(
            "native execution proof requires Linux procfs".into(),
        ));
    }
    let boot = fs::read_to_string("/proc/sys/kernel/random/boot_id").map_err(native_io)?;
    let boot = boot.trim();
    if boot.len() != 36
        || !boot.bytes().enumerate().all(|(index, byte)| {
            if [8, 13, 18, 23].contains(&index) {
                byte == b'-'
            } else {
                byte.is_ascii_hexdigit()
            }
        })
    {
        return Err(DurableFleetError::Corrupt(
            "invalid native boot identity".into(),
        ));
    }
    Ok(boot.to_ascii_lowercase())
}

struct NativeProcess {
    group: u64,
    start_ticks: u64,
}

fn native_process(pid: u32) -> Result<Option<NativeProcess>, DurableFleetError> {
    let stat = match fs::read_to_string(format!("/proc/{pid}/stat")) {
        Ok(stat) => stat,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(native_io(error)),
    };
    let (_, fields) = stat
        .rsplit_once(')')
        .ok_or_else(|| DurableFleetError::Corrupt("invalid native process stat".into()))?;
    let fields: Vec<&str> = fields.split_whitespace().collect();
    let value = |index: usize| -> Result<u64, DurableFleetError> {
        fields
            .get(index)
            .and_then(|text| text.parse().ok())
            .ok_or_else(|| DurableFleetError::Corrupt("invalid native process identity".into()))
    };
    Ok(Some(NativeProcess {
        group: value(2)?,
        start_ticks: value(19)?,
    }))
}

fn process_group_exists(group: u64) -> Result<bool, DurableFleetError> {
    for entry in fs::read_dir("/proc").map_err(native_io)? {
        let entry = entry.map_err(native_io)?;
        let Ok(pid) = entry.file_name().to_string_lossy().parse::<u32>() else {
            continue;
        };
        if let Some(process) = native_process(pid)?
            && process.group == group
        {
            return Ok(true);
        }
    }
    Ok(false)
}

#[cfg(all(test, target_os = "linux"))]
#[path = "durable_execution_tests.rs"]
mod tests;
