//! Explicit Root administration and read-only handoff of existing owner state.
//! These functions are not peer RPCs and never recover a cut from a local hash.

use crate::authority_host_config::*;
use crate::authority_host_runtime::open_registered_issuer;
use crate::authority_host_runtime::verify_process;
use crate::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_memory::CognitiveCheckpointHead;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_memory::CognitiveCheckpointPhase;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use std::fs::File;
use std::io;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::path::PathBuf;

const CHECKPOINT_OWNER: &str = "root-cognitive-checkpoint-v1";

/// Root-created original consumer directories, separate from Root frontiers.
/// The caller must pin this trusted launch input; no peer chooses these paths.
pub struct HostAuthorityLocalConsumers {
    pub device: PathBuf,
    pub notes: PathBuf,
}

/// Explicit fresh bootstrap before releasing the original writer. The caller
/// supplies the original owner's coherently captured genuinely fresh cut.
/// Existing or partial Root namespaces are errors and are never overwritten.
pub fn initialize_host_authority_owners(
    config_file: &Path,
    registration_file: &Path,
    initial_cut: CognitiveRecoveryAnchor,
) -> io::Result<()> {
    let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
    let registration: HostAuthorityRegistration = read_root_json(registration_file)?;
    validate(&config, &registration)?;
    let (clock, leases, issuer) = open_registered_issuer(&config)?;
    let writer = config
        .writer
        .as_ref()
        .ok_or_else(|| io::Error::other("writer absent"))?;
    let service = HostAuthorityService::from_registered_owner(
        issuer.clone(),
        clock.clone(),
        registration.registered_identity.identity()?,
    )?
    .with_registered_writer(writer.clone(), leases.verifier())?;
    let expected = service
        .writer
        .as_ref()
        .ok_or_else(|| io::Error::other("writer absent"))?
        .checkpoint_registration(
            &issuer,
            registration.publisher_epoch,
            peer(&config, &registration),
        )?;
    let checkpoint = config
        .checkpoint_state_dir
        .as_ref()
        .ok_or_else(|| io::Error::other("checkpoint absent"))?;
    let consumers = config
        .consumers
        .as_ref()
        .ok_or_else(|| io::Error::other("consumers absent"))?;
    let directories = [
        checkpoint,
        &consumers.device.state_dir,
        &consumers.notes.state_dir,
    ];
    // Preflight every name before creating any namespace. I/O failure after this
    // point retains partial state; the caller must not retry with replacement.
    for path in directories {
        match std::fs::symlink_metadata(path) {
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            _ => {
                return Err(io::Error::other(
                    "owner namespace already exists or is unavailable",
                ));
            }
        }
    }
    writer.with_live(&leases.verifier(), |_| {
        for path in directories {
            std::fs::DirBuilder::new().mode(0o700).create(path)?;
        }
        File::open(&config.state_dir)?.sync_all()?;
        HostCognitiveCheckpoint::initialize_fresh(
            RootAuthorityDirectory::open(checkpoint).map_err(io::Error::other)?,
            expected,
            initial_cut,
            clock.clone(),
        )
        .map_err(io::Error::other)?;
        let head = issuer.revocations()?;
        for slot in [&consumers.device, &consumers.notes] {
            HostConsumerFrontier::initialize_fresh(
                RootAuthorityDirectory::open(&slot.state_dir).map_err(io::Error::other)?,
                slot.owner_id.clone(),
                &head,
                clock.clone(),
                writer.authority_lease.expires_at_unix_ms,
            )
            .map_err(io::Error::other)?;
        }
        if issuer.revocations()? != head {
            return Err(io::Error::other(
                "issuer changed during explicit owner bootstrap",
            ));
        }
        verify_process(&registration, config.peer_uid)
    })
}

/// Read an existing, exact Current and the two existing original frontiers.
/// No missing input is created. The trusted launcher separately retains and
/// transfers actual Root/consumer pidfds; these public bytes grant no authority.
pub fn capture_host_authority_bootstrap(
    config_file: &Path,
    registration_file: &Path,
    local: HostAuthorityLocalConsumers,
) -> io::Result<HostAuthorityPublicBootstrapV1> {
    let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
    let registration: HostAuthorityRegistration = read_root_json(registration_file)?;
    validate(&config, &registration)?;
    let root_slots = config
        .consumers
        .as_ref()
        .ok_or_else(|| io::Error::other("consumers absent"))?;
    let checkpoint_dir = config
        .checkpoint_state_dir
        .as_ref()
        .ok_or_else(|| io::Error::other("checkpoint absent"))?;
    let mut identities = std::collections::BTreeSet::new();
    for path in [
        checkpoint_dir,
        &root_slots.device.state_dir,
        &root_slots.notes.state_dir,
    ] {
        let metadata = std::fs::metadata(path)?;
        if !identities.insert((metadata.dev(), metadata.ino())) {
            return Err(io::Error::other("Root owner directories alias"));
        }
    }
    for path in [&local.device, &local.notes] {
        let metadata = std::fs::symlink_metadata(path)?;
        if !path.is_absolute()
            || path.canonicalize()? != *path
            || !metadata.is_dir()
            || metadata.uid() != config.peer_uid
            || metadata.gid() != config.peer_gid
            || metadata.mode() & 0o777 != 0o700
            || path.starts_with(&config.required_bind.mountpoint)
        {
            return Err(io::Error::other("unsafe original consumer directory"));
        }
    }
    let device_metadata = std::fs::metadata(&local.device)?;
    let notes_metadata = std::fs::metadata(&local.notes)?;
    if (device_metadata.dev(), device_metadata.ino())
        == (notes_metadata.dev(), notes_metadata.ino())
    {
        return Err(io::Error::other("original consumers alias"));
    }
    let (clock, leases, issuer) = open_registered_issuer(&config)?;
    let writer = config
        .writer
        .as_ref()
        .ok_or_else(|| io::Error::other("writer absent"))?;
    let consumer = peer(&config, &registration);
    let service = HostAuthorityService::from_registered_owner(
        issuer.clone(),
        clock.clone(),
        registration.registered_identity.identity()?,
    )?
    .with_registered_writer(writer.clone(), leases.verifier())?;
    let expected = service
        .writer
        .as_ref()
        .ok_or_else(|| io::Error::other("writer absent"))?
        .checkpoint_registration(&issuer, registration.publisher_epoch, consumer.clone())?;
    writer.with_live(&leases.verifier(), |_| {
        let proof = issuer.retained_writer_authorization(writer)?;
        let checkpoint_dir = config
            .checkpoint_state_dir
            .as_ref()
            .ok_or_else(|| io::Error::other("checkpoint absent"))?;
        HostCognitiveCheckpoint::open(
            RootAuthorityDirectory::open(checkpoint_dir).map_err(io::Error::other)?,
            expected.clone(),
            clock.clone(),
        )
        .map_err(io::Error::other)?;
        let head = HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
            RootAuthorityDirectory::open(checkpoint_dir).map_err(io::Error::other)?,
            CHECKPOINT_OWNER.into(),
        )
        .map_err(io::Error::other)?
        .load(CHECKPOINT_OWNER)
        .map_err(io::Error::other)?;
        if head.writer_binding != expected.writer_binding
            || head.peer_lifetime != expected.peer_lifetime
            || head.owner_agent_id != expected.owner_agent_id
            || head.publisher_epoch != expected.publisher_epoch
            || head.phase != CognitiveCheckpointPhase::Current
            || head.proposal.is_some()
            || head.counter == 0
        {
            return Err(io::Error::other(
                "Root checkpoint is not this exact Current",
            ));
        }
        let revocations = issuer.revocations()?;
        let read = |slot: &HostAuthorityConsumerConfig,
                    local_state_dir: PathBuf|
         -> io::Result<HostAuthorityPublicConsumerV1> {
            HostConsumerFrontier::open(
                RootAuthorityDirectory::open(&slot.state_dir).map_err(io::Error::other)?,
                slot.owner_id.clone(),
                clock.clone(),
                writer.authority_lease.expires_at_unix_ms,
            )
            .map_err(io::Error::other)?;
            let frontier = HostAuthorityFrontierStore::<FinalUseFrontier>::open(
                RootAuthorityDirectory::open(&slot.state_dir).map_err(io::Error::other)?,
                slot.owner_id.clone(),
            )
            .map_err(io::Error::other)?
            .load(&slot.owner_id)
            .map_err(io::Error::other)?;
            Ok(HostAuthorityPublicConsumerV1 {
                local_state_dir,
                owner_id: slot.owner_id.clone(),
                frontier,
            })
        };
        let slots = config
            .consumers
            .as_ref()
            .ok_or_else(|| io::Error::other("consumers absent"))?;
        let stat = std::fs::read_to_string("/proc/self/stat")?;
        let start = stat
            .rsplit_once(") ")
            .and_then(|(_, fields)| fields.split_whitespace().nth(19))
            .and_then(|value| value.parse().ok())
            .filter(|ticks: &u64| *ticks != 0)
            .ok_or_else(|| io::Error::other("invalid actual Root start"))?;
        let bundle = HostAuthorityPublicBootstrapV1 {
            schema_version: 1,
            operation: HOST_AUTHORITY_BOOTSTRAP_V1.into(),
            root: CognitiveCheckpointPeerLifetime {
                uid: 0,
                pid: std::process::id(),
                boot_id: registration.boot_id.clone(),
                process_start_ticks: start,
            },
            consumer,
            registered_identity: registration.registered_identity.clone(),
            issuer_key: issuer.trust_key()?.into(),
            revocations: revocations.clone(),
            writer: writer.clone(),
            writer_proof: proof,
            checkpoint: head,
            consumers: HostAuthorityPublicConsumersV1 {
                device: read(&slots.device, local.device)?,
                notes: read(&slots.notes, local.notes)?,
            },
            sockets: HostAuthorityFiveLanePathsV1 {
                observation: config.sockets.observation.clone(),
                issuer: config.sockets.issuer.clone(),
                checkpoint: config.sockets.checkpoint.clone(),
                device_frontier: config
                    .sockets
                    .device_frontier
                    .clone()
                    .ok_or_else(|| io::Error::other("device lane absent"))?,
                notes_frontier: config
                    .sockets
                    .notes_frontier
                    .clone()
                    .ok_or_else(|| io::Error::other("Notes lane absent"))?,
            },
        };
        if issuer.revocations()? != revocations {
            return Err(io::Error::other("issuer changed during handoff"));
        }
        crate::authority_host_service::validate_observation_lease(
            &writer.authority_lease,
            &revocations,
            clock.now_unix_ms().map_err(io::Error::other)?,
        )?;
        verify_process(&registration, config.peer_uid)?;
        Ok(bundle)
    })
}

fn peer(
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
) -> CognitiveCheckpointPeerLifetime {
    CognitiveCheckpointPeerLifetime {
        uid: config.peer_uid,
        pid: registration.peer_pid,
        boot_id: registration.boot_id.clone(),
        process_start_ticks: registration.process_start_ticks,
    }
}

fn validate(
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
) -> io::Result<()> {
    if config.schema_version != 1
        || registration.schema_version != 1
        || config.peer_uid == 0
        || config.peer_gid == 0
        || registration.publisher_epoch == 0
        || registration.checkpoint_owner_agent_id != registration.registered_identity.agent_id
    {
        return Err(io::Error::other("invalid trusted owner registration"));
    }
    verify_process(registration, config.peer_uid)?;
    let checkpoint = config
        .checkpoint_state_dir
        .as_ref()
        .ok_or_else(|| io::Error::other("checkpoint absent"))?;
    let consumers = config
        .consumers
        .as_ref()
        .ok_or_else(|| io::Error::other("consumers absent"))?;
    let directories = [
        checkpoint,
        &consumers.device.state_dir,
        &consumers.notes.state_dir,
    ];
    for path in directories {
        if path.parent() != Some(config.state_dir.as_path()) || !path.is_absolute() {
            return Err(io::Error::other(
                "Root owner namespace must be a direct private state child",
            ));
        }
    }
    if checkpoint == &consumers.device.state_dir
        || checkpoint == &consumers.notes.state_dir
        || consumers.device.state_dir == consumers.notes.state_dir
        || consumers.device.owner_id != config.signer_id
        || consumers.notes.owner_id != config.signer_id
    {
        return Err(io::Error::other("aliased or foreign Root owner namespace"));
    }
    Ok(())
}
