//! Root launcher entry points. Initialization and runtime opening are disjoint.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::HostAuthorityClock;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use serde::Deserialize;
use serde::Serialize;

use crate::DeploymentFinalUseIssuer;
use crate::DeploymentGrantPolicy;
use crate::HostAuthorityLane;
use crate::HostAuthorityService;
use crate::authority_host_config::HostAuthorityBindIdentity;
use crate::authority_host_config::HostAuthorityRegistration;
use crate::authority_host_config::HostAuthorityServiceConfig;
use crate::authority_host_config::read_root_json;

#[path = "authority_host_listeners.rs"]
mod listeners;
use listeners::serve_lanes;

const CLOCK_OWNER: &str = "root-authority-clock-v1";
const LEASE_OWNER: &str = "root-authority-leases-v1";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityBootstrap {
    pub schema_version: u32,
    pub required_bind: HostAuthorityBindIdentity,
    pub signer_id: String,
    pub policies: Vec<DeploymentGrantPolicy>,
    pub lease_id: String,
    pub lease_binding: AuthorityLeaseBinding,
    pub lease_lifetime_ms: u64,
}

#[derive(Serialize)]
pub struct HostAuthorityInitialized {
    pub schema_version: u32,
    pub signer_id: String,
    pub verifying_key: [u8; 32],
    pub lease_id: String,
    pub lease_revision: u64,
    pub production_ready: bool,
}

/// Fresh explicit administrator authorization, not a cut/recovery witness.
/// Existing or partial state is never overwritten or reset after failure.
pub fn initialize_host_authority(
    state: &Path,
    bootstrap_file: &Path,
) -> io::Result<HostAuthorityInitialized> {
    let bootstrap: HostAuthorityBootstrap = read_root_json(bootstrap_file)?;
    if bootstrap.schema_version != 1 || !(1..=86_400_000).contains(&bootstrap.lease_lifetime_ms) {
        return Err(io::Error::other("invalid bootstrap"));
    }
    bootstrap.required_bind.verify()?;
    if !state.starts_with(&bootstrap.required_bind.mountpoint)
        || state == bootstrap.required_bind.mountpoint
    {
        return Err(io::Error::other(
            "state must be a new child of required bind",
        ));
    }
    RootAuthorityDirectory::open(
        state
            .parent()
            .ok_or_else(|| io::Error::other("missing parent"))?,
    )
    .map_err(io::Error::other)?;
    std::fs::DirBuilder::new().mode(0o700).create(state)?;
    File::open(
        state
            .parent()
            .ok_or_else(|| io::Error::other("missing parent"))?,
    )?
    .sync_all()?;
    let root = RootAuthorityDirectory::open(state).map_err(io::Error::other)?;
    let clock = Arc::new(
        HostAuthorityClock::initialize(root.clone(), CLOCK_OWNER.into())
            .map_err(io::Error::other)?,
    );
    let frontier = Arc::new(
        HostAuthorityFrontierStore::initialize(
            root,
            LEASE_OWNER.into(),
            AuthorityLeaseFrontier::for_empty_epoch(1).map_err(io::Error::other)?,
        )
        .map_err(io::Error::other)?,
    );
    let lease_path = state.join("leases");
    std::fs::DirBuilder::new().mode(0o700).create(&lease_path)?;
    File::open(state)?.sync_all()?;
    let leases = AuthorityLeaseRegistry::open_state_dir_with_trust(
        &lease_path,
        LEASE_OWNER.into(),
        clock.clone(),
        frontier,
    )
    .map_err(io::Error::other)?;
    let now = clock.now_unix_ms().map_err(io::Error::other)?;
    let expiry = now
        .checked_add(bootstrap.lease_lifetime_ms)
        .ok_or_else(|| io::Error::other("lease expiry overflow"))?;
    leases
        .put_lease(
            AuthorityLease {
                schema_version: 1,
                lease_id: bootstrap.lease_id.clone(),
                authority_epoch: 1,
                revision: 1,
                binding: bootstrap.lease_binding,
                issued_at_unix_ms: now,
                expires_at_unix_ms: expiry,
            },
            0,
        )
        .map_err(io::Error::other)?;
    let issuer = DeploymentFinalUseIssuer::create_protected(
        &state.join("issuer"),
        bootstrap.signer_id.clone(),
        bootstrap.policies,
        clock,
        leases.verifier(),
        bootstrap.lease_id.clone(),
        1,
    )?;
    Ok(HostAuthorityInitialized {
        schema_version: 1,
        signer_id: bootstrap.signer_id,
        verifying_key: issuer.trust_key()?.verifying_key,
        lease_id: bootstrap.lease_id,
        lease_revision: 1,
        production_ready: false,
    })
}

/// Open a previously provisioned state with an independently pinned public key
/// and pre-held actual owner pidfd. No missing mount/state/key creates defaults.
pub fn serve_host_authority_session(
    config_file: &Path,
    registration_file: &Path,
    owner_pidfd: OwnedFd,
) -> io::Result<()> {
    serve_host_authority_session_with_text(config_file, registration_file, owner_pidfd, None)
}

/// Open the existing Root service with an optional fixed native UI peer. The
/// same issuer and writer proof serve all lanes; no second Agentd is launched.
pub fn serve_host_authority_session_with_text(
    config_file: &Path,
    registration_file: &Path,
    owner_pidfd: OwnedFd,
    text_ui: Option<(&Path, OwnedFd)>,
) -> io::Result<()> {
    let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
    let registration: HostAuthorityRegistration = read_root_json(registration_file)?;
    if config.schema_version != 1
        || registration.schema_version != 1
        || config.peer_uid == 0
        || config.lease_revision == 0
        || !(1..=30_000).contains(&config.timeout_ms)
        || !(1..=300_000).contains(&config.lifetime_ms)
        || registration.publisher_epoch == 0
        || registration.checkpoint_owner_agent_id != registration.registered_identity.agent_id
    {
        return Err(io::Error::other("invalid service registration"));
    }
    verify_process(&registration, config.peer_uid)?;
    if text_ui.is_some()
        && config.issuer_record_profile
            != crate::authority_host_config::HostIssuerRecordProfile::TextRecovery
    {
        return Err(io::Error::other(
            "native text requires the explicit text_recovery issuer record profile",
        ));
    }
    let (clock, leases, issuer) = open_registered_issuer(&config)?;
    let service = HostAuthorityService::from_registered_owner(
        issuer,
        clock,
        registration.registered_identity.identity()?,
    )?;
    let service = if let Some(writer) = &config.writer {
        service.with_registered_writer(writer.clone(), leases.verifier())?
    } else {
        service
    };
    let service = if let Some(directory) = &config.checkpoint_state_dir {
        if !directory.starts_with(&config.state_dir) || directory == &config.state_dir {
            return Err(io::Error::other("checkpoint must be a private state child"));
        }
        service.with_registered_checkpoint(
            RootAuthorityDirectory::open(directory).map_err(io::Error::other)?,
            registration.publisher_epoch,
            codex_hepta_memory::CognitiveCheckpointPeerLifetime {
                uid: config.peer_uid,
                pid: registration.peer_pid,
                boot_id: registration.boot_id.clone(),
                process_start_ticks: registration.process_start_ticks,
            },
        )?
    } else {
        service
    };
    let service = match (
        &config.consumers,
        &config.sockets.device_frontier,
        &config.sockets.notes_frontier,
    ) {
        (Some(consumers), Some(_), Some(_)) => {
            service.with_registered_consumers(&config.state_dir, consumers)?
        }
        (None, None, None) => service,
        _ => {
            return Err(io::Error::other(
                "both fixed consumer lanes are required together",
            ));
        }
    };
    if let Some((text_file, ui_pidfd)) = text_ui {
        let text: crate::HostAuthorityTextUiRegistration = read_root_json(text_file)?;
        if text.peer_uid != config.peer_uid {
            return Err(io::Error::other(
                "text UI must share the registered Agentd owner UID for its existing private ingress",
            ));
        }
        text.validate(&service)?;
        if [
            &config.sockets.observation,
            &config.sockets.issuer,
            &config.sockets.checkpoint,
        ]
        .into_iter()
        .chain(config.sockets.device_frontier.iter())
        .chain(config.sockets.notes_frontier.iter())
        .any(|path| path == &text.socket_path)
        {
            return Err(io::Error::other("text UI requires a distinct private lane"));
        }
        std::thread::scope(|scope| {
            let worker = scope.spawn(|| {
                service.serve_text_ui(
                    &text,
                    &ui_pidfd,
                    &owner_pidfd,
                    std::time::Duration::from_millis(config.timeout_ms),
                    std::time::Duration::from_millis(config.lifetime_ms),
                )
            });
            let original = serve_lanes(&service, &config, &registration, &owner_pidfd);
            let ui = worker
                .join()
                .map_err(|_| io::Error::other("text UI lane panicked"))?;
            original.and(ui)
        })
    } else {
        serve_lanes(&service, &config, &registration, &owner_pidfd)
    }
}

/// Explicit root administration authorizes a new original registry writer
/// lease and retains its canonical signed proof. Runtime never calls this.
/// Existing lease/proof identity must match exactly; nothing is reset/renewed.
pub fn register_host_writer_authorization(
    config_file: &Path,
) -> io::Result<crate::HostSignedWriterAuthorizationV1> {
    let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
    let writer = config
        .writer
        .as_ref()
        .ok_or_else(|| io::Error::other("writer registration required"))?;
    writer.validate()?;
    let (_, leases, issuer) = open_registered_issuer(&config)?;
    match leases
        .read_lease(&writer.authority_lease.lease_id)
        .map_err(io::Error::other)?
    {
        Some(current) if current.lease != writer.authority_lease => {
            return Err(io::Error::other("existing original writer lease differs"));
        }
        Some(_) => {}
        None => {
            leases
                .put_lease(writer.authority_lease.clone(), 0)
                .map_err(io::Error::other)?;
        }
    }
    issuer.register_writer_authorization(writer, &leases.verifier())
}

pub(super) fn open_registered_issuer(
    config: &HostAuthorityServiceConfig,
) -> io::Result<(
    Arc<HostAuthorityClock>,
    AuthorityLeaseRegistry,
    Arc<DeploymentFinalUseIssuer>,
)> {
    if config.schema_version != 1 || config.lease_revision == 0 {
        return Err(io::Error::other("invalid service config"));
    }
    config.required_bind.verify()?;
    if !config
        .state_dir
        .starts_with(&config.required_bind.mountpoint)
    {
        return Err(io::Error::other("state outside required bind"));
    }
    let root = RootAuthorityDirectory::open(&config.state_dir).map_err(io::Error::other)?;
    let clock = Arc::new(
        HostAuthorityClock::open(root.clone(), CLOCK_OWNER.into()).map_err(io::Error::other)?,
    );
    let frontier = Arc::new(
        HostAuthorityFrontierStore::open(root, LEASE_OWNER.into()).map_err(io::Error::other)?,
    );
    let lease_path = config.state_dir.join("leases");
    // Original registry has initialization behavior; require all original state
    // entries before calling it during runtime, rather than invoking bootstrap.
    read_existing_private(&lease_path.join("authority-leases.lock"))?;
    read_existing_private(&lease_path.join("authority-leases.json"))?;
    let leases = AuthorityLeaseRegistry::open_state_dir_with_trust(
        &lease_path,
        LEASE_OWNER.into(),
        clock.clone(),
        frontier,
    )
    .map_err(io::Error::other)?;
    let open = match config.issuer_record_profile {
        crate::authority_host_config::HostIssuerRecordProfile::Standard => {
            DeploymentFinalUseIssuer::open_protected
        }
        crate::authority_host_config::HostIssuerRecordProfile::TextRecovery => {
            DeploymentFinalUseIssuer::open_protected_text_recovery
        }
    };
    let issuer = Arc::new(open(
        &config.state_dir.join("issuer"),
        clock.clone(),
        leases.verifier(),
        config.lease_id.clone(),
        config.lease_revision,
    )?);
    let key = issuer.trust_key()?;
    if key.key_id != config.signer_id || key.verifying_key != config.expected_verifying_key {
        return Err(io::Error::other("issuer public key pin mismatch"));
    }
    Ok((clock, leases, issuer))
}

fn read_existing_private(path: &Path) -> io::Result<()> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_file()
        || metadata.uid() != 0
        || metadata.mode() & 0o777 != 0o600
        || metadata.nlink() != 1
    {
        return Err(io::Error::other("missing/unsafe existing lease state"));
    }
    Ok(())
}

pub(crate) fn verify_process(registration: &HostAuthorityRegistration, uid: u32) -> io::Result<()> {
    if registration.peer_pid == 0
        || registration.peer_pid > i32::MAX as u32
        || registration.process_start_ticks == 0
    {
        return Err(io::Error::other("invalid owner process"));
    }
    let boot = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?;
    if boot.trim() != registration.boot_id {
        return Err(io::Error::other("registered boot mismatch"));
    }
    let stat = std::fs::read_to_string(format!("/proc/{}/stat", registration.peer_pid))?;
    let start = stat
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok());
    if start != Some(registration.process_start_ticks) {
        return Err(io::Error::other("registered start identity mismatch"));
    }
    let status = std::fs::read_to_string(format!("/proc/{}/status", registration.peer_pid))?;
    let actual_uid = status
        .lines()
        .find_map(|line| line.strip_prefix("Uid:"))
        .map(|line| line.split_whitespace().collect::<Vec<_>>());
    let expected_uid = uid.to_string();
    if actual_uid
        .as_ref()
        .is_none_or(|values| values.len() != 4 || values.iter().any(|value| *value != expected_uid))
        || !status.lines().any(|line| line == "NoNewPrivs:\t1")
        || ["CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"]
            .iter()
            .any(|field| {
                !status.lines().any(|line| {
                    line.strip_prefix(field)
                        .is_some_and(|value| value == ":\t0000000000000000")
                })
            })
        || !status.lines().any(|line| {
            line.strip_prefix("Groups:")
                .is_some_and(|groups| groups.split_whitespace().next().is_none())
        })
    {
        return Err(io::Error::other(
            "owner must have exact dedicated UID, no groups/capabilities and NoNewPrivileges",
        ));
    }
    Ok(())
}

pub(crate) fn owner_alive(owner: &OwnedFd, end: Instant) -> io::Result<()> {
    if Instant::now() >= end {
        return Err(io::Error::other("session lifetime elapsed"));
    }
    let mut descriptor = libc::pollfd {
        fd: owner.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };
    // SAFETY: one valid initialized pollfd is borrowed for this nonblocking call.
    let result = unsafe { libc::poll(&mut descriptor, 1, 0) };
    if result < 0 {
        return Err(io::Error::last_os_error());
    }
    if result != 0 {
        return Err(io::Error::other("owner process exited"));
    }
    Ok(())
}
