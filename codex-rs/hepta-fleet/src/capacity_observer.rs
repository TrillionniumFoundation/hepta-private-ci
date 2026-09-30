//! Pressure-aware capacity observation for the selected local supervisor host.
//!
//! CPU parallelism and currently available memory are read from the operating
//! system. Logical queue/process ceilings remain explicit policy fields; an OS
//! probe never invents accelerator authority or a global fleet view.

use std::path::Path;
#[cfg(target_os = "macos")]
use std::process::Command;

use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::HostObservation;
use crate::MAX_RESOURCE_QUANTITY;
use crate::ResourceVectorV1;

pub const LOCAL_CAPACITY_SOURCE_ID: &str = "runtime.fleet.local-os-capacity.v1";
pub const DEFAULT_CAPACITY_TTL_MS: u64 = 30_000;
const MIN_CAPACITY_TTL_MS: u64 = 1_000;
const MAX_CAPACITY_TTL_MS: u64 = 300_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HostPressureObservationV1 {
    pub logical_cpu_count: u64,
    pub memory_total_bytes: u64,
    pub memory_available_bytes: u64,
    pub memory_pressure_basis_points: u16,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalCapacityObservationV1 {
    pub host: HostObservation,
    pub pressure: HostPressureObservationV1,
    pub source_id: &'static str,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalCapacityObserverConfig {
    pub host_id: String,
    pub failure_domain_id: String,
    pub generation: u64,
    pub ttl_ms: u64,
    pub cpu_reserve_millis: u64,
    pub memory_reserve_bytes: u64,
    pub configured_accelerator_millis: u64,
    pub logical_capacity: ResourceVectorV1,
}

impl LocalCapacityObserverConfig {
    pub fn for_local_supervisor(
        fleet_root: &Path,
        generation: u64,
    ) -> Result<Self, LocalCapacityObserverError> {
        if !fleet_root.is_absolute() {
            return Err(LocalCapacityObserverError::InvalidConfig(
                "fleet root must be absolute".to_string(),
            ));
        }
        let digest = Sha256::digest(fleet_root.as_os_str().as_encoded_bytes());
        let host_id = format!("local-host-{}", hex_prefix(&digest, 12));
        let logical_cpu_count = logical_cpu_count()?;
        let logical_capacity = ResourceVectorV1::logical(
            logical_cpu_count,
            /*memory_bytes*/ 0,
            logical_cpu_count.saturating_mul(4).max(1),
            4_096,
        );
        Ok(Self {
            host_id,
            failure_domain_id: "local-supervisor".to_string(),
            generation,
            ttl_ms: DEFAULT_CAPACITY_TTL_MS,
            cpu_reserve_millis: 0,
            memory_reserve_bytes: 128 * 1024 * 1024,
            configured_accelerator_millis: 0,
            logical_capacity,
        })
    }

    fn validate(&self) -> Result<(), LocalCapacityObserverError> {
        validate_identity(&self.host_id, "host")?;
        validate_identity(&self.failure_domain_id, "failure domain")?;
        if self.generation == 0
            || !(MIN_CAPACITY_TTL_MS..=MAX_CAPACITY_TTL_MS).contains(&self.ttl_ms)
            || self.configured_accelerator_millis > MAX_RESOURCE_QUANTITY
            || self.logical_capacity.cpu_millis != 0
            || self.logical_capacity.accelerator_millis != 0
            || self.logical_capacity.concurrent_turns == 0
            || self.logical_capacity.tool_processes == 0
            || self.logical_capacity.turn_queue_slots == 0
        {
            return Err(LocalCapacityObserverError::InvalidConfig(
                "invalid local capacity profile".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct LocalCapacityObserver {
    config: LocalCapacityObserverConfig,
}

impl LocalCapacityObserver {
    pub fn new(config: LocalCapacityObserverConfig) -> Result<Self, LocalCapacityObserverError> {
        config.validate()?;
        Ok(Self { config })
    }

    pub fn config(&self) -> &LocalCapacityObserverConfig {
        &self.config
    }

    pub fn observe(
        &self,
        now_ms: u64,
    ) -> Result<LocalCapacityObservationV1, LocalCapacityObserverError> {
        let logical_cpu_count = logical_cpu_count()?;
        let cpu_millis = logical_cpu_count
            .checked_mul(1_000)
            .ok_or(LocalCapacityObserverError::Arithmetic)?
            .saturating_sub(self.config.cpu_reserve_millis);
        let (memory_total_bytes, memory_available_bytes) = physical_memory()?;
        let allocatable_memory = memory_available_bytes
            .saturating_sub(self.config.memory_reserve_bytes)
            .min(MAX_RESOURCE_QUANTITY);
        if cpu_millis == 0 || allocatable_memory == 0 {
            return Err(LocalCapacityObserverError::CapacityUnavailable);
        }
        let valid_until_ms = now_ms
            .checked_add(self.config.ttl_ms)
            .ok_or(LocalCapacityObserverError::Arithmetic)?;
        let pressure = memory_pressure_basis_points(memory_total_bytes, memory_available_bytes)?;
        let host = HostObservation {
            host_id: self.config.host_id.clone(),
            failure_domain_id: self.config.failure_domain_id.clone(),
            generation: self.config.generation,
            observed_at_ms: now_ms,
            valid_until_ms,
            capacity: ResourceVectorV1 {
                cpu_millis,
                memory_bytes: allocatable_memory,
                accelerator_millis: self.config.configured_accelerator_millis,
                concurrent_turns: self.config.logical_capacity.concurrent_turns,
                tool_processes: self.config.logical_capacity.tool_processes,
                turn_queue_slots: self.config.logical_capacity.turn_queue_slots,
            },
        };
        host.capacity
            .validate_nonzero()
            .map_err(|error| LocalCapacityObserverError::InvalidConfig(error.to_string()))?;
        Ok(LocalCapacityObservationV1 {
            host,
            pressure: HostPressureObservationV1 {
                logical_cpu_count,
                memory_total_bytes,
                memory_available_bytes,
                memory_pressure_basis_points: pressure,
            },
            source_id: LOCAL_CAPACITY_SOURCE_ID,
        })
    }
}

impl crate::DurableFleetStore {
    pub async fn next_host_generation(
        &self,
        host_id: &str,
    ) -> Result<u64, crate::DurableFleetError> {
        validate_identity(host_id, "host")
            .map_err(|error| crate::DurableFleetError::Invalid(error.to_string()))?;
        let current: Option<i64> =
            sqlx::query_scalar("SELECT generation FROM fleet_hosts WHERE host_id = ?")
                .bind(host_id)
                .fetch_optional(&self.pool)
                .await
                .map_err(crate::durable_schema::sqlx_error)?;
        current
            .map(crate::durable_rows::to_u64)
            .transpose()?
            .unwrap_or(0)
            .checked_add(1)
            .ok_or_else(|| {
                crate::DurableFleetError::Invalid("host generation overflow".to_string())
            })
    }

    pub async fn observe_local_capacity(
        &self,
        observer: &LocalCapacityObserver,
    ) -> Result<
        (LocalCapacityObservationV1, crate::FleetOperationReceiptV1),
        crate::DurableFleetError,
    > {
        let observed = observer
            .observe(self.owner_now_ms()?)
            .map_err(|error| crate::DurableFleetError::Unavailable(error.to_string()))?;
        let receipt = self
            .observe_host(&observed.host, observed.source_id)
            .await?;
        Ok((observed, receipt))
    }
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum LocalCapacityObserverError {
    #[error("invalid local capacity observer configuration: {0}")]
    InvalidConfig(String),
    #[error("local host capacity is unavailable")]
    CapacityUnavailable,
    #[error("local capacity arithmetic overflowed")]
    Arithmetic,
    #[error("local capacity observation failed: {0}")]
    Observation(String),
}

fn logical_cpu_count() -> Result<u64, LocalCapacityObserverError> {
    let value = std::thread::available_parallelism()
        .map_err(|error| LocalCapacityObserverError::Observation(error.to_string()))?
        .get();
    u64::try_from(value).map_err(|_| LocalCapacityObserverError::Arithmetic)
}

#[cfg(target_os = "linux")]
fn physical_memory() -> Result<(u64, u64), LocalCapacityObserverError> {
    parse_linux_meminfo(
        &std::fs::read_to_string("/proc/meminfo")
            .map_err(|error| LocalCapacityObserverError::Observation(error.to_string()))?,
    )
}

#[cfg(target_os = "macos")]
fn physical_memory() -> Result<(u64, u64), LocalCapacityObserverError> {
    let total = command_u64("/usr/sbin/sysctl", &["-n", "hw.memsize"])?;
    let output = Command::new("/usr/bin/vm_stat")
        .output()
        .map_err(|error| LocalCapacityObserverError::Observation(error.to_string()))?;
    if !output.status.success() {
        return Err(LocalCapacityObserverError::Observation(
            "vm_stat failed".to_string(),
        ));
    }
    let text = String::from_utf8(output.stdout)
        .map_err(|error| LocalCapacityObserverError::Observation(error.to_string()))?;
    let available = parse_macos_vm_stat(&text)?;
    Ok((total, available.min(total)))
}

#[cfg(not(any(target_os = "linux", target_os = "macos")))]
fn physical_memory() -> Result<(u64, u64), LocalCapacityObserverError> {
    Err(LocalCapacityObserverError::Observation(
        "physical memory observation is unsupported on this host".to_string(),
    ))
}

#[cfg(target_os = "linux")]
fn parse_linux_meminfo(text: &str) -> Result<(u64, u64), LocalCapacityObserverError> {
    let mut total_kib = None;
    let mut available_kib = None;
    for line in text.lines() {
        let mut fields = line.split_whitespace();
        match fields.next() {
            Some("MemTotal:") => total_kib = fields.next().and_then(|value| value.parse().ok()),
            Some("MemAvailable:") => {
                available_kib = fields.next().and_then(|value| value.parse().ok())
            }
            _ => {}
        }
    }
    let total_kib: u64 = total_kib.ok_or_else(|| {
        LocalCapacityObserverError::Observation("MemTotal is missing".to_string())
    })?;
    let available_kib: u64 = available_kib.ok_or_else(|| {
        LocalCapacityObserverError::Observation("MemAvailable is missing".to_string())
    })?;
    Ok((
        total_kib
            .checked_mul(1_024)
            .ok_or(LocalCapacityObserverError::Arithmetic)?,
        available_kib
            .checked_mul(1_024)
            .ok_or(LocalCapacityObserverError::Arithmetic)?,
    ))
}

#[cfg(target_os = "macos")]
fn parse_macos_vm_stat(text: &str) -> Result<u64, LocalCapacityObserverError> {
    let page_size = text
        .lines()
        .next()
        .and_then(|line| line.split("page size of ").nth(1))
        .and_then(|rest| rest.split_whitespace().next())
        .and_then(|value| value.parse::<u64>().ok())
        .ok_or_else(|| {
            LocalCapacityObserverError::Observation("vm_stat page size is missing".to_string())
        })?;
    let mut pages = 0_u64;
    for label in [
        "Pages free:",
        "Pages inactive:",
        "Pages speculative:",
        "Pages purgeable:",
    ] {
        let value = text
            .lines()
            .find_map(|line| {
                line.strip_prefix(label)
                    .and_then(|value| value.trim().trim_end_matches('.').parse::<u64>().ok())
            })
            .unwrap_or(0);
        pages = pages
            .checked_add(value)
            .ok_or(LocalCapacityObserverError::Arithmetic)?;
    }
    pages
        .checked_mul(page_size)
        .ok_or(LocalCapacityObserverError::Arithmetic)
}

#[cfg(target_os = "macos")]
fn command_u64(program: &str, arguments: &[&str]) -> Result<u64, LocalCapacityObserverError> {
    let output = Command::new(program)
        .args(arguments)
        .output()
        .map_err(|error| LocalCapacityObserverError::Observation(error.to_string()))?;
    if !output.status.success() {
        return Err(LocalCapacityObserverError::Observation(format!(
            "{program} failed"
        )));
    }
    String::from_utf8(output.stdout)
        .map_err(|error| LocalCapacityObserverError::Observation(error.to_string()))?
        .trim()
        .parse()
        .map_err(|error: std::num::ParseIntError| {
            LocalCapacityObserverError::Observation(error.to_string())
        })
}

fn memory_pressure_basis_points(
    total: u64,
    available: u64,
) -> Result<u16, LocalCapacityObserverError> {
    if total == 0 || available > total {
        return Err(LocalCapacityObserverError::Observation(
            "invalid physical memory observation".to_string(),
        ));
    }
    let used = total - available;
    let basis_points = u128::from(used)
        .checked_mul(10_000)
        .ok_or(LocalCapacityObserverError::Arithmetic)?
        / u128::from(total);
    u16::try_from(basis_points).map_err(|_| LocalCapacityObserverError::Arithmetic)
}

fn validate_identity(value: &str, field: &str) -> Result<(), LocalCapacityObserverError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(LocalCapacityObserverError::InvalidConfig(format!(
            "invalid {field} identity"
        )));
    }
    Ok(())
}

fn hex_prefix(bytes: &[u8], byte_count: usize) -> String {
    use std::fmt::Write as _;

    let mut output = String::with_capacity(byte_count * 2);
    for byte in bytes.iter().take(byte_count) {
        let _ = write!(&mut output, "{byte:02x}");
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(target_os = "linux")]
    #[test]
    fn linux_memory_parser_uses_available_not_total() {
        assert_eq!(
            parse_linux_meminfo("MemTotal: 1024 kB\nMemAvailable: 256 kB\n"),
            Ok((1024 * 1024, 256 * 1024))
        );
    }

    #[test]
    fn pressure_is_bounded() {
        assert_eq!(memory_pressure_basis_points(100, 25), Ok(7_500));
    }
}
