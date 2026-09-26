//! Named product composition for the supervisor-owned fleet allocation state.
//!
//! This module is part of the existing `hepta-supervisord` process. It opens
//! the durable owner under the canonical fleet state root, refreshes physical
//! capacity from the selected host, and reconciles lease expiry. It never
//! starts a second fleet writer or treats an observation as allocation authority.

use codex_hepta_fleet::CapacityObservationError;
use codex_hepta_fleet::DurableFleetError;
use codex_hepta_fleet::DurableFleetOwner;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::LinuxProcfsCapacityObserverV1;
use codex_hepta_fleet::SystemFleetClock;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::H7H89ProductionGrantVerifier;
use codex_hepta_supervisor::SupervisorError;
use codex_hepta_supervisor::run_supervisord;
use codex_hepta_supervisor::run_supervisord_with_grant_verifier;
use sha2::Digest;
use sha2::Sha256;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio::time::MissedTickBehavior;
use tokio_util::sync::CancellationToken;

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

    #[cfg(target_os = "linux")]
    let identity = Some(LocalFleetIdentityV1::discover()?);
    #[cfg(not(target_os = "linux"))]
    let identity: Option<LocalFleetIdentityV1> = None;

    perform_maintenance(&state_root, identity.as_ref())?;

    let supervisor_cancellation = cancellation.clone();
    let mut supervisor = Box::pin(async move {
        match verifier {
            Some(verifier) => {
                run_supervisord_with_grant_verifier(
                    fleet_root,
                    supervisor_cancellation,
                    verifier,
                )
                .await
            }
            None => run_supervisord(fleet_root, supervisor_cancellation).await,
        }
    });
    let mut interval = tokio::time::interval(CAPACITY_REFRESH_INTERVAL);
    interval.set_missed_tick_behavior(MissedTickBehavior::Skip);
    // The first interval tick is immediate; initial maintenance already ran.
    interval.tick().await;

    loop {
        tokio::select! {
            result = &mut supervisor => {
                cancellation.cancel();
                return result;
            }
            _ = interval.tick() => {
                let maintenance_root = state_root.clone();
                let maintenance_identity = identity.clone();
                let maintenance = tokio::task::spawn_blocking(move || {
                    perform_maintenance(&maintenance_root, maintenance_identity.as_ref())
                })
                .await
                .map_err(|error| {
                    SupervisorError::Invalid(format!(
                        "runtime.fleet maintenance task failed: {error}"
                    ))
                })?;
                if let Err(error) = maintenance {
                    cancellation.cancel();
                    let _ = supervisor.await;
                    return Err(error);
                }
            }
        }
    }
}

fn perform_maintenance(
    state_root: &Path,
    identity: Option<&LocalFleetIdentityV1>,
) -> Result<(), SupervisorError> {
    let clock = Arc::new(SystemFleetClock);
    let mut owner = DurableFleetOwner::open_supervisor_state_root(state_root, clock)
        .map_err(|error| SupervisorError::Invalid(format!("open runtime.fleet owner: {error}")))?;
    let now_ms = unix_ms()?;
    if owner
        .metrics()
        .map_err(map_owner_error)?
        .fleet_expired_uncollected_grants
        > 0
    {
        owner
            .reconcile_expired(&format!("supervisor-expiry-{now_ms}"))
            .map_err(map_owner_error)?;
    }

    let Some(identity) = identity else {
        return Ok(());
    };
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
    match owner.refresh_capacity(&format!("supervisor-capacity-{now_ms}"), &observer) {
        Ok(_) => Ok(()),
        // Pressure is an observed unavailable state, not fabricated zero
        // capacity. Do not refresh the prior observation; it expires within one
        // TTL and new allocation then fails closed while lifecycle supervision
        // remains available.
        Err(DurableFleetError::Capacity(
            CapacityObservationError::PressureLimitExceeded { .. },
        )) => Ok(()),
        Err(error) => Err(map_owner_error(error)),
    }
}

fn map_owner_error(error: DurableFleetError) -> SupervisorError {
    SupervisorError::Invalid(format!("runtime.fleet owner operation failed: {error}"))
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
        let machine_digest = Sha256::digest(machine_id.as_slice().trim_ascii());
        let boot_digest = Sha256::digest(boot_id.as_slice().trim_ascii());
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
    let maximum_u64 = u64::try_from(maximum)
        .map_err(|_| SupervisorError::Invalid("identity bound exceeds u64".to_string()))?;
    if metadata.len() > maximum_u64 {
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
