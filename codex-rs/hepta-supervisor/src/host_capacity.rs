#[cfg(target_os = "macos")]
use std::process::Command;

use codex_hepta_fleet::FleetResourceVectorV1;
use codex_hepta_fleet::lease_ledger::HostObservation;

use crate::SupervisorError;

#[cfg(target_os = "macos")]
const MIB: u64 = 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HostCapacityPolicyV1 {
    pub max_concurrent_turns: u64,
    pub max_tool_processes: u64,
    pub turn_queue_slots: u64,
    pub memory_reserve_mib: u64,
}

impl HostCapacityPolicyV1 {
    fn validate(self) -> Result<(), SupervisorError> {
        if self.max_concurrent_turns == 0
            || self.max_tool_processes == 0
            || self.turn_queue_slots == 0
        {
            return Err(SupervisorError::FleetAllocation(
                "host capacity policy requires non-zero soft-axis limits".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MeasuredHostCapacityV1 {
    pub observation: HostObservation,
    pub logical_processors: u64,
    pub measured_memory_mib: u64,
}

/// Measure the local host and combine those physical facts with explicit policy
/// ceilings for the non-physical Fleet axes. The result is still only an
/// observation: publishing it into Fleet state requires the existing signed
/// final-use authority path.
pub fn observe_local_host_capacity_v1(
    host_id: String,
    failure_domain_id: String,
    generation: u64,
    now_ms: u64,
    ttl_ms: u64,
    policy: HostCapacityPolicyV1,
) -> Result<MeasuredHostCapacityV1, SupervisorError> {
    policy.validate()?;
    if generation == 0 || now_ms == 0 || ttl_ms == 0 {
        return Err(SupervisorError::FleetAllocation(
            "host capacity observation requires non-zero generation, time and ttl".to_string(),
        ));
    }
    let valid_until_ms = now_ms.checked_add(ttl_ms).ok_or_else(|| {
        SupervisorError::FleetAllocation("host capacity observation ttl overflow".to_string())
    })?;
    let logical_processors = u64::try_from(
        std::thread::available_parallelism()
            .map_err(|error| SupervisorError::FleetAllocation(error.to_string()))?
            .get(),
    )
    .map_err(|_| SupervisorError::FleetAllocation("logical CPU count overflow".to_string()))?;
    let measured_memory_mib = physical_memory_mib()?;
    let allocatable_memory_mib = measured_memory_mib
        .checked_sub(policy.memory_reserve_mib)
        .filter(|value| *value > 0)
        .ok_or_else(|| {
            SupervisorError::FleetAllocation(
                "configured memory reserve consumes all measured host memory".to_string(),
            )
        })?;
    let capacity = FleetResourceVectorV1 {
        concurrent_turns: logical_processors.min(policy.max_concurrent_turns),
        memory_mib: allocatable_memory_mib,
        tool_processes: policy.max_tool_processes,
        turn_queue_slots: policy.turn_queue_slots,
    };
    Ok(MeasuredHostCapacityV1 {
        observation: HostObservation {
            host_id,
            failure_domain_id,
            generation,
            observed_at_ms: now_ms,
            valid_until_ms,
            capacity,
        },
        logical_processors,
        measured_memory_mib,
    })
}

#[cfg(target_os = "linux")]
fn physical_memory_mib() -> Result<u64, SupervisorError> {
    parse_linux_meminfo(&std::fs::read_to_string("/proc/meminfo")?)
}

#[cfg(target_os = "macos")]
fn physical_memory_mib() -> Result<u64, SupervisorError> {
    let output = Command::new("/usr/sbin/sysctl")
        .args(["-n", "hw.memsize"])
        .output()
        .map_err(|error| SupervisorError::FleetAllocation(error.to_string()))?;
    if !output.status.success() {
        return Err(SupervisorError::FleetAllocation(
            "sysctl hw.memsize failed".to_string(),
        ));
    }
    let text = std::str::from_utf8(&output.stdout)
        .map_err(|error| SupervisorError::FleetAllocation(error.to_string()))?;
    let bytes: u64 = text
        .trim()
        .parse()
        .map_err(|_| SupervisorError::FleetAllocation("invalid hw.memsize output".to_string()))?;
    let mib = bytes / MIB;
    if mib == 0 {
        return Err(SupervisorError::FleetAllocation(
            "measured host memory is zero".to_string(),
        ));
    }
    Ok(mib)
}

#[cfg(not(any(target_os = "linux", target_os = "macos")))]
fn physical_memory_mib() -> Result<u64, SupervisorError> {
    Err(SupervisorError::FleetAllocation(
        "physical memory observation is unsupported on this host OS".to_string(),
    ))
}

#[cfg(target_os = "linux")]
fn parse_linux_meminfo(contents: &str) -> Result<u64, SupervisorError> {
    for line in contents.lines() {
        if let Some(value) = line.strip_prefix("MemTotal:") {
            let mut fields = value.split_whitespace();
            let kib: u64 = fields
                .next()
                .ok_or_else(|| SupervisorError::FleetAllocation("missing MemTotal value".to_string()))?
                .parse()
                .map_err(|_| SupervisorError::FleetAllocation("invalid MemTotal value".to_string()))?;
            if fields.next() != Some("kB") {
                return Err(SupervisorError::FleetAllocation(
                    "unexpected MemTotal unit".to_string(),
                ));
            }
            let mib = kib / 1024;
            if mib == 0 {
                return Err(SupervisorError::FleetAllocation(
                    "measured host memory is zero".to_string(),
                ));
            }
            return Ok(mib);
        }
    }
    Err(SupervisorError::FleetAllocation(
        "MemTotal is missing from /proc/meminfo".to_string(),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(target_os = "linux")]
    #[test]
    fn linux_meminfo_parser_is_bounded_to_memtotal_kib() {
        assert_eq!(
            parse_linux_meminfo("MemTotal:       16777216 kB\nMemFree: 1 kB\n")
                .expect("memory"),
            16_384
        );
        assert!(parse_linux_meminfo("MemFree: 1 kB\n").is_err());
        assert!(parse_linux_meminfo("MemTotal: 10 MB\n").is_err());
    }

    #[test]
    fn policy_rejects_zero_soft_axes() {
        assert!(HostCapacityPolicyV1 {
            max_concurrent_turns: 0,
            max_tool_processes: 1,
            turn_queue_slots: 1,
            memory_reserve_mib: 0,
        }
        .validate()
        .is_err());
    }
}
