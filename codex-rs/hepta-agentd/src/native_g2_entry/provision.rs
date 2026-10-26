//! Fresh native administration through original Registry/Root factories only.

use super::boot::Boot;
use super::paths;
use codex_hepta_agentd::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::HOS2_DESTINATION_V1;
use codex_hepta_memory::Hos2DeliveryId;
use codex_hepta_memory::Hos2InstallBudgetV1;
use codex_hepta_paths::HeptaFleetRoot;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

pub(super) const AUTHORITY: &str = "/state/authority";
pub(super) const SIGNER: &str = "native-g2-original-root";
pub(super) const CONFIG: &str = "/state/service-initial.json";
pub(super) const REGISTRATION: &str = "/state/registration-initial.json";
pub(super) const WRITER_LIFETIME_MS: u64 = 20_000;

pub(super) fn fresh_registry() -> Result<(FleetRegistry, AgentId), Box<dyn std::error::Error>> {
    let fleet = HeptaFleetRoot::parse(PathBuf::from(paths::FLEET))?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let agent = AgentId::parse("bf5c80be-3b26-4fd2-95e1-32f395538f6c")?;
    registry.register(AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(paths::WORKSPACE, &fleet)?,
        ResourceBudget {
            max_concurrent_turns: 1,
            memory_limit_mib: 128,
            max_tool_processes: 1,
            turn_queue_capacity: 1,
        },
    )?)?;
    Ok((registry, agent))
}

pub(super) fn initialize_authority(
    boot: &Boot,
    agent: &AgentId,
) -> Result<HostAuthorityInitialized, Box<dyn std::error::Error>> {
    use std::os::unix::fs::MetadataExt;
    let metadata = std::fs::metadata(paths::STATE)?;
    let policies = [112, 128]
        .into_iter()
        .map(|offset| {
            let request = Hos2InstallBudgetV1 {
                schema_version: 1,
                delivery: Hos2DeliveryId::new(
                    boot.page[96..112].try_into().unwrap(),
                    boot.page[offset..offset + 16].try_into().unwrap(),
                    /*sequence*/ 1,
                )?,
                manage_slot: 2,
                manage_generation: 1,
                expected_revision: 1,
                period_ns: 100_000_000,
                cap_ns: 0,
            };
            Ok::<_, Box<dyn std::error::Error>>(DeploymentGrantPolicy {
                subject_id: agent.to_string(),
                destination_id: HOS2_DESTINATION_V1.into(),
                scope_sha256: *request.scope_digest().as_array(),
                lifetime_ms: 1_000,
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    let policy_bytes = serde_json::to_vec(&policies)?;
    let bootstrap = HostAuthorityBootstrap {
        schema_version: 1,
        required_bind: HostAuthorityBindIdentity {
            mountpoint: paths::STATE.into(),
            source_path: paths::STATE.into(),
            device: metadata.dev(),
            inode: metadata.ino(),
        },
        signer_id: SIGNER.into(),
        policies,
        lease_id: "native-g2-original-issuer".into(),
        lease_binding: AuthorityLeaseBinding {
            principal_id: agent.to_string(),
            operation_class: "runtime.agentd.production_operation".into(),
            destination_id: HOS2_DESTINATION_V1.into(),
            scope_sha256: *codex_hepta_types::Digest32::of_bytes(&policy_bytes).as_array(),
            payload_sha256: *codex_hepta_types::Digest32::of_bytes(
                b"native-g2-original-root-policy-v1",
            )
            .as_array(),
        },
        lease_lifetime_ms: 300_000,
    };
    let path = Path::new("/state/root-bootstrap.json");
    paths::root_json(path, &bootstrap)?;
    Ok(initialize_host_authority(Path::new(AUTHORITY), path)?)
}

pub(super) fn register_initial(
    boot: &Boot,
    registry: &FleetRegistry,
    agent: &AgentId,
    initialized: HostAuthorityInitialized,
) -> Result<
    (
        HostAuthorityServiceConfig,
        HostAuthorityRegistration,
        HostSignedWriterAuthorizationV1,
    ),
    Box<dyn std::error::Error>,
> {
    use std::os::unix::fs::MetadataExt;
    let record = registry.load_agent(agent)?;
    let generation = record.lifecycle.generation;
    let metadata = std::fs::metadata(paths::STATE)?;
    let now = now_ms()?;
    let writer = HostAuthorityWriterRegistration {
        registered_agent_id: agent.clone(),
        spawn_generation: generation,
        owner_epoch: 1,
        local_lease_id: "native-g2-original-writer".into(),
        local_lease_generation: 1,
        authority_lease: AuthorityLease {
            schema_version: 1,
            lease_id: "native-g2-original-writer-authority".into(),
            revision: 1,
            authority_epoch: 1,
            binding: AuthorityLeaseBinding {
                principal_id: agent.to_string(),
                operation_class: "runtime.agentd.production_writer".into(),
                destination_id: "native-g2-original-cognitive-owner".into(),
                scope_sha256: *codex_hepta_types::Digest32::of_bytes(&serde_json::to_vec(
                    &record.manifest,
                )?)
                .as_array(),
                payload_sha256: *codex_hepta_types::Digest32::of_bytes(
                    b"native-g2-original-writer-v1",
                )
                .as_array(),
            },
            issued_at_unix_ms: now,
            expires_at_unix_ms: now
                .checked_add(WRITER_LIFETIME_MS)
                .ok_or("writer expiry overflow")?,
        },
    };
    let sockets = |name: &str| Path::new(paths::LANES).join(name);
    let config = HostAuthorityServiceConfig {
        schema_version: 1,
        state_dir: AUTHORITY.into(),
        required_bind: HostAuthorityBindIdentity {
            mountpoint: paths::STATE.into(),
            source_path: paths::STATE.into(),
            device: metadata.dev(),
            inode: metadata.ino(),
        },
        signer_id: initialized.signer_id,
        expected_verifying_key: initialized.verifying_key,
        lease_id: initialized.lease_id,
        lease_revision: initialized.lease_revision,
        writer: Some(writer),
        checkpoint_state_dir: Some(Path::new(AUTHORITY).join("checkpoint")),
        consumers: Some(HostAuthorityConsumersConfig {
            device: HostAuthorityConsumerConfig {
                state_dir: Path::new(AUTHORITY).join("device"),
                owner_id: SIGNER.into(),
            },
            notes: HostAuthorityConsumerConfig {
                state_dir: Path::new(AUTHORITY).join("notes"),
                owner_id: SIGNER.into(),
            },
        }),
        sockets: HostAuthoritySocketPaths {
            observation: sockets("observation.sock"),
            issuer: sockets("issuer.sock"),
            checkpoint: sockets("checkpoint.sock"),
            device_frontier: Some(sockets("device-frontier.sock")),
            notes_frontier: Some(sockets("notes-frontier.sock")),
        },
        peer_uid: 60001,
        peer_gid: 60001,
        timeout_ms: 500,
        lifetime_ms: 120_000,
        issuer_record_profile: HostIssuerRecordProfile::Standard,
    };
    let registration = HostAuthorityRegistration {
        schema_version: 1,
        peer_pid: boot.pids[0],
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
            .trim()
            .to_owned(),
        process_start_ticks: start_ticks(boot.pids[0])?,
        registered_identity: HostAuthorityRegisteredIdentity {
            agent_id: agent.clone(),
            spawn_generation: generation,
            fleet_root: paths::FLEET.into(),
            workspace: paths::WORKSPACE.into(),
            resources: record.manifest.resources,
        },
        checkpoint_owner_agent_id: agent.clone(),
        publisher_epoch: 1,
    };
    paths::root_json(Path::new(CONFIG), &config)?;
    paths::root_json(Path::new(REGISTRATION), &registration)?;
    Ok((
        config,
        registration,
        register_host_writer_authorization(Path::new(CONFIG))?,
    ))
}

pub(super) fn start_ticks(pid: u32) -> Result<u64, Box<dyn std::error::Error>> {
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    Ok(stat
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .ok_or("native process birth unavailable")?
        .parse()?)
}

pub(super) fn now_ms() -> Result<u64, Box<dyn std::error::Error>> {
    Ok(u64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?)
}
