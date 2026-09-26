//! Named product composition for the supervisor-owned fleet allocation state.
//!
//! This module is part of the existing `hepta-supervisord` process. It opens
//! the durable owner under the canonical fleet state root, refreshes physical
//! capacity from the selected host, and reconciles lease expiry. It never
//! starts a second fleet writer or treats an observation as allocation authority.

use codex_hepta_fleet::DurableFleetOwner;
use codex_hepta_fleet::LinuxProcfsCapacityObserverV1;
use codex_hepta_fleet::SystemFleetClock;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_paths::HeptaFleetRoot;
use sha2::Digest;
use sha2::Sha256;
use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio::time::MissedTickBehavior;
use tokio_util::sync::CancellationToken;

use crate::H7H89ProductionGrantVerifier;
use crate::SupervisorError;
use crate::run_supervisord;
use crate::run_supervisord_with_grant_verifier;

const CAPACITY_TTL_MS: u64 = 60_000;
const CAPACITY_REFRESH_INTERVAL: Duration = Duration::from_secs(20);
const MAX_MEMORY_PRESSURE_BASIS_POINTS: u16 = 5_000;
const HOST_ID_ENV: &str = "HEPTA_FLEET_HOST_ID";
const FAILURE_DOMAIN_ENV: &str = "HEPTA_FLEET_FAILURE_DOMAIN_ID";
const HOST_GENERATION_ENV: &str = "HEPTA_FLEET_HOST_GENERATION";

pub(crate) async fn run_supervisord_product(
    fleet_root: HeptaFleetRoot,
    cancellation: CancellationToken,
    verifier: Option<H7H89ProductionGrantVerifier>,
) -> Result<(), SupervisorError> {
    let registry = FleetRegistry::open_existing(fleet_root.clone())?;
    let state_root = registry.layout().state_root().to_path_buf();
    initialize_owner(&state_root)?;

    let identity = LocalFleetIdentityV1::discover().ok();
    if let Some(identity) = identity.as_ref() {
        let _ = refresh_capacity(&state_root, identity);
    }

    let maintenance_state_root = state_root.clone();
    let maintenance_identity = identity.clone();
    let maintenance_cancellation = cancellation.clone();
    let maintenance = tokio::spawn(async move {
        let mut interval = tokio::time::interval(CAPACITY_REFRESH_INTERVAL);
        interval.set_missed_tick_behavior(MissedTickBehavior::Skip);
        interval.tick().await;
        loop {
            tokio::select! {
                _ = maintenance_cancellation.cancelled() => return,
                _ = interval.tick() => {
                    let state_root = maintenance_state_root.clone();
                    let identity = maintenance_identity.clone();
                    let _ = tokio::task::spawn_blocking(move || {
                        initialize_owner(&state_root)?;
                        if let Some(identity) = identity.as_ref() {
                            let _ = refresh_capacity(&state_root, identity);
                        }
                        Ok::<(), SupervisorError>(())
                    }).await;
                }
            }
        }
    });

    let result = match verifier {
        Some(verifier) => {
            run_supervisord_with_grant_verifier(fleet_root, cancellation.clone(), verifier).await
        }
        None => run_supervisord(fleet_root, cancellation.clone()).await,
    };
    cancellation.cancel();
    let _ = maintenance.await;
    result
}

fn initialize_owner(state_root: &std::path::Path) -> Result<(), SupervisorError> {
    let clock = Arc::new(SystemFleetClock);
    let mut owner = DurableFleetOwner::open_supervisor_state_root(state_root, clock)
        .map_err(|error| SupervisorError::Invalid(format!("open runtime.fleet owner: {error}")))?;
    let now_ms = unix_ms()?;
    owner
        .reconcile_expired(&format!("supervisor-expiry-{now_ms}"))
        .map_err(|error| {
            SupervisorError::Invalid(format!("reconcile runtime.fleet expiry: {error}"))
        })?;
    Ok(())
}

fn refresh_capacity(
    state_root: &std::path::Path,
    identity: &LocalFleetIdentityV1,
) -> Result<(), SupervisorError> {
    let clock = Arc::new(SystemFleetClock);
    let mut owner = DurableFleetOwner::open_supervisor_state_root(state_root, clock)
        .map_err(|error| SupervisorError::Invalid(format!("open runtime.fleet owner: {error}")))?;
    let observer = LinuxProcfsCapacityObserverV1::for_current_host(
        identity.host_id.clone(),
        identity.failure_domain_id.clone(),
        identity.host_generation,
        CAPACITY_TTL_MS,
        MAX_MEMORY_PRESSURE_BASIS_POINTS,
    )
    .map_err(|error| {
        SupervisorError::Invalid(format!("configure runtime.fleet capacity observer: {error}"))
    })?;
    let now_ms = unix_ms()?;
    owner
        .refresh_capacity(&format!("supervisor-capacity-{now_ms}"), &observer)
        .map_err(|error| {
            SupervisorError::Invalid(format!("refresh runtime.fleet capacity: {error}"))
        })?;
    Ok(())
}

#[derive(Clone, Debug)]
struct LocalFleetIdentityV1 {
    host_id: String,
    failure_domain_id: String,
    host_generation: u64,
}

impl LocalFleetIdentityV1 {
    fn discover() -> Result<Self, SupervisorError> {
        let configured = (
            std::env::var(HOST_ID_ENV).ok(),
            std::env::var(FAILURE_DOMAIN_ENV).ok(),
            std::env::var(HOST_GENERATION_ENV).ok(),
        );
        match configured {
            (Some(host_id), Some(failure_domain_id), Some(generation)) => {
                let host_generation = generation.parse::<u64>().map_err(|error| {
                    SupervisorError::Invalid(format!(
                        "{HOST_GENERATION_ENV} is invalid: {error}"
                    ))
                })?;
                if host_generation == 0 {
                    return Err(SupervisorError::Invalid(format!(
                        "{HOST_GENERATION_ENV} must be non-zero"
                    )));
                }
                Ok(Self {
                    host_id,
                    failure_domain_id,
                    host_generation,
                })
            }
            (None, None, None) => Self::discover_linux(),
            _ => Err(SupervisorError::Invalid(format!(
                "{HOST_ID_ENV}, {FAILURE_DOMAIN_ENV}, and {HOST_GENERATION_ENV} must be configured together"
            ))),
        }
    }

    #[cfg(target_os = "linux")]
    fn discover_linux() -> Result<Self, SupervisorError> {
        let machine_id = read_bounded("/etc/machine-id", 4_096)?;
        let boot_id = read_bounded("/proc/sys/kernel/random/boot_id", 4_096)?;
        let machine_digest = Sha256::digest(machine_id.trim_ascii());
        let boot_digest = Sha256::digest(boot_id.trim_ascii());
        let host_id = format!("host-{}", hex_prefix(&machine_digest, 16));
        let failure_domain_id = format!("local-{}", hex_prefix(&machine_digest, 16));
        let mut generation_bytes = [0_u8; 8];
        generation_bytes.copy_from_slice(&boot_digest[..8]);
        let host_generation = u64::from_be_bytes(generation_bytes).max(1);
        Ok(Self {
            host_id,
            failure_domain_id,
            host_generation,
        })
    }

    #[cfg(not(target_os = "linux"))]
    fn discover_linux() -> Result<Self, SupervisorError> {
        Err(SupervisorError::Invalid(
            "automatic runtime.fleet host discovery is currently implemented only for Linux"
                .to_string(),
        ))
    }
}

fn read_bounded(path: &str, maximum: usize) -> Result<Vec<u8>, SupervisorError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err(SupervisorError::Invalid(format!(
            "runtime.fleet identity source is not a regular file: {path}"
        )));
    }
    if metadata.len() > maximum as u64 {
        return Err(SupervisorError::Invalid(format!(
            "runtime.fleet identity source exceeds {maximum} bytes: {path}"
        )));
    }
    let bytes = std::fs::read(path)?;
    if bytes.is_empty() || bytes.len() > maximum {
        return Err(SupervisorError::Invalid(format!(
            "runtime.fleet identity source has invalid length: {path}"
        )));
    }
    Ok(bytes)
}

fn hex_prefix(bytes: &[u8], digits: usize) -> String {
    let mut output = String::with_capacity(digits);
    for byte in bytes.iter().take(digits.div_ceil(2)) {
        use std::fmt::Write as _;
        let _ = write!(&mut output, "{byte:02x}");
    }
    output.truncate(digits);
    output
}

fn unix_ms() -> Result<u64, SupervisorError> {
    let duration = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| SupervisorError::Invalid(format!("system clock before epoch: {error}")))?;
    u64::try_from(duration.as_millis())
        .map_err(|_| SupervisorError::Invalid("system time exceeds u64 milliseconds".to_string()))
}
