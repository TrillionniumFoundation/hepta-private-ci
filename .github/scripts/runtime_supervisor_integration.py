#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:160]!r}")
    write(path, content.replace(old, new, 1))


def replace_all(path: str, old: str, new: str, minimum: int = 1) -> None:
    content = read(path)
    count = content.count(old)
    if count < minimum:
        raise RuntimeError(f"{path}: expected at least {minimum} replacements, found {count}: {old[:160]!r}")
    write(path, content.replace(old, new))


# Fix generator output before integrating it.
replace_once(
    "codex-rs/hepta-supervisor/src/daemon_protocol.rs",
    "use codex_hepta_contracts::Sha256Digest;\n",
    "",
)
replace_all(
    "codex-rs/hepta-supervisor/src/lock_qualification.rs",
    "*guard = guard.saturating_add(1);",
    "*guard = (*guard).saturating_add(1);",
    minimum=3,
)
replace_once(
    "codex-rs/hepta-supervisor/src/production_authority_distribution.rs",
    '''        assert_eq!(
            reader.resolve_grant(&first),
            Err(ProductionAuthorityDistributionError::StaleSigner)
        );
        assert_eq!(
            publisher.rotate(1, verifier("release-policy", 3, 3)),
            Err(ProductionAuthorityDistributionError::GenerationFence {
                expected: 1,
                actual: 2,
            })
        );
''',
    '''        assert!(matches!(
            reader.resolve_grant(&first),
            Err(ProductionAuthorityDistributionError::StaleSigner)
        ));
        assert!(matches!(
            publisher.rotate(1, verifier("release-policy", 3, 3)),
            Err(ProductionAuthorityDistributionError::GenerationFence {
                expected: 1,
                actual: 2,
            })
        ));
''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/production_authority_distribution.rs",
    '''        assert_eq!(
            reader.resolve_grant(&second),
            Err(ProductionAuthorityDistributionError::RevokedGrant)
        );

        let wrong = grant("other-policy", 2, Sha256Digest::for_bytes(b"wrong"));
        assert_eq!(
            reader.resolve_grant(&wrong),
            Err(ProductionAuthorityDistributionError::UnknownSigner)
        );
''',
    '''        assert!(matches!(
            reader.resolve_grant(&second),
            Err(ProductionAuthorityDistributionError::RevokedGrant)
        ));

        let wrong = grant("other-policy", 2, Sha256Digest::for_bytes(b"wrong"));
        assert!(matches!(
            reader.resolve_grant(&wrong),
            Err(ProductionAuthorityDistributionError::UnknownSigner)
        ));
''',
)

# Instrumented lock and external authority distribution in the daemon.
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "#[cfg(unix)]\nuse tokio::sync::Mutex;\n",
    "",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "use crate::H7H89ProductionGrantVerifier;\n",
    "use crate::H7H89ProductionGrantVerifier;\nuse crate::ProductionAuthorityReader;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "#[cfg(unix)]\nuse crate::daemon_protocol::SupervisordHealth;\n",
    "#[cfg(unix)]\nuse crate::daemon_protocol::SupervisordDiagnostics;\n#[cfg(unix)]\nuse crate::daemon_protocol::SupervisordHealth;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "#[cfg(unix)]\nuse crate::daemon_protocol::SupervisordMethod;\n",
    "#[cfg(unix)]\nuse crate::daemon_protocol::SupervisordLockOperation;\n#[cfg(unix)]\nuse crate::daemon_protocol::SupervisordMethod;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "#[cfg(unix)]\nuse crate::signed_authority::authority_epoch_for_supervisor_epoch;\n",
    "#[cfg(unix)]\nuse crate::signed_authority::authority_epoch_for_supervisor_epoch;\n#[cfg(unix)]\nuse crate::supervisor_lock::SupervisorLock;\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''struct DaemonState<D: ProcessDriver> {
    registry: FleetRegistry,
    supervisor: Mutex<Supervisor<D>>,
    supervisor_epoch: SupervisorEpoch,
    production_grant_verifier: Option<H7H89ProductionGrantVerifier>,
    observed_faults: AtomicU64,
}
''',
    '''struct DaemonState<D: ProcessDriver> {
    registry: FleetRegistry,
    supervisor: SupervisorLock<Supervisor<D>>,
    supervisor_epoch: SupervisorEpoch,
    production_authority: Option<ProductionAuthorityReader>,
    observed_faults: AtomicU64,
}
''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''pub async fn run_supervisord_with_grant_verifier(
    fleet_root: HeptaFleetRoot,
    cancellation: CancellationToken,
    verifier: H7H89ProductionGrantVerifier,
) -> Result<(), SupervisorError> {
    if !PRODUCTION_AUTHORITY_FEATURE_ENABLED {
        return Err(SupervisorError::ProductionAuthorityFeatureDisabled);
    }
    run_supervisord_inner(fleet_root, cancellation, Some(verifier)).await
}
''',
    '''pub async fn run_supervisord_with_grant_verifier(
    fleet_root: HeptaFleetRoot,
    cancellation: CancellationToken,
    verifier: H7H89ProductionGrantVerifier,
) -> Result<(), SupervisorError> {
    if !PRODUCTION_AUTHORITY_FEATURE_ENABLED {
        return Err(SupervisorError::ProductionAuthorityFeatureDisabled);
    }
    let authority = ProductionAuthorityReader::pinned(verifier)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    run_supervisord_inner(fleet_root, cancellation, Some(authority)).await
}

/// Runs supervisord with an independently owned, live authority distribution.
/// The publisher remains outside this process boundary; signer rotation and
/// grant revocation are resolved again immediately before final-use admission.
pub async fn run_supervisord_with_authority_distribution(
    fleet_root: HeptaFleetRoot,
    cancellation: CancellationToken,
    authority: ProductionAuthorityReader,
) -> Result<(), SupervisorError> {
    if !PRODUCTION_AUTHORITY_FEATURE_ENABLED {
        return Err(SupervisorError::ProductionAuthorityFeatureDisabled);
    }
    run_supervisord_inner(fleet_root, cancellation, Some(authority)).await
}
''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "    production_grant_verifier: Option<H7H89ProductionGrantVerifier>,\n) -> Result<(), SupervisorError> {\n",
    "    production_authority: Option<ProductionAuthorityReader>,\n) -> Result<(), SupervisorError> {\n",
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''    let state = Arc::new(DaemonState {
        registry,
        supervisor: Mutex::new(supervisor),
        supervisor_epoch: SupervisorEpoch::new(),
        production_grant_verifier,
        observed_faults: AtomicU64::new(recovery.faults.len() as u64),
    });
''',
    '''    let state = Arc::new(DaemonState {
        registry,
        supervisor: SupervisorLock::new(supervisor),
        supervisor_epoch: SupervisorEpoch::new(),
        production_authority,
        observed_faults: AtomicU64::new(recovery.faults.len() as u64),
    });
''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''                _ = interval.tick() => {
                    let faults = tick_state.supervisor.lock().await.tick(Instant::now()).faults;
                    tick_state.observed_faults.fetch_add(faults.len() as u64, Ordering::Relaxed);
                }
''',
    '''                _ = interval.tick() => {
                    // Collection and per-Agent application are separate lock
                    // phases. A slow process driver no longer monopolizes one
                    // 256-Agent tick while preserving the single writer and
                    // every Fleet generation/CAS fence.
                    let agent_ids = {
                        let supervisor = tick_state
                            .supervisor
                            .lock(SupervisordLockOperation::TickPlan)
                            .await;
                        supervisor.agent_ids()
                    };
                    for agent_id in agent_ids {
                        let faults = {
                            let mut supervisor = tick_state
                                .supervisor
                                .lock(SupervisordLockOperation::TickAgent)
                                .await;
                            supervisor.tick_agent(&agent_id, Instant::now()).faults
                        };
                        tick_state
                            .observed_faults
                            .fetch_add(faults.len() as u64, Ordering::Relaxed);
                        tokio::task::yield_now().await;
                    }
                }
''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "    _production_grant_verifier: Option<H7H89ProductionGrantVerifier>,\n",
    "    _production_authority: Option<ProductionAuthorityReader>,\n",
)

# Add diagnostics endpoint and move read-only registry collection outside lock.
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''            let recovery_required = state
                .supervisor
                .lock()
                .await
                .any_production_recovery_required();
''',
    '''            let recovery_required = state
                .supervisor
                .lock(SupervisordLockOperation::Health)
                .await
                .any_production_recovery_required();
''',
)
health_tail = '''            SupervisordPayload::Health(SupervisordHealth {
                ready: !recovery_required,
                supervisor_epoch: state.supervisor_epoch.clone(),
                process_id: std::process::id(),
                registered_agents,
                observed_faults: state.observed_faults.load(Ordering::Relaxed),
            })
        }
'''
diagnostics_arm = health_tail + '''        SupervisordMethod::Diagnostics { agent_id } => {
            let registry_snapshot = match state.registry.load() {
                Ok(snapshot) => snapshot,
                Err(error) => {
                    return safe_rejection(error.into(), None, false);
                }
            };
            let registered_agents = match u16::try_from(registry_snapshot.agents.len()) {
                Ok(count) => count,
                Err(_) => {
                    return safe_rejection(
                        SupervisorError::Invalid("registered agent count exceeds u16".to_string()),
                        None,
                        false,
                    );
                }
            };
            let authority = match state.production_authority.as_ref() {
                Some(authority) => match authority.snapshot() {
                    Ok(snapshot) => Some(snapshot),
                    Err(error) => {
                        return safe_rejection(
                            SupervisorError::Invalid(error.to_string()),
                            None,
                            false,
                        );
                    }
                },
                None => None,
            };
            let recovery = match agent_id {
                Some(agent_id) => {
                    let supervisor = state
                        .supervisor
                        .lock(SupervisordLockOperation::Diagnostics)
                        .await;
                    Some(crate::recovery_diagnostics::diagnose(
                        &state.registry,
                        &supervisor,
                        &agent_id,
                        authority_epoch_for_supervisor_epoch(state.supervisor_epoch.as_str()),
                    ))
                }
                None => None,
            };
            SupervisordPayload::Diagnostics(SupervisordDiagnostics {
                supervisor_epoch: state.supervisor_epoch.clone(),
                process_id: std::process::id(),
                registered_agents,
                observed_faults: state.observed_faults.load(Ordering::Relaxed),
                authority_distribution_generation: authority.as_ref().map(|value| value.generation),
                authority_signer_id: authority.as_ref().map(|value| value.signer_id.clone()),
                authority_signer_epoch: authority.as_ref().map(|value| value.signer_epoch),
                lock_metrics: state.supervisor.snapshot(),
                recovery,
            })
        }
'''
replace_once("codex-rs/hepta-supervisor/src/daemon.rs", health_tail, diagnostics_arm)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''            let supervisor = state.supervisor.lock().await;
            let records = match state.registry.load() {
                Ok(snapshot) => snapshot.agents,
''',
    '''            let records = match state.registry.load() {
                Ok(snapshot) => snapshot.agents,
''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''                }
            };
            let agents = match records
''',
    '''                }
            };
            let supervisor = state
                .supervisor
                .lock(SupervisordLockOperation::Roster)
                .await;
            let agents = match records
''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''        SupervisordMethod::ReleaseSelection { agent_id } => {
            let supervisor = state.supervisor.lock().await;
''',
    '''        SupervisordMethod::ReleaseSelection { agent_id } => {
            let supervisor = state
                .supervisor
                .lock(SupervisordLockOperation::ReleaseSelection)
                .await;
''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''        SupervisordMethod::ProductionMutationStatus { agent_id } => {
            let supervisor = state.supervisor.lock().await;
''',
    '''        SupervisordMethod::ProductionMutationStatus { agent_id } => {
            let supervisor = state
                .supervisor
                .lock(SupervisordLockOperation::ProductionMutationStatus)
                .await;
''',
)

# Final-use authority lookup and labelled mutation locks.
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''    let Some(verifier) = state.production_grant_verifier.clone() else {
        return error_payload(
            "production_authority_unavailable",
            "signed production recovery requires an externally pinned verifier",
            /*actual*/ None,
        );
    };
    let agent_id = fence.agent_id.clone();
    let mut supervisor = state.supervisor.lock().await;
''',
    '''    let Some(authority) = state.production_authority.as_ref() else {
        return error_payload(
            "production_authority_unavailable",
            "signed production recovery requires an externally pinned authority distribution",
            /*actual*/ None,
        );
    };
    let verifier = match authority.resolve_recovery(&decision) {
        Ok(verifier) => verifier,
        Err(error) => {
            return error_payload(
                "production_authority_rejected",
                &error.to_string(),
                /*actual*/ None,
            );
        }
    };
    let agent_id = fence.agent_id.clone();
    let mut supervisor = state
        .supervisor
        .lock(SupervisordLockOperation::RecoveryResolution)
        .await;
''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''    let Some(verifier) = state.production_grant_verifier.clone() else {
        return error_payload(
            "production_authority_unavailable",
            "signed production mutations require an externally pinned verifier",
            /*actual*/ None,
        );
    };
''',
    '''    let Some(authority) = state.production_authority.as_ref() else {
        return error_payload(
            "production_authority_unavailable",
            "signed production mutations require an externally pinned authority distribution",
            /*actual*/ None,
        );
    };
    let verifier = match authority.resolve_grant(&grant) {
        Ok(verifier) => verifier,
        Err(error) => {
            return error_payload(
                "production_authority_rejected",
                &error.to_string(),
                /*actual*/ None,
            );
        }
    };
''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''    let agent_id = fence.agent_id.clone();
    let accepted_state_digest = fence.state_digest.clone();
    let mut supervisor = state.supervisor.lock().await;
''',
    '''    let agent_id = fence.agent_id.clone();
    let accepted_state_digest = fence.state_digest.clone();
    let mut supervisor = state
        .supervisor
        .lock(SupervisordLockOperation::SignedMutation)
        .await;
''',
)
# The second identical block belongs to ordinary mutation after the signed block was replaced.
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''    let agent_id = fence.agent_id.clone();
    let accepted_state_digest = fence.state_digest.clone();
    let mut supervisor = state.supervisor.lock().await;
''',
    '''    let agent_id = fence.agent_id.clone();
    let accepted_state_digest = fence.state_digest.clone();
    let mut supervisor = state
        .supervisor
        .lock(SupervisordLockOperation::Mutation)
        .await;
''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    "    if state.production_grant_verifier.is_some()\n",
    "    if state.production_authority.is_some()\n",
)

# Move status registry load out of the read-only lock; mutation paths retain exact locked status.
replace_once(
    "codex-rs/hepta-supervisor/src/daemon.rs",
    '''async fn agent_status<D: ProcessDriver>(
    state: &DaemonState<D>,
    agent_id: &AgentId,
) -> Result<SupervisordAgentStatus, SupervisorError> {
    let supervisor = state.supervisor.lock().await;
    agent_status_locked(state, &supervisor, agent_id)
}
''',
    '''async fn agent_status<D: ProcessDriver>(
    state: &DaemonState<D>,
    agent_id: &AgentId,
) -> Result<SupervisordAgentStatus, SupervisorError> {
    let record = state
        .registry
        .load()?
        .agent(agent_id)
        .cloned()
        .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
    let supervisor = state
        .supervisor
        .lock(SupervisordLockOperation::Snapshot)
        .await;
    status_from(
        &state.supervisor_epoch,
        &record,
        supervisor.snapshot(agent_id),
    )
}
''',
)

# Durable publication with named failpoints. Production builds ignore the
# environment variable because qualification_fault is cfg-gated.
write(
    "codex-rs/hepta-supervisor/src/durable_publish.rs",
    r'''use std::io;
use std::path::Path;

/// Replace one already-synchronized staging file within the same directory.
/// Unix synchronizes the parent directory; Windows uses write-through replace.
pub(crate) fn publish(staging: &Path, destination: &Path) -> io::Result<()> {
    publish_with_context("durable_publish", staging, destination)
}

pub(crate) fn publish_with_context(
    context: &str,
    staging: &Path,
    destination: &Path,
) -> io::Result<()> {
    let parent = staging.parent().ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "durable staging has no parent")
    })?;
    if destination.parent() != Some(parent) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "durable replacement must remain in the staging directory",
        ));
    }
    crate::qualification_fault::check(&format!("{context}.rename"))?;
    publish_same_directory(staging, destination)?;
    crate::qualification_fault::check(&format!("{context}.after_publish"))?;
    crate::qualification_fault::check(&format!("{context}.directory_fsync"))?;
    sync_parent(destination)
}

#[cfg(unix)]
fn publish_same_directory(staging: &Path, destination: &Path) -> io::Result<()> {
    std::fs::rename(staging, destination)
}

#[cfg(windows)]
fn publish_same_directory(staging: &Path, destination: &Path) -> io::Result<()> {
    use windows_sys::Win32::Storage::FileSystem::MOVEFILE_REPLACE_EXISTING;
    use windows_sys::Win32::Storage::FileSystem::MOVEFILE_WRITE_THROUGH;
    use windows_sys::Win32::Storage::FileSystem::MoveFileExW;

    let parent = staging.parent().ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "durable staging has no parent")
    })?;
    let parent = if parent.as_os_str().is_empty() {
        Path::new(".")
    } else {
        parent
    };
    let parent = parent.canonicalize()?;
    let staging_name = staging.file_name().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "durable staging has no file name",
        )
    })?;
    let destination_name = destination.file_name().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "durable destination has no file name",
        )
    })?;
    let staging = wide_path(&parent.join(staging_name))?;
    let destination = wide_path(&parent.join(destination_name))?;
    // SAFETY: Both buffers are NUL-terminated UTF-16 paths with no interior NUL,
    // and remain alive for this synchronous call.
    let result = unsafe {
        MoveFileExW(
            staging.as_ptr(),
            destination.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if result == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

#[cfg(unix)]
fn sync_parent(destination: &Path) -> io::Result<()> {
    let parent = destination.parent().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "durable destination has no parent",
        )
    })?;
    std::fs::File::open(parent)?.sync_all()
}

#[cfg(windows)]
fn sync_parent(_destination: &Path) -> io::Result<()> {
    Ok(())
}

#[cfg(windows)]
fn wide_path(path: &Path) -> io::Result<Vec<u16>> {
    use std::os::windows::ffi::OsStrExt;

    let mut wide = Vec::new();
    for unit in path.as_os_str().encode_wide() {
        if unit == 0 || wide.len() >= 32_766 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "durable path contains NUL or exceeds the Windows path limit",
            ));
        }
        wide.push(unit);
    }
    wide.push(/*value*/ 0);
    Ok(wide)
}

#[cfg(not(any(unix, windows)))]
fn publish_same_directory(_staging: &Path, _destination: &Path) -> io::Result<()> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "durable publication is unsupported on this platform",
    ))
}

#[cfg(not(any(unix, windows)))]
fn sync_parent(_destination: &Path) -> io::Result<()> {
    Ok(())
}
''',
)

# Lease failpoints.
replace_once(
    "codex-rs/hepta-supervisor/src/lease.rs",
    'const PROCESS_LEASE_FILE: &str = "supervisor-process.json";\n',
    'pub(crate) const PROCESS_LEASE_FILE: &str = "supervisor-process.json";\n',
)
replace_once(
    "codex-rs/hepta-supervisor/src/lease.rs",
    '''    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp_path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    match std::fs::hard_link(&temp_path, &final_path) {
''',
    '''    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp_path)?;
    crate::qualification_fault::check("lease.storage_full")?;
    file.write_all(&bytes)?;
    crate::qualification_fault::check("lease.fsync")?;
    file.sync_all()?;
    crate::qualification_fault::check("lease.rename")?;
    match std::fs::hard_link(&temp_path, &final_path) {
''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/lease.rs",
    '''    }
    let _ = std::fs::remove_file(temp_path);
    sync_directory(run_root)
}
''',
    '''    }
    crate::qualification_fault::check("lease.after_publish")?;
    let _ = std::fs::remove_file(temp_path);
    crate::qualification_fault::check("lease.directory_fsync")?;
    sync_directory(run_root)
}
''',
)

# Restart journal failpoints.
replace_once(
    "codex-rs/hepta-supervisor/src/restart_journal.rs",
    '''    let mut file = options.open(&temp_path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    if let Err(error) = crate::durable_publish::publish(&temp_path, &final_path) {
''',
    '''    let mut file = options.open(&temp_path)?;
    crate::qualification_fault::check("restart_journal.storage_full")?;
    file.write_all(&bytes)?;
    crate::qualification_fault::check("restart_journal.fsync")?;
    file.sync_all()?;
    drop(file);
    if let Err(error) =
        crate::durable_publish::publish_with_context("restart_journal", &temp_path, &final_path)
    {
''',
)

# Signed intent failpoints.
replace_once(
    "codex-rs/hepta-supervisor/src/signed_intent.rs",
    '''    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    publish::publish(&temp, &final_path)?;
''',
    '''    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    crate::qualification_fault::check("signed_intent.storage_full")?;
    file.write_all(&bytes)?;
    crate::qualification_fault::check("signed_intent.fsync")?;
    file.sync_all()?;
    drop(file);
    publish::publish_with_context("signed_intent", &temp, &final_path)?;
''',
)

# Release transaction uses the same durable publisher and named fault points.
replace_once(
    "codex-rs/hepta-supervisor/src/release_transaction.rs",
    '''    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    replace_same_directory(&temp, &final_path)?;
    sync_directory(run_root)?;
    Ok(())
}

fn replace_same_directory(temp: &Path, final_path: &Path) -> Result<(), std::io::Error> {
    #[cfg(unix)]
    {
        std::fs::rename(temp, final_path)
    }
    #[cfg(not(unix))]
    {
        if final_path.exists() {
            std::fs::remove_file(final_path)?;
        }
        std::fs::rename(temp, final_path)
    }
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), std::io::Error> {
    std::fs::File::open(path)?.sync_all()
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), std::io::Error> {
    Ok(())
}
''',
    '''    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    crate::qualification_fault::check("release_transaction.storage_full")?;
    file.write_all(&bytes)?;
    crate::qualification_fault::check("release_transaction.fsync")?;
    file.sync_all()?;
    drop(file);
    crate::durable_publish::publish_with_context("release_transaction", &temp, &final_path)?;
    Ok(())
}
''',
)

# Actionable recovery mapping unit coverage.
with_tests = read("codex-rs/hepta-supervisor/src/recovery_diagnostics.rs") + r'''

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_blocker_maps_to_one_operator_action_and_retry_policy() {
        let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
            .expect("agent");
        let cases = [
            (RecoveryBlocker::None, RecoveryOperatorAction::None, true),
            (
                RecoveryBlocker::ProcessAmbiguity,
                RecoveryOperatorAction::FenceAndObserveProcessExit,
                false,
            ),
            (
                RecoveryBlocker::ReleaseCasAmbiguity,
                RecoveryOperatorAction::InspectReleaseStateCas,
                false,
            ),
            (
                RecoveryBlocker::IntentMismatch,
                RecoveryOperatorAction::InspectIntentAndTransaction,
                false,
            ),
            (
                RecoveryBlocker::FrontierDrift,
                RecoveryOperatorAction::RequalifyReleaseFrontier,
                false,
            ),
            (
                RecoveryBlocker::AuthorityEpochChange,
                RecoveryOperatorAction::RefreshAuthorityEpoch,
                false,
            ),
            (
                RecoveryBlocker::DurabilityFailure,
                RecoveryOperatorAction::RepairDurableState,
                false,
            ),
            (
                RecoveryBlocker::AwaitingIndependentDecision,
                RecoveryOperatorAction::IssueIndependentRecoveryDecision,
                false,
            ),
        ];
        for (blocker, action, retry_safe) in cases {
            let value = diagnostic(&agent_id, blocker, None, None);
            assert_eq!(value.action, action);
            assert_eq!(value.retry_safe, retry_safe);
        }
    }
}
'''
write("codex-rs/hepta-supervisor/src/recovery_diagnostics.rs", with_tests)

# Crash-consistency source matrix. The kill cases execute in a child process so
# SIGKILL exercises the real atomic publication boundary.
write(
    "codex-rs/hepta-supervisor/src/crash_qualification.rs",
    r'''#[cfg(test)]
mod tests {
    use std::path::Path;
    use std::process::Command;

    use codex_hepta_contracts::AgentId;
    use codex_hepta_contracts::Sha256Digest;
    use codex_hepta_fleet::AgentLifecycle;
    use codex_hepta_fleet::ReleaseId;

    use crate::H7H89ProductionTransition;
    use crate::ProcessIdentity;
    use crate::lease::PROCESS_LEASE_FILE;
    use crate::lease::ProcessLease;
    use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
    use crate::lease::read_lease;
    use crate::lease::write_lease;
    use crate::release_transaction::DurableReleaseTransaction;
    use crate::release_transaction::RELEASE_TRANSACTION_FILE;
    use crate::release_transaction::ReleaseTransactionKind;
    use crate::release_transaction::read_release_transaction;
    use crate::release_transaction::write_release_transaction;
    use crate::restart_journal::DurableRestartWindow;
    use crate::restart_journal::RESTART_JOURNAL_FILE;
    use crate::restart_journal::RestartBudgetJournal;
    use crate::restart_journal::read_restart_journal;
    use crate::restart_journal::write_restart_journal;
    use crate::signed_intent::SIGNED_INTENT_FILE;
    use crate::signed_intent::SignedIntentStatus;
    use crate::signed_intent::SignedSupervisorIntent;
    use crate::signed_intent::read_intent;
    use crate::signed_intent::write_intent;

    const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

    #[test]
    fn subprocess_writer() {
        let Ok(root) = std::env::var("HEPTA_CRASH_CHILD_ROOT") else {
            return;
        };
        let kind = std::env::var("HEPTA_CRASH_CHILD_KIND").expect("kind");
        let result = match kind.as_str() {
            "lease" => write_lease(Path::new(&root), &lease()).map_err(|error| error.to_string()),
            "restart" => write_restart_journal(Path::new(&root), &restart(2))
                .map_err(|error| error.to_string()),
            "intent" => write_intent(Path::new(&root), &intent(b"new-grant"))
                .map_err(|error| error.to_string()),
            "release" => write_release_transaction(Path::new(&root), &transaction("v3"))
                .map_err(|error| error.to_string()),
            other => panic!("unknown child writer {other}"),
        };
        let expected_error = std::env::var_os("HEPTA_CRASH_EXPECT_ERROR").is_some();
        if expected_error {
            assert!(result.is_err(), "fault injection unexpectedly succeeded");
        } else {
            result.expect("child write");
        }
    }

    #[test]
    fn storage_fsync_and_rename_failures_preserve_prior_valid_state() {
        for (kind, point) in [
            ("restart", "restart_journal.fsync=fsync"),
            ("intent", "signed_intent.storage_full=storage_full"),
            ("release", "release_transaction.rename=rename"),
        ] {
            let dir = tempfile::tempdir().expect("temp");
            write_baseline(kind, dir.path());
            let before = read_bytes(kind, dir.path());
            run_child(kind, dir.path(), point, true);
            assert_eq!(read_bytes(kind, dir.path()), before, "{kind} prior state changed");
            assert_valid(kind, dir.path());
        }
    }

    #[test]
    #[cfg(unix)]
    fn sigkill_after_publication_leaves_only_a_valid_old_or_new_record() {
        for (kind, point) in [
            ("lease", "lease.after_publish=kill"),
            ("intent", "signed_intent.after_publish=kill"),
            ("release", "release_transaction.after_publish=kill"),
        ] {
            let dir = tempfile::tempdir().expect("temp");
            if kind != "lease" {
                write_baseline(kind, dir.path());
            }
            let status = run_child_status(kind, dir.path(), point, false);
            assert!(!status.success(), "SIGKILL child unexpectedly succeeded");
            assert_valid(kind, dir.path());
        }
    }

    #[test]
    fn truncated_lease_restart_intent_and_transaction_fail_closed() {
        for kind in ["lease", "restart", "intent", "release"] {
            let dir = tempfile::tempdir().expect("temp");
            write_baseline(kind, dir.path());
            let path = record_path(kind, dir.path());
            let mut bytes = std::fs::read(&path).expect("record");
            bytes.truncate(bytes.len().saturating_div(2).max(1));
            std::fs::write(path, bytes).expect("truncate");
            assert_invalid(kind, dir.path());
        }
    }

    fn run_child(kind: &str, root: &Path, fault: &str, expect_error: bool) {
        let status = run_child_status(kind, root, fault, expect_error);
        assert!(status.success(), "child writer failed: {status:?}");
    }

    fn run_child_status(
        kind: &str,
        root: &Path,
        fault: &str,
        expect_error: bool,
    ) -> std::process::ExitStatus {
        let mut command = Command::new(std::env::current_exe().expect("test binary"));
        command
            .arg("--exact")
            .arg("crash_qualification::tests::subprocess_writer")
            .arg("--nocapture")
            .env("HEPTA_CRASH_CHILD_ROOT", root)
            .env("HEPTA_CRASH_CHILD_KIND", kind)
            .env("HEPTA_SUPERVISOR_FAULT", fault);
        if expect_error {
            command.env("HEPTA_CRASH_EXPECT_ERROR", "1");
        }
        command.status().expect("run child")
    }

    fn write_baseline(kind: &str, root: &Path) {
        match kind {
            "lease" => write_lease(root, &lease()).expect("lease"),
            "restart" => write_restart_journal(root, &restart(1)).expect("restart"),
            "intent" => write_intent(root, &intent(b"old-grant")).expect("intent"),
            "release" => write_release_transaction(root, &transaction("v2")).expect("release"),
            other => panic!("unknown baseline {other}"),
        }
    }

    fn read_bytes(kind: &str, root: &Path) -> Vec<u8> {
        std::fs::read(record_path(kind, root)).expect("record bytes")
    }

    fn record_path(kind: &str, root: &Path) -> std::path::PathBuf {
        root.join(match kind {
            "lease" => PROCESS_LEASE_FILE,
            "restart" => RESTART_JOURNAL_FILE,
            "intent" => SIGNED_INTENT_FILE,
            "release" => RELEASE_TRANSACTION_FILE,
            other => panic!("unknown record {other}"),
        })
    }

    fn assert_valid(kind: &str, root: &Path) {
        match kind {
            "lease" => {
                let value = read_lease(root).expect("lease read").expect("lease present");
                crate::lease::validate_lease(&value, &agent(), 1, AgentLifecycle::Starting)
                    .expect("lease valid");
            }
            "restart" => assert!(read_restart_journal(root).expect("restart read").is_some()),
            "intent" => assert!(read_intent(root).expect("intent read").is_some()),
            "release" => {
                assert!(read_release_transaction(root).expect("release read").is_some())
            }
            other => panic!("unknown valid record {other}"),
        }
    }

    fn assert_invalid(kind: &str, root: &Path) {
        let invalid = match kind {
            "lease" => read_lease(root).is_err(),
            "restart" => read_restart_journal(root).is_err(),
            "intent" => read_intent(root).is_err(),
            "release" => read_release_transaction(root).is_err(),
            other => panic!("unknown invalid record {other}"),
        };
        assert!(invalid, "{kind} truncation was accepted");
    }

    fn agent() -> AgentId {
        AgentId::parse(AGENT).expect("agent")
    }

    fn lease() -> ProcessLease {
        ProcessLease {
            schema_version: PROCESS_LEASE_SCHEMA_VERSION,
            agent_id: agent(),
            spawn_generation: 1,
            release_id: ReleaseId::parse("v1").expect("release"),
            identity: ProcessIdentity::new(42, "qualification-incarnation").expect("identity"),
        }
    }

    fn restart(attempts: u32) -> RestartBudgetJournal {
        RestartBudgetJournal::new(
            agent(),
            ReleaseId::parse("v1").expect("release"),
            DurableRestartWindow::empty(),
            DurableRestartWindow {
                attempts,
                window_started_unix_millis: Some(1_000),
            },
        )
        .expect("restart")
    }

    fn intent(grant: &[u8]) -> SignedSupervisorIntent {
        SignedSupervisorIntent::new(
            Sha256Digest::for_bytes(grant),
            AGENT,
            H7H89ProductionTransition::Upgrade,
            "v1",
            "v2",
            0,
            1,
            1,
            SignedIntentStatus::Committed,
        )
        .expect("intent")
    }

    fn transaction(target: &str) -> DurableReleaseTransaction {
        DurableReleaseTransaction::new(
            AGENT,
            ReleaseTransactionKind::Upgrade,
            "v1",
            target,
            None,
            None,
            None,
            1,
            1,
        )
        .expect("transaction")
    }
}
''',
)
replace_once(
    "codex-rs/hepta-supervisor/src/lib.rs",
    "mod control;\n",
    "mod control;\n#[cfg(test)]\nmod crash_qualification;\n",
)

print("runtime.supervisor integration phase patched")
