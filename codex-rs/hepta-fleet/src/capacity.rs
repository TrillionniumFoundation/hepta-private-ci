use std::path::Path;
use std::process::Command;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::FleetResourceVectorV1;

pub const FLEET_CAPACITY_OBSERVATION_SCHEMA_VERSION: u32 = 1;
pub const DEFAULT_CAPACITY_OBSERVATION_TTL_MS: u64 = 60_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LocalCapacityPolicyV1 {
    pub memory_reserve_mib: u64,
    pub max_concurrent_turns: u64,
    pub max_tool_processes: u64,
    pub max_turn_queue_slots: u64,
    pub observation_ttl_ms: u64,
}

impl Default for LocalCapacityPolicyV1 {
    fn default() -> Self {
        Self {
            memory_reserve_mib: 512,
            max_concurrent_turns: 256,
            max_tool_processes: 1_024,
            max_turn_queue_slots: 16_384,
            observation_ttl_ms: DEFAULT_CAPACITY_OBSERVATION_TTL_MS,
        }
    }
}

impl LocalCapacityPolicyV1 {
    fn validate(self) -> Result<Self, CapacityObservationError> {
        if self.max_concurrent_turns == 0
            || self.max_tool_processes == 0
            || self.max_turn_queue_slots == 0
            || self.observation_ttl_ms == 0
        {
            return Err(CapacityObservationError::InvalidPolicy);
        }
        Ok(self)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObservedFleetCapacityV1 {
    pub schema_version: u32,
    pub host_id: String,
    pub failure_domain_id: String,
    pub host_generation: u64,
    pub observation_revision: u64,
    pub observed_at_ms: u64,
    pub valid_until_ms: u64,
    pub capacity: FleetResourceVectorV1,
    pub observation_digest: Sha256Digest,
}

impl ObservedFleetCapacityV1 {
    pub fn validate(&self, now_ms: u64) -> Result<(), CapacityObservationError> {
        validate_identifier(&self.host_id)?;
        validate_identifier(&self.failure_domain_id)?;
        if self.schema_version != FLEET_CAPACITY_OBSERVATION_SCHEMA_VERSION
            || self.host_generation == 0
            || self.observation_revision == 0
            || self.observed_at_ms > now_ms
            || self.valid_until_ms <= now_ms
            || self.valid_until_ms <= self.observed_at_ms
            || self.capacity.is_zero()
        {
            return Err(CapacityObservationError::InvalidObservation);
        }
        let expected = observation_digest(
            &self.host_id,
            &self.failure_domain_id,
            self.host_generation,
            self.observation_revision,
            self.observed_at_ms,
            self.valid_until_ms,
            self.capacity,
        )?;
        if expected != self.observation_digest {
            return Err(CapacityObservationError::DigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CapacityObservationRequestV1 {
    pub host_id: String,
    pub failure_domain_id: String,
    pub host_generation: u64,
    pub observation_revision: u64,
    pub now_ms: u64,
}

pub trait FleetCapacityObserver: Send {
    fn observe(
        &mut self,
        request: &CapacityObservationRequestV1,
    ) -> Result<ObservedFleetCapacityV1, CapacityObservationError>;
}

#[derive(Clone, Debug)]
pub struct LocalSystemCapacityObserver {
    policy: LocalCapacityPolicyV1,
}

impl LocalSystemCapacityObserver {
    pub fn new(policy: LocalCapacityPolicyV1) -> Result<Self, CapacityObservationError> {
        Ok(Self {
            policy: policy.validate()?,
        })
    }

    fn physical_memory_mib(&self) -> Result<u64, CapacityObservationError> {
        #[cfg(target_os = "linux")]
        {
            let text = std::fs::read_to_string(Path::new("/proc/meminfo"))
                .map_err(CapacityObservationError::Io)?;
            return parse_linux_meminfo_mib(&text);
        }
        #[cfg(target_os = "macos")]
        {
            let output = Command::new("/usr/sbin/sysctl")
                .args(["-n", "hw.memsize"])
                .output()
                .map_err(CapacityObservationError::Io)?;
            if !output.status.success() {
                return Err(CapacityObservationError::PlatformUnavailable);
            }
            let bytes: u64 = std::str::from_utf8(&output.stdout)
                .map_err(|_| CapacityObservationError::PlatformUnavailable)?
                .trim()
                .parse()
                .map_err(|_| CapacityObservationError::PlatformUnavailable)?;
            return Ok(bytes / (1024 * 1024));
        }
        #[cfg(not(any(target_os = "linux", target_os = "macos")))]
        {
            let _ = Path::new("/");
            let _ = Command::new("");
            Err(CapacityObservationError::PlatformUnavailable)
        }
    }
}

impl FleetCapacityObserver for LocalSystemCapacityObserver {
    fn observe(
        &mut self,
        request: &CapacityObservationRequestV1,
    ) -> Result<ObservedFleetCapacityV1, CapacityObservationError> {
        validate_identifier(&request.host_id)?;
        validate_identifier(&request.failure_domain_id)?;
        if request.host_generation == 0 || request.observation_revision == 0 {
            return Err(CapacityObservationError::InvalidObservation);
        }
        let cpu = u64::try_from(
            std::thread::available_parallelism()
                .map_err(CapacityObservationError::Io)?
                .get(),
        )
        .map_err(|_| CapacityObservationError::PlatformUnavailable)?;
        let physical_memory_mib = self.physical_memory_mib()?;
        let memory_mib = physical_memory_mib
            .checked_sub(self.policy.memory_reserve_mib)
            .ok_or(CapacityObservationError::InsufficientPhysicalCapacity)?;
        let capacity = FleetResourceVectorV1 {
            concurrent_turns: cpu.min(self.policy.max_concurrent_turns).max(1),
            memory_mib,
            tool_processes: self.policy.max_tool_processes,
            turn_queue_slots: self.policy.max_turn_queue_slots,
        };
        if capacity.is_zero() || capacity.memory_mib == 0 {
            return Err(CapacityObservationError::InsufficientPhysicalCapacity);
        }
        let valid_until_ms = request
            .now_ms
            .checked_add(self.policy.observation_ttl_ms)
            .ok_or(CapacityObservationError::InvalidObservation)?;
        let observation_digest = observation_digest(
            &request.host_id,
            &request.failure_domain_id,
            request.host_generation,
            request.observation_revision,
            request.now_ms,
            valid_until_ms,
            capacity,
        )?;
        Ok(ObservedFleetCapacityV1 {
            schema_version: FLEET_CAPACITY_OBSERVATION_SCHEMA_VERSION,
            host_id: request.host_id.clone(),
            failure_domain_id: request.failure_domain_id.clone(),
            host_generation: request.host_generation,
            observation_revision: request.observation_revision,
            observed_at_ms: request.now_ms,
            valid_until_ms,
            capacity,
            observation_digest,
        })
    }
}

#[derive(Debug, Error)]
pub enum CapacityObservationError {
    #[error("invalid fleet capacity policy")]
    InvalidPolicy,
    #[error("invalid fleet capacity observation")]
    InvalidObservation,
    #[error("fleet capacity observation digest mismatch")]
    DigestMismatch,
    #[error("host capacity observer is unavailable on this platform")]
    PlatformUnavailable,
    #[error("host does not have capacity after the configured reserve")]
    InsufficientPhysicalCapacity,
    #[error("capacity observation I/O failed: {0}")]
    Io(#[source] std::io::Error),
    #[error("capacity observation encoding failed: {0}")]
    Encode(#[from] serde_json::Error),
}

fn validate_identifier(value: &str) -> Result<(), CapacityObservationError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
    {
        return Err(CapacityObservationError::InvalidObservation);
    }
    Ok(())
}

fn observation_digest(
    host_id: &str,
    failure_domain_id: &str,
    host_generation: u64,
    observation_revision: u64,
    observed_at_ms: u64,
    valid_until_ms: u64,
    capacity: FleetResourceVectorV1,
) -> Result<Sha256Digest, CapacityObservationError> {
    let canonical = serde_json::to_vec(&(
        "hepta.runtime-fleet.capacity-observation.v1",
        host_id,
        failure_domain_id,
        host_generation,
        observation_revision,
        observed_at_ms,
        valid_until_ms,
        capacity,
    ))?;
    Ok(Sha256Digest::for_bytes(&canonical))
}

#[cfg(target_os = "linux")]
fn parse_linux_meminfo_mib(text: &str) -> Result<u64, CapacityObservationError> {
    let mut total = None;
    let mut available = None;
    for line in text.lines() {
        let mut parts = line.split_whitespace();
        let Some(key) = parts.next() else {
            continue;
        };
        let Some(raw) = parts.next() else {
            continue;
        };
        let value: u64 = raw
            .parse()
            .map_err(|_| CapacityObservationError::PlatformUnavailable)?;
        match key {
            "MemTotal:" => total = Some(value),
            "MemAvailable:" => available = Some(value),
            _ => {}
        }
    }
    let kib = available.or(total).ok_or(CapacityObservationError::PlatformUnavailable)?;
    Ok(kib / 1024)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(target_os = "linux")]
    #[test]
    fn linux_memory_parser_prefers_available_capacity() {
        let text = "MemTotal:       8388608 kB\nMemAvailable:   4194304 kB\n";
        assert_eq!(parse_linux_meminfo_mib(text).expect("parse"), 4096);
    }

    #[test]
    fn observation_digest_binds_every_capacity_axis() {
        let base = FleetResourceVectorV1 {
            concurrent_turns: 2,
            memory_mib: 4096,
            tool_processes: 8,
            turn_queue_slots: 64,
        };
        let first = observation_digest("host-a", "rack-a", 1, 1, 10, 20, base).expect("digest");
        let mut changed = base;
        changed.turn_queue_slots += 1;
        let second =
            observation_digest("host-a", "rack-a", 1, 1, 10, 20, changed).expect("digest");
        assert_ne!(first, second);
    }
}
