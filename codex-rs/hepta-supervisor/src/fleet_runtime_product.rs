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
use codex_hepta_fleet::reconcile_expired_idempotent;
use codex_hepta_fleet::refresh_capacity_idempotent;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::FleetStartAdmission;
use codex_hepta_supervisor::H7H89ProductionGrantVerifier;
use codex_hepta_supervisor::SupervisorError;
use codex_hepta_supervisor::run_supervisord_with_fleet_start_admission;
use sha2::Digest;
use sha2::Sha256;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio::time::MissedTickBehavior;
use tokio_util::sync::CancellationToken;

const CAPACITY_TTL_MS: u64 = 60_000;
const CAPACITY_REFRESH_INTERVAL_MS: u64 = 20_000;
const CAPACITY_REFRESH_INTERVAL: Duration = Duration::from_secs(20);
const MAX_MEMORY_PRESSURE_BASIS_POINTS: u16 = 5_000;
const PRODUCT_OWNER_LOCK: &str = "runtime-fleet-product-owner.lock";
const HOST_ID_ENV: &str = "HEPTA_FLEET_HOST_ID";
const FAILURE_DOMAIN_ENV: &str = "HEPTA_FLEET_FAILURE_DOMAIN_ID";
const HOST_GENERATION_ENV: &str = "HEPTA_FLEET_HOST_GENERATION";

pub(crate) async fn run_supervisord_product(
    fleet_root: HeptaFleetRoot,
    cancellation: CancellationToken,
    verifier: Option<H7H89ProductionGrantVerifier>,
    fleet_start_admission: FleetStartAdmission,
) -> Result<(), SupervisorError> {
    let state_root = fleet_root.layout().state_root().to_path_buf();
    // Acquire the named-product ownership boundary before FleetRegistry open:
    // open_existing may clean staging roots, migrate private directories and
    // republish the workspace reservation index. A losing second product must
    // not perform even one registry or allocation-state write.
    let _product_owner = FleetProductOwnerGuard::acquire(&state_root)?;
    FleetRegistry::open_existing(fleet_root.clone())?;

    #[cfg(target_os = "linux")]
    let identity = Some(LocalFleetIdentityV1::discover(&state_root)?);
    #[cfg(not(target_os = "linux"))]
    let identity: Option<LocalFleetIdentityV1> = None;

    perform_maintenance(&state_root, identity.as_ref())?;

    let supervisor_cancellation = cancellation.clone();
    let mut supervisor = Box::pin(run_supervisord_with_fleet_start_admission(
        fleet_root,
        supervisor_cancellation,
        verifier,
        fleet_start_admission,
    ));
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
    let maintenance_slot = now_ms / CAPACITY_REFRESH_INTERVAL_MS;
    let expiry_operation_id = format!("supervisor-expiry-slot-{maintenance_slot}");
    if owner
        .metrics()
        .map_err(map_owner_error)?
        .fleet_expired_uncollected_grants
        > 0
    {
        reconcile_expired_idempotent(&mut owner, &expiry_operation_id).map_err(map_owner_error)?;
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
        SupervisorError::Invalid(format!(
            "configure runtime.fleet capacity observer: {error}"
        ))
    })?;
    // A reboot within the same maintenance slot must not replay the previous
    // incarnation's capacity receipt. Hash the complete identity, not its order.
    let identity_digest = Sha256::digest(
        format!("{}:{}", identity.host_id, identity.host_generation).as_bytes(),
    );
    let capacity_operation_id = format!(
        "supervisor-capacity-{}-slot-{maintenance_slot}",
        hex_prefix(&identity_digest, 64)
    );
    match refresh_capacity_idempotent(&mut owner, &capacity_operation_id, &observer) {
        Ok(_) => Ok(()),
        // Pressure is an observed unavailable state, not fabricated zero
        // capacity. Do not refresh the prior observation; it expires within one
        // TTL and new allocation then fails closed while lifecycle supervision
        // remains available.
        Err(DurableFleetError::Capacity(CapacityObservationError::PressureLimitExceeded {
            ..
        })) => Ok(()),
        Err(error) => Err(map_owner_error(error)),
    }
}

fn map_owner_error(error: DurableFleetError) -> SupervisorError {
    SupervisorError::Invalid(format!("runtime.fleet owner operation failed: {error}"))
}

struct FleetProductOwnerGuard {
    _file: File,
}

impl FleetProductOwnerGuard {
    fn acquire(state_root: &Path) -> Result<Self, SupervisorError> {
        let metadata = std::fs::symlink_metadata(state_root)?;
        if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
            return Err(SupervisorError::Invalid(format!(
                "runtime.fleet state root is not a physical directory: {}",
                state_root.display()
            )));
        }
        let path = state_root.join(PRODUCT_OWNER_LOCK);
        let file = open_product_owner_lock(&path)?;
        file.try_lock().map_err(|error| {
            SupervisorError::Invalid(format!(
                "another hepta-supervisord owns runtime.fleet product maintenance: {error}"
            ))
        })?;
        Ok(Self { _file: file })
    }
}

#[cfg(unix)]
fn open_product_owner_lock(path: &Path) -> Result<File, SupervisorError> {
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::fs::PermissionsExt;

    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .mode(0o600)
        .open(path)?;
    if !file.metadata()?.is_file() {
        return Err(SupervisorError::Invalid(
            "runtime.fleet product owner lock is not a regular file".to_string(),
        ));
    }
    file.set_permissions(std::fs::Permissions::from_mode(0o600))?;
    Ok(file)
}

#[cfg(not(unix))]
fn open_product_owner_lock(path: &Path) -> Result<File, SupervisorError> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)
        .map_err(Into::into)
}

#[derive(Clone, Debug)]
struct LocalFleetIdentityV1 {
    host_id: String,
    failure_domain_id: String,
    host_generation: u64,
}

impl LocalFleetIdentityV1 {
    fn discover(state_root: &Path) -> Result<Self, SupervisorError> {
        let configured = (
            std::env::var(HOST_ID_ENV).ok(),
            std::env::var(FAILURE_DOMAIN_ENV).ok(),
            std::env::var(HOST_GENERATION_ENV).ok(),
        );
        match configured {
            (Some(host_id), Some(failure_domain_id), Some(generation)) => {
                let requested_generation = generation.parse::<u64>().map_err(|error| {
                    SupervisorError::Invalid(format!("{HOST_GENERATION_ENV} is invalid: {error}"))
                })?;
                // Operator overrides use the same observed boot and durable
                // monotonic fence. Neither configuration nor wall time may
                // resurrect an old incarnation.
                let boot_identity = observed_boot_identity()?;
                Self::resolve(
                    state_root,
                    host_id,
                    failure_domain_id,
                    &boot_identity,
                    Some(requested_generation),
                )
            }
            (None, None, None) => Self::discover_linux(state_root),
            _ => Err(SupervisorError::Invalid(format!(
                "{HOST_ID_ENV}, {FAILURE_DOMAIN_ENV}, and {HOST_GENERATION_ENV} must be configured together"
            ))),
        }
    }

    fn resolve(
        state_root: &Path,
        host_id: String,
        failure_domain_id: String,
        boot_identity: &str,
        requested_generation: Option<u64>,
    ) -> Result<Self, SupervisorError> {
        let mut owner = DurableFleetOwner::open_supervisor_state_root(
            state_root,
            Arc::new(SystemFleetClock),
        )
        .map_err(map_owner_error)?;
        let incarnation = owner
            .resolve_host_incarnation(
                &host_id,
                &failure_domain_id,
                boot_identity,
                requested_generation,
            )
            .map_err(map_owner_error)?;
        Ok(Self {
            host_id,
            failure_domain_id,
            host_generation: incarnation.host_generation,
        })
    }

    #[cfg(target_os = "linux")]
    fn discover_linux(state_root: &Path) -> Result<Self, SupervisorError> {
        let machine_id = read_bounded("/etc/machine-id", 4_096)?;
        let machine_digest = Sha256::digest(machine_id.as_slice().trim_ascii());
        Self::resolve(
            state_root,
            format!("host-{}", hex_prefix(&machine_digest, 16)),
            format!("local-{}", hex_prefix(&machine_digest, 16)),
            &observed_boot_identity()?,
            None,
        )
    }

    #[cfg(not(target_os = "linux"))]
    fn discover_linux(_state_root: &Path) -> Result<Self, SupervisorError> {
        Err(SupervisorError::Invalid(
            "automatic runtime.fleet host discovery is currently implemented only for Linux"
                .to_string(),
        ))
    }
}

fn observed_boot_identity() -> Result<String, SupervisorError> {
    let bytes = read_bounded("/proc/sys/kernel/random/boot_id", 4_096)?;
    // The digest is an opaque identity. Its numeric ordering is never a host
    // generation; the existing durable owner allocates that separately.
    Ok(hex_prefix(&Sha256::digest(bytes.as_slice().trim_ascii()), 64))
}

fn read_bounded(path: &str, maximum: usize) -> Result<Vec<u8>, SupervisorError> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
    }
    let file = options.open(path)?;
    let metadata = file.metadata()?;
    if !metadata.file_type().is_file() {
        return Err(SupervisorError::Invalid(format!(
            "runtime.fleet identity source is not a regular file: {path}"
        )));
    }
    let maximum_u64 = u64::try_from(maximum)
        .map_err(|_| SupervisorError::Invalid("identity bound exceeds u64".to_string()))?;
    let read_limit = maximum_u64
        .checked_add(1)
        .ok_or_else(|| SupervisorError::Invalid("identity bound overflow".to_string()))?;
    if metadata.len() > maximum_u64 {
        return Err(SupervisorError::Invalid(format!(
            "runtime.fleet identity source exceeds {maximum} bytes: {path}"
        )));
    }
    let mut bytes = Vec::new();
    file.take(read_limit).read_to_end(&mut bytes)?;
    if bytes.as_slice().trim_ascii().is_empty() || bytes.len() > maximum {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn product_identity_survives_reopen_and_orders_boots_by_commit_not_hash() {
        let directory = tempfile::tempdir().expect("tempdir");
        let root = directory.path();
        let resolve = |boot: &str, requested| {
            LocalFleetIdentityV1::resolve(
                root,
                "host-test".to_string(),
                "domain-test".to_string(),
                boot,
                requested,
            )
        };
        let first = resolve(&"f".repeat(64), None).expect("first boot");
        let reopened = resolve(&"f".repeat(64), None).expect("same boot restart");
        assert_eq!(first.host_generation, reopened.host_generation);
        let second = resolve(&"1".repeat(64), None).expect("new lower-valued identity");
        assert_eq!(second.host_generation, first.host_generation + 1);
        assert!(resolve(&"f".repeat(64), None).is_err());
        assert!(resolve(&"1".repeat(64), Some(first.host_generation)).is_err());
    }

    #[test]
    fn identity_read_rejects_missing_empty_and_oversized_sources() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("boot-id");
        let name = path.to_str().expect("path");
        assert!(read_bounded(name, 32).is_err());
        assert!(!path.exists());
        std::fs::write(&path, " \n").expect("write empty");
        assert!(read_bounded(name, 32).is_err());
        std::fs::write(&path, "x".repeat(33)).expect("write oversized");
        assert!(read_bounded(name, 32).is_err());
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn actual_linux_boot_identity_is_stable_across_owner_reopens() {
        let directory = tempfile::tempdir().expect("tempdir");
        let first = LocalFleetIdentityV1::discover_linux(directory.path()).expect("native discovery");
        let second = LocalFleetIdentityV1::discover_linux(directory.path()).expect("native reopen");
        assert_eq!(first.host_id, second.host_id);
        assert_eq!(first.host_generation, second.host_generation);
    }

    #[cfg(unix)]
    #[test]
    fn identity_reader_and_product_lock_reject_symlinks() {
        use std::os::unix::fs::symlink;
        let directory = tempfile::tempdir().expect("tempdir");
        let target = directory.path().join("target");
        std::fs::write(&target, "boot-identity").expect("write target");
        let link = directory.path().join("link");
        symlink(&target, &link).expect("symlink");
        assert!(read_bounded(link.to_str().expect("path"), 32).is_err());
        assert!(open_product_owner_lock(&link).is_err());
        assert_eq!(std::fs::read_to_string(target).expect("target"), "boot-identity");
    }
}
