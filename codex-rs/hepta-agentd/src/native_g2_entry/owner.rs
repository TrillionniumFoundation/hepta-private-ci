//! Actual original owner operations. Commands are consumed only from Root's
//! fixed process-bound channel; no host plan installs a signer, lease or cut.

use super::boot::Boot;
use super::ipc;
use super::supervisor;
use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdG2NativeImage;
use codex_hepta_agentd::AgentdG2NativeOperationHost;
use codex_hepta_agentd::AgentdIdentity;
use codex_hepta_agentd::attach_g2_native_operation_host;
use codex_hepta_agentd::drop_root_native_owner_credentials;
use codex_hepta_agentd::receive_root_production_inputs;
use codex_hepta_agentd::receive_root_production_writer_handoff;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_memory::HOS2_DESTINATION_V1;
use codex_hepta_memory::HOS2_INSTALL_TOPIC_V1;
use codex_hepta_memory::Hos2DeliveryId;
use codex_hepta_memory::ProductionQueuedReceipt;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::path::Path;
use std::time::Duration;

#[derive(Deserialize, Serialize)]
#[serde(tag = "command", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Command {
    Observe,
    Prepare {
        operation_id: String,
        expected_revision: u64,
        cap_ns: u64,
    },
    Dispatch {
        queued: ProductionQueuedReceipt,
    },
    Retire {
        through: Hos2DeliveryId,
    },
    Current,
    Reconcile {
        occurrence_key: String,
    },
}

pub(super) fn run(
    boot: Boot,
    control: File,
    launch: &Path,
    requests: &Path,
) -> Result<(), Box<dyn std::error::Error>> {
    // Authenticate the actual native image before relinquishing Root. This
    // read-only attach creates neither a source owner nor a FinalUse grant.
    let discovery = std::sync::Arc::new(
        codex_hepta_agentd::AgentdHos2Device::from_g2_initial_bootstrap(
            control.try_clone()?,
            &boot.page,
        )?,
    );
    drop_root_native_owner_credentials(/*expected_uid*/ 60001, /*expected_gid*/ 60001)?;
    let _read_only_observer = if boot.role == super::boot::Role::Recovery {
        Some(super::native_observer::spawn(discovery)?)
    } else {
        None
    };
    let (spec, handoff) = supervisor::receive_original(supervisor::connect_parent(launch)?)?;
    ipc::wait_selected(&handoff)?;
    let (sealed, root, writer) =
        receive_root_production_writer_handoff(handoff, Duration::from_millis(500))?;
    let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(spec.fleet_root.clone())?)?;
    let record = registry.load_agent(&spec.agent_id)?;
    let identity = AgentdIdentity {
        agent_id: spec.agent_id.clone(),
        layout: record.layout.clone(),
        spawn_generation: spec.generation,
        fleet_root: spec.fleet_root.clone(),
        workspace: spec.workspace.clone(),
        resources: record.manifest.resources,
        home_root: spec.home_root.clone(),
        run_root: spec.run_root.clone(),
        control_socket: spec.control_socket.clone(),
        app_server_socket: record.layout.app_server_socket().to_path_buf(),
    };
    std::env::set_current_dir(&spec.workspace)?;
    // The original drop has completed before the first runtime thread exists.
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(1)
        .enable_all()
        .build()?;
    let retained_root = root.try_clone()?;
    let (config, owner) = runtime.block_on(async {
        let inputs = receive_root_production_inputs(
            sealed,
            root,
            &identity,
            Duration::from_millis(500),
            Duration::from_secs(300),
        )
        .await?;
        let mut config =
            AgentdConfig::from_root_writer_handoff(&inputs, writer, std::env::current_dir()?)?;
        let owner = attach_g2_native_operation_host(
            &mut config,
            inputs,
            control,
            AgentdG2NativeImage::InitialV3(&boot.page),
        )
        .await?;
        Ok::<_, Box<dyn std::error::Error>>((config, owner))
    })?;
    let _config = config; // Retain the original writer lock for this whole role.
    let stream = supervisor::connect_parent(requests)?;
    let mut channel = HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer { uid: 0, pid: 1 },
            timeout: Duration::from_millis(500),
            lifetime: Duration::from_secs(300),
            request_bound: 32_768,
            response_bound: 32_768,
        },
        retained_root,
    )?;
    while channel.exchange(|bytes| {
        let command =
            serde_json::from_slice(bytes).map_err(|_| HostIssuerTransportError::InvalidRequest)?;
        let value = runtime
            .block_on(execute(&owner, command))
            .map_err(|_| HostIssuerTransportError::Unavailable)?;
        serde_json::to_vec(&value).map_err(|_| HostIssuerTransportError::Unavailable)
    })? {}
    Ok(())
}

async fn execute(
    owner: &AgentdG2NativeOperationHost,
    command: Command,
) -> Result<serde_json::Value, Box<dyn std::error::Error>> {
    match command {
        Command::Observe => {
            Ok(super::native_observer::value(
                owner.read_usage(/*request_id*/ 1)?,
            ))
        }
        Command::Prepare {
            operation_id,
            expected_revision,
            cap_ns,
        } => {
            let usage = owner.read_usage(/*request_id*/ 2)?;
            let writer = owner.writer();
            let sequence = writer
                .next_hos2_delivery_sequence(usage.boot_id, usage.observer_space_id)
                .await?;
            let request = owner.install_request(sequence, expected_revision, cap_ns)?;
            let payload = request.to_json()?;
            let operation = OperationIntentV1::new(
                StableId::new(operation_id)?,
                StableId::new(writer.owner_agent_id().as_str())?,
                StableId::new(HOS2_DESTINATION_V1)?,
                Digest32::of_bytes(payload.as_bytes()),
                request.scope_digest(),
                Generation::new(writer.generation())?,
                /*expected_predecessor*/ None,
            )?;
            Ok(serde_json::to_value(
                writer
                    .prepare_operation(operation, HOS2_INSTALL_TOPIC_V1, payload)
                    .await?,
            )?)
        }
        Command::Dispatch { queued } => Ok(serde_json::to_value(
            owner.host().dispatch_with_grant_provider(queued).await?,
        )?),
        Command::Retire { through } => {
            let retired = owner.retire_through(&through).await?;
            Ok(
                serde_json::json!({"retired_through":retired.retired_through,"next_sequence":retired.next_sequence}),
            )
        }
        Command::Reconcile { occurrence_key } => {
            let retained = owner
                .writer()
                .retained_hos2_terminal(&occurrence_key)
                .await?;
            let request =
                codex_hepta_memory::Hos2InstallBudgetV1::from_json(&retained.request_json)?;
            let observed = owner.observe_retained_native_delivery(&request).await?;
            let original: serde_json::Value = serde_json::from_str(&retained.terminal_json)?;
            if original["observation"] != serde_json::to_value(&observed)? {
                return Err(
                    "actual retained native history differs from original durable terminal".into(),
                );
            }
            Ok(serde_json::json!({"retained":retained,"observation":observed}))
        }
        Command::Current => {
            let current = owner.acknowledge_current_receipt().await?;
            let (device, notes) = owner.consumer_frontiers().await?;
            Ok(
                serde_json::json!({"current":current,"device_frontier":device,"notes_frontier":notes,"database_path":owner.writer().database_path()}),
            )
        }
    }
}
