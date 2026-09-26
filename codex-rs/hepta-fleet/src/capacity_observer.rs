//! Trusted, bounded capacity observations for the supervisor-owned fleet runtime.
//!
//! The Linux implementation reads physical CPU availability, MemAvailable and
//! the kernel memory-pressure signal. Callers provide stable host identity and
//! generation through immutable supervisor configuration; allocation requests
//! cannot manufacture capacity.

use crate::ResourceVectorV1;
use crate::lease_ledger::HostObservation;
use serde::Deserialize;
use serde::Serialize;
use std::fmt;
use std::path::Path;
use std::path::PathBuf;

pub const CAPACITY_OBSERVATION_SCHEMA_VERSION: u32 = 1;
pub const MAX_CAPACITY_OBSERVATION_TTL_MS: u64 = 300_000;
pub const MAX_MEMORY_PRESSURE_BASIS_POINTS: u16 = 10_000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TrustedCapacityObservationV1 {
    pub schema_version: u32,
    pub observer_id: String,
    pub host_id: String,
    pub failure_domain_id: String,
    pub host_generation: u64,
    pub observed_at_ms: u64,
    pub valid_until_ms: u64,
    pub memory_pressure_basis_points: u16,
    pub capacity: ResourceVectorV1,
}

impl TrustedCapacityObservationV1 {
    pub fn validate(&self) -> Result<(), CapacityObservationError> {
        if self.schema_version != CAPACITY_OBSERVATION_SCHEMA_VERSION {
            return Err(CapacityObservationError::UnsupportedSchema(
                self.schema_version,
            ));
        }
        for value in [
            self.observer_id.as_str(),
            self.host_id.as_str(),
            self.failure_domain_id.as_str(),
        ] {
            if !valid_identifier(value) {
                return Err(CapacityObservationError::InvalidIdentity);
            }
        }
        if self.host_generation == 0
            || self.observed_at_ms >= self.valid_until_ms
            || self.valid_until_ms - self.observed_at_ms > MAX_CAPACITY_OBSERVATION_TTL_MS
            || self.memory_pressure_basis_points > MAX_MEMORY_PRESSURE_BASIS_POINTS
            || self.capacity.is_empty()
        {
            return Err(CapacityObservationError::InvalidObservation);
        }
        self.capacity
            .validate()
            .map_err(|_| CapacityObservationError::InvalidObservation)
    }

    pub fn host_observation(&self) -> Result<HostObservation, CapacityObservationError> {
        self.validate()?;
        Ok(HostObservation {
            host_id: self.host_id.clone(),
            failure_domain_id: self.failure_domain_id.clone(),
            generation: self.host_generation,
            observed_at_ms: self.observed_at_ms,
            valid_until_ms: self.valid_until_ms,
            capacity: self.capacity,
        })
    }
}

pub trait FleetCapacityObserverV1: fmt::Debug + Send + Sync {
    fn observe(
        &self,
        now_ms: u64,
    ) -> Result<TrustedCapacityObservationV1, CapacityObservationError>;
}

#[derive(Clone, Debug)]
pub struct LinuxProcfsCapacityObserverV1 {
    host_id: String,
    failure_domain_id: String,
    host_generation: u64,
    observation_ttl_ms: u64,
    maximum_memory_pressure_basis_points: u16,
    meminfo_path: PathBuf,
    memory_pressure_path: PathBuf,
}

impl LinuxProcfsCapacityObserverV1 {
    pub fn for_current_host(
        host_id: String,
        failure_domain_id: String,
        host_generation: u64,
        observation_ttl_ms: u64,
        maximum_memory_pressure_basis_points: u16,
    ) -> Result<Self, CapacityObservationError> {
        Self::with_paths(
            host_id,
            failure_domain_id,
            host_generation,
            observation_ttl_ms,
            maximum_memory_pressure_basis_points,
            "/proc/meminfo",
            "/proc/pressure/memory",
        )
    }

    pub fn with_paths(
        host_id: String,
        failure_domain_id: String,
        host_generation: u64,
        observation_ttl_ms: u64,
        maximum_memory_pressure_basis_points: u16,
        meminfo_path: impl Into<PathBuf>,
        memory_pressure_path: impl Into<PathBuf>,
    ) -> Result<Self, CapacityObservationError> {
        if !valid_identifier(&host_id)
            || !valid_identifier(&failure_domain_id)
            || host_generation == 0
            || observation_ttl_ms == 0
            || observation_ttl_ms > MAX_CAPACITY_OBSERVATION_TTL_MS
            || maximum_memory_pressure_basis_points > MAX_MEMORY_PRESSURE_BASIS_POINTS
        {
            return Err(CapacityObservationError::InvalidConfiguration);
        }
        Ok(Self {
            host_id,
            failure_domain_id,
            host_generation,
            observation_ttl_ms,
            maximum_memory_pressure_basis_points,
            meminfo_path: meminfo_path.into(),
            memory_pressure_path: memory_pressure_path.into(),
        })
    }
}

impl FleetCapacityObserverV1 for LinuxProcfsCapacityObserverV1 {
    fn observe(
        &self,
        now_ms: u64,
    ) -> Result<TrustedCapacityObservationV1, CapacityObservationError> {
        #[cfg(not(target_os = "linux"))]
        {
            let _ = now_ms;
            return Err(CapacityObservationError::UnsupportedPlatform);
        }
        #[cfg(target_os = "linux")]
        {
            let cpu_millis = u64::try_from(
                std::thread::available_parallelism()
                    .map_err(CapacityObservationError::Io)?
                    .get(),
            )
            .map_err(|_| CapacityObservationError::ArithmeticOverflow)?
            .checked_mul(1_000)
            .ok_or(CapacityObservationError::ArithmeticOverflow)?;
            let memory_bytes = read_available_memory_bytes(&self.meminfo_path)?;
            let memory_pressure_basis_points =
                read_memory_pressure_basis_points(&self.memory_pressure_path)?;
            if memory_pressure_basis_points > self.maximum_memory_pressure_basis_points {
                return Err(CapacityObservationError::PressureLimitExceeded {
                    observed: memory_pressure_basis_points,
                    maximum: self.maximum_memory_pressure_basis_points,
                });
            }
            let valid_until_ms = now_ms
                .checked_add(self.observation_ttl_ms)
                .ok_or(CapacityObservationError::ArithmeticOverflow)?;
            let observation = TrustedCapacityObservationV1 {
                schema_version: CAPACITY_OBSERVATION_SCHEMA_VERSION,
                observer_id: "linux.procfs.v1".to_string(),
                host_id: self.host_id.clone(),
                failure_domain_id: self.failure_domain_id.clone(),
                host_generation: self.host_generation,
                observed_at_ms: now_ms,
                valid_until_ms,
                memory_pressure_basis_points,
                capacity: ResourceVectorV1::physical(cpu_millis, memory_bytes, 0),
            };
            observation.validate()?;
            Ok(observation)
        }
    }
}

fn read_available_memory_bytes(path: &Path) -> Result<u64, CapacityObservationError> {
    let content = std::fs::read_to_string(path).map_err(CapacityObservationError::Io)?;
    let line = content
        .lines()
        .find(|line| line.starts_with("MemAvailable:"))
        .ok_or(CapacityObservationError::MissingMemAvailable)?;
    let mut fields = line.split_ascii_whitespace();
    if fields.next() != Some("MemAvailable:") {
        return Err(CapacityObservationError::InvalidMeminfo);
    }
    let kibibytes = fields
        .next()
        .ok_or(CapacityObservationError::InvalidMeminfo)?
        .parse::<u64>()
        .map_err(|_| CapacityObservationError::InvalidMeminfo)?;
    if fields.next() != Some("kB") || fields.next().is_some() || kibibytes == 0 {
        return Err(CapacityObservationError::InvalidMeminfo);
    }
    kibibytes
        .checked_mul(1024)
        .ok_or(CapacityObservationError::ArithmeticOverflow)
}

fn read_memory_pressure_basis_points(path: &Path) -> Result<u16, CapacityObservationError> {
    let content = std::fs::read_to_string(path).map_err(CapacityObservationError::Io)?;
    let some = content
        .lines()
        .find(|line| line.starts_with("some "))
        .ok_or(CapacityObservationError::InvalidPressure)?;
    let value = some
        .split_ascii_whitespace()
        .find_map(|field| field.strip_prefix("avg10="))
        .ok_or(CapacityObservationError::InvalidPressure)?;
    parse_percent_basis_points(value)
}

fn parse_percent_basis_points(value: &str) -> Result<u16, CapacityObservationError> {
    let (whole, fractional) = value
        .split_once('.')
        .ok_or(CapacityObservationError::InvalidPressure)?;
    if whole.is_empty()
        || fractional.is_empty()
        || fractional.len() > 2
        || !whole.bytes().all(|byte| byte.is_ascii_digit())
        || !fractional.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(CapacityObservationError::InvalidPressure);
    }
    let whole = whole
        .parse::<u16>()
        .map_err(|_| CapacityObservationError::InvalidPressure)?;
    let mut fractional = fractional
        .parse::<u16>()
        .map_err(|_| CapacityObservationError::InvalidPressure)?;
    if value.split_once('.').map(|(_, value)| value.len()) == Some(1) {
        fractional = fractional
            .checked_mul(10)
            .ok_or(CapacityObservationError::InvalidPressure)?;
    }
    let basis_points = whole
        .checked_mul(100)
        .and_then(|value| value.checked_add(fractional))
        .ok_or(CapacityObservationError::InvalidPressure)?;
    if basis_points > MAX_MEMORY_PRESSURE_BASIS_POINTS {
        return Err(CapacityObservationError::InvalidPressure);
    }
    Ok(basis_points)
}

fn valid_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-/".contains(&byte))
}

#[derive(Debug)]
pub enum CapacityObservationError {
    UnsupportedSchema(u32),
    UnsupportedPlatform,
    InvalidConfiguration,
    InvalidIdentity,
    InvalidObservation,
    MissingMemAvailable,
    InvalidMeminfo,
    InvalidPressure,
    PressureLimitExceeded { observed: u16, maximum: u16 },
    ArithmeticOverflow,
    Io(std::io::Error),
}

impl fmt::Display for CapacityObservationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for CapacityObservationError {}

#[cfg(test)]
#[path = "capacity_observer_tests.rs"]
mod tests;
