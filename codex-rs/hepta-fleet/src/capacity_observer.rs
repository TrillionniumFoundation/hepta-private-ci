use std::fs;
use std::num::NonZeroUsize;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use thiserror::Error;

use crate::FleetAllocationStoreError;
use crate::FleetCapacityObservationSourceV1;
use crate::FleetHostObservationV1;
use crate::FleetResourceVectorV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalCapacityPolicyV1 {
    pub maximum_concurrent_turns: u64,
    pub maximum_tool_processes: u64,
    pub maximum_turn_queue_slots: u64,
    pub memory_reserve_mib: u64,
    pub observation_ttl_ms: u64,
}

impl LocalCapacityPolicyV1 {
    pub fn validate(&self) -> Result<(), LocalCapacityObserverError> {
        if self.maximum_concurrent_turns == 0
            || self.maximum_tool_processes == 0
            || self.maximum_turn_queue_slots == 0
            || self.observation_ttl_ms == 0
            || self.observation_ttl_ms > 300_000
        {
            return Err(LocalCapacityObserverError::InvalidPolicy);
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct LocalCapacityObserverV1 {
    host_id: String,
    failure_domain_id: String,
    policy: LocalCapacityPolicyV1,
}

impl LocalCapacityObserverV1 {
    pub fn new(
        host_id: String,
        failure_domain_id: String,
        policy: LocalCapacityPolicyV1,
    ) -> Result<Self, LocalCapacityObserverError> {
        policy.validate()?;
        if !identifier(&host_id) || !identifier(&failure_domain_id) {
            return Err(LocalCapacityObserverError::InvalidIdentity);
        }
        Ok(Self {
            host_id,
            failure_domain_id,
            policy,
        })
    }

    pub fn observe(
        &self,
        generation: u64,
        revision: u64,
    ) -> Result<FleetHostObservationV1, LocalCapacityObserverError> {
        if generation == 0 || revision == 0 {
            return Err(LocalCapacityObserverError::InvalidGeneration);
        }
        let now_unix_ms = unix_ms_now()?;
        let memory_mib = local_available_memory_mib()?
            .checked_sub(self.policy.memory_reserve_mib)
            .ok_or(LocalCapacityObserverError::InsufficientMemory)?;
        let parallelism = std::thread::available_parallelism()
            .unwrap_or(NonZeroUsize::MIN)
            .get() as u64;
        let concurrent_turns = parallelism.min(self.policy.maximum_concurrent_turns).max(1);
        let valid_until_unix_ms = now_unix_ms
            .checked_add(self.policy.observation_ttl_ms)
            .ok_or(LocalCapacityObserverError::Clock)?;
        FleetHostObservationV1::new(
            self.host_id.clone(),
            self.failure_domain_id.clone(),
            generation,
            revision,
            now_unix_ms,
            valid_until_unix_ms,
            FleetCapacityObservationSourceV1::LocalKernel,
            FleetResourceVectorV1 {
                concurrent_turns,
                memory_mib,
                tool_processes: self.policy.maximum_tool_processes,
                turn_queue_slots: self.policy.maximum_turn_queue_slots,
            },
        )
        .map_err(LocalCapacityObserverError::Store)
    }
}

#[cfg(target_os = "linux")]
fn local_available_memory_mib() -> Result<u64, LocalCapacityObserverError> {
    let source = fs::read_to_string("/proc/meminfo")?;
    let line = source
        .lines()
        .find(|line| line.starts_with("MemAvailable:"))
        .ok_or(LocalCapacityObserverError::Unavailable)?;
    let kib = line
        .split_ascii_whitespace()
        .nth(1)
        .ok_or(LocalCapacityObserverError::Unavailable)?
        .parse::<u64>()
        .map_err(|_| LocalCapacityObserverError::Unavailable)?;
    Ok(kib / 1024)
}

#[cfg(not(target_os = "linux"))]
fn local_available_memory_mib() -> Result<u64, LocalCapacityObserverError> {
    Err(LocalCapacityObserverError::UnsupportedHost)
}

fn unix_ms_now() -> Result<u64, LocalCapacityObserverError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| LocalCapacityObserverError::Clock)?
        .as_millis();
    u64::try_from(millis).map_err(|_| LocalCapacityObserverError::Clock)
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
}

#[derive(Debug, Error)]
pub enum LocalCapacityObserverError {
    #[error("invalid local capacity policy")]
    InvalidPolicy,
    #[error("invalid local capacity observer identity")]
    InvalidIdentity,
    #[error("invalid local capacity observer generation")]
    InvalidGeneration,
    #[error("local capacity observer unavailable")]
    Unavailable,
    #[error("local host is unsupported by the physical capacity observer")]
    UnsupportedHost,
    #[error("local available memory is below the reserved floor")]
    InsufficientMemory,
    #[error("local capacity observer clock unavailable")]
    Clock,
    #[error("local capacity observer I/O: {0}")]
    Io(#[from] std::io::Error),
    #[error("fleet allocation store: {0}")]
    Store(#[from] FleetAllocationStoreError),
}
