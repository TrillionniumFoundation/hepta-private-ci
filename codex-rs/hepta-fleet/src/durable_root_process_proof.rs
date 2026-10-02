//! Root-local proof of an already persisted, bound native execution.

use std::fs::File;
use std::io::Read;

use sqlx::Row;
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

pub(crate) fn verify_root_record(
    row: &SqliteRow,
    execution_id: &str,
    pid: u32,
    workload_uid: u32,
) -> Result<FleetExecutionContextV1, DurableFleetError> {
    validate_identity(execution_id, "execution")?;
    if workload_uid == 0 || kernel_uid("/proc/thread-self/status")? != 0 {
        return Err(DurableFleetError::Invalid(
            "bound Root resource observation requires Root and a non-Root workload".into(),
        ));
    }
    let state: String = row.try_get("state").map_err(sqlx_error)?;
    let boot: String = row.try_get("boot_identity").map_err(sqlx_error)?;
    let saved_pid: Option<i64> = row.try_get("process_id").map_err(sqlx_error)?;
    let group: Option<i64> = row.try_get("process_group").map_err(sqlx_error)?;
    let ticks: Option<i64> = row.try_get("process_start_ticks").map_err(sqlx_error)?;
    if state != "running" || boot != native_boot_identity()? {
        return Err(DurableFleetError::Stale);
    }
    let context: FleetExecutionContextV1 = decode_json(
        &row.try_get::<String, _>("context_json")
            .map_err(sqlx_error)?,
    )?;
    let dev = to_u64(row.try_get("containment_dev").map_err(sqlx_error)?)?;
    let ino = to_u64(row.try_get("containment_ino").map_err(sqlx_error)?)?;
    // This existing check covers every Root-owned, non-writable ancestor,
    // cgroup.procs, cgroup.events and the saved directory device/inode.
    if context.execution_id != execution_id
        || native_containment(&context.containment)? != (dev, ino)
        || kernel_uid(&format!("/proc/{pid}/status"))? != workload_uid
    {
        return Err(DurableFleetError::Stale);
    }
    let native = native_process(pid)?.ok_or(DurableFleetError::Stale)?;
    if native.group != u64::from(pid)
        || saved_pid != Some(i64::from(pid))
        || group != Some(to_i64(native.group)?)
        || ticks != Some(to_i64(native.start_ticks)?)
        || read_kernel(&format!("/proc/{pid}/cgroup"))? != format!("0::/{}\n", context.containment)
        || native_process(pid)?.map(|p| (p.group, p.start_ticks))
            != Some((native.group, native.start_ticks))
        || kernel_uid(&format!("/proc/{pid}/status"))? != workload_uid
        || native_containment(&context.containment)? != (dev, ino)
        || native_boot_identity()? != boot
    {
        return Err(DurableFleetError::Stale);
    }
    Ok(context)
}

fn kernel_uid(path: &str) -> Result<u32, DurableFleetError> {
    let status = read_kernel(path)?;
    let line = status
        .lines()
        .find_map(|line| line.strip_prefix("Uid:"))
        .ok_or_else(|| DurableFleetError::Corrupt("missing kernel UID identity".into()))?;
    let values = line
        .split_whitespace()
        .map(str::parse::<u32>)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| DurableFleetError::Corrupt("invalid kernel UID identity".into()))?;
    if values.len() != 4 || values.iter().any(|uid| *uid != values[0]) {
        return Err(DurableFleetError::Stale);
    }
    Ok(values[0])
}

fn read_kernel(path: &str) -> Result<String, DurableFleetError> {
    const MAXIMUM: u64 = 65_536;
    let mut value = String::new();
    File::open(path)
        .and_then(|file| file.take(MAXIMUM + 1).read_to_string(&mut value))
        .map_err(|error| DurableFleetError::Unavailable(error.to_string()))?;
    if value.len() as u64 > MAXIMUM {
        return Err(DurableFleetError::Corrupt(
            "kernel process metadata exceeded its bound".into(),
        ));
    }
    Ok(value)
}
