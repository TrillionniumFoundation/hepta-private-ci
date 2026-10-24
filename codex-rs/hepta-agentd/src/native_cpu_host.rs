//! One final-image Agentd owner, bootstrapped only by its actual native Root.
use super::*;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::RootFinalUseFrontierClient;
use codex_hepta_contracts::RootPeerIdentity;
use codex_hepta_memory::CognitiveCheckpointCommand;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::CognitiveCheckpointRequest;
use codex_hepta_memory::CognitiveCheckpointResponse;
use codex_hepta_memory::CognitiveCheckpointStatus;
use codex_hepta_memory::CognitiveCheckpointTransport;
use codex_hepta_memory::ProductionHos2Target;
use std::io::Read;
use std::os::unix::fs::DirBuilderExt;

pub(super) fn run(boot: NativeBootstrap, device: Arc<crate::AgentdHos2Device>) -> io::Result<()> {
    let deadline = end()?;
    let root_peer = peer(1, 0)?;
    let root_fd = pidfd(1)?;
    let name = boot.owner_runtime_name()?;
    let kernel_bootstrap = boot.bytes[..boot.byte_count()].to_vec();
    let allow_effects = !device.is_history_only();
    let launch_stream = connect(&Path::new(RUNTIME).join(format!("{name}.launch")), deadline)?;
    let mut launch = crate::RootNotesLaunchChannel::from_peer_stream(
        launch_stream,
        root_peer.clone(),
        root_fd.try_clone()?,
        deadline,
    )?;
    let (frame, mut descriptors) = launch.read(deadline)?;
    let crate::RootNotesLaunchFrame::OriginalBootstrapV1 {
        schema_version: 1,
        launch_nonce,
    } = frame
    else {
        return Err(invalid(
            "native CPU launch expected the original sealed bootstrap",
        ));
    };
    if descriptors.len() != 2 {
        return Err(invalid("sealed bootstrap and original Root pidfd required"));
    }
    let transferred_root = descriptors.pop().unwrap();
    launch.require_same_peer_pidfd(&transferred_root, deadline)?;
    let mut sealed = File::from(descriptors.pop().unwrap());
    let length = sealed.metadata()?.len();
    if length == 0 || length > crate::HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 {
        return Err(invalid("bootstrap bytes bound"));
    }
    crate::authority_host_bootstrap_seal::validate_sealed(&sealed, length)?;
    let mut bytes = Vec::new();
    sealed.by_ref().take(length + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != length {
        return Err(invalid("sealed bootstrap bytes changed"));
    }
    let bundle: crate::HostAuthorityPublicBootstrapV1 =
        serde_json::from_slice(&bytes).map_err(error)?;
    if bundle.schema_version != 1
        || bundle.operation != crate::HOST_AUTHORITY_BOOTSTRAP_V1
        || bundle.root != root_peer
        || bundle.consumer != peer(std::process::id(), 60001)?
        || bundle.checkpoint.peer_lifetime != bundle.consumer
    {
        return Err(invalid("original Root bootstrap role/lifetime mismatch"));
    }
    let identity = crate::authority_host_config::registered_identity(&bundle.registered_identity)?;
    std::env::set_current_dir(&identity.workspace)?;
    let config = crate::config::NativeCpuConfig::load(
        identity.fleet_root.clone(),
        identity.agent_id.clone(),
        identity.spawn_generation,
        identity.home_root.clone(),
        identity.run_root.clone(),
        identity.home_root.clone(),
        identity.workspace,
    )
    .map_err(error)?;
    // All five connections precede the first awaited feed read. The Root lane
    // listener intentionally accepts the complete fixed set before serving.
    let observation = connect(&bundle.sockets.observation, deadline)?;
    let issuer = connect(&bundle.sockets.issuer, deadline)?;
    let checkpoint = connect(&bundle.sockets.checkpoint, deadline)?;
    let device_frontier = connect(&bundle.sockets.device_frontier, deadline)?;
    let notes_frontier = connect(&bundle.sockets.notes_frontier, deadline)?;
    let runtime = runtime()?;
    runtime.block_on(async move {
        let writer=&bundle.writer;
        let session=Arc::new(crate::AgentdRootAuthoritySession::connect(observation,
            crate::AgentdRootAuthorityPeer {pid:root_peer.pid,boot_id:root_peer.boot_id.clone(),process_start_ticks:root_peer.process_start_ticks},
            transferred_root.try_clone()?,Duration::from_millis(500),remaining(deadline)?,crate::AgentdRootWriterTrust {
                issuer_id:bundle.issuer_key.key_id.clone(),verifying_key:bundle.issuer_key.verifying_key,
                agent_id:writer.registered_agent_id.clone(),spawn_generation:writer.spawn_generation,owner_epoch:writer.owner_epoch,
                local_lease_id:writer.local_lease_id.clone(),local_lease_generation:writer.local_lease_generation,
                authority_lease:writer.authority_lease.clone(),
            }).await.map_err(error)?);
        let copied=bundle.clone();let clock=session.clock();let head=session.revocations().map_err(error)?;
        let consumers_root=transferred_root.try_clone()?;
        let owners=tokio::task::spawn_blocking(move || ->io::Result<Vec<FinalUseAuthority>> {
            let mut owners=Vec::new();
            for (slot,stream) in [(&copied.consumers.device,device_frontier),(&copied.consumers.notes,notes_frontier)] {
                if slot.owner_id!=copied.issuer_key.key_id {return Err(invalid("canonical consumer owner differs"));}
                let frontier=Arc::new(RootFinalUseFrontierClient::from_stream(stream,slot.owner_id.clone(),
                    RootPeerIdentity {pid:copied.root.pid,boot_id:copied.root.boot_id.clone(),process_start_ticks:copied.root.process_start_ticks},
                    consumers_root.try_clone()?,IO_TIMEOUT,remaining(deadline)?).map_err(error)?);
                match std::fs::DirBuilder::new().mode(0o700).create(&slot.local_state_dir) {
                    Ok(())=>{},Err(e) if e.kind()==io::ErrorKind::AlreadyExists=>{},Err(e)=>return Err(e),
                }
                let owner=FinalUseAuthority::open_state_dir_with_issuer_keys(&slot.local_state_dir,slot.owner_id.clone(),
                    vec![FinalUseIssuerTrustKey::from(copied.issuer_key.clone())],head.clone(),clock.clone(),frontier).map_err(error)?;
                if owner.frontier().map_err(error)?!=slot.frontier {return Err(invalid("original consumer frontier differs from Root handoff"));}
                owners.push(owner);
            }
            Ok(owners)
        }).await.map_err(error)??;
        session.activate_final_use_owners(owners.clone()).await.map_err(error)?;
        let transport=Arc::new(crate::AgentdUnixCognitiveCheckpointTransport::from_stream(checkpoint,
            crate::AgentdCognitiveCheckpointPeer {pid:root_peer.pid,boot_id:root_peer.boot_id.clone(),process_start_ticks:root_peer.process_start_ticks},
            transferred_root.try_clone()?,IO_TIMEOUT,remaining(deadline)?).map_err(error)?);
        let read=CognitiveCheckpointRequest {schema_version:1,operation:"runtime.cognitive.checkpoint.v1".into(),
            request_id:format!("{:016x}{:016x}",bundle.checkpoint.publisher_epoch,1),command:CognitiveCheckpointCommand::ReadHead,
            expected:None,proposal:None};
        let response:CognitiveCheckpointResponse=serde_json::from_slice(&transport.exchange(&serde_json::to_vec(&read).map_err(error)?)
            .await.map_err(error)?).map_err(error)?;
        if response.status!=CognitiveCheckpointStatus::Ack || response.request_id!=read.request_id {return Err(invalid("independent initial Current refused"));}
        let current=CognitiveCheckpointReceipt {token:response.token.ok_or_else(||invalid("missing opaque Current token"))?,
            head:response.head.ok_or_else(||invalid("missing complete Current head"))?};
        if current.head!=bundle.checkpoint {return Err(invalid("original Current changed before exact recovery"));}
        let (host,coordinator)=crate::AgentdProductionWriterHost::open_with_protected_recovery_and_ready_for_identity(config.identity(),
            session.authority(),session.verifier(),writer.local_lease_id.clone(),writer.local_lease_generation,
            crate::AgentdProtectedCheckpointInputs {transport,current_receipt:current,deadline:IO_TIMEOUT},
            move || async move {
                tokio::task::spawn_blocking(move || ->io::Result<()> {
                    launch.send(&crate::RootNotesLaunchFrame::RecoveredOwnerReadyV1 {schema_version:1,launch_nonce:launch_nonce.clone()},&[],deadline)?;
                    let (frame,rights)=launch.read(deadline)?;
                    if !rights.is_empty() || !matches!(frame,crate::RootNotesLaunchFrame::RecoveredOwnerRegisteredV1 {schema_version:1,launch_nonce:ref actual} if actual==&launch_nonce) {
                        return Err(invalid("same Root did not confirm recovered owner registration"));
                    }
                    Ok(())
                }).await.map_err(|e|crate::AgentdError::Protocol(e.to_string()))??;
                Ok(())
            }).await.map_err(error)?;
        // Capture original retained state immediately after the protected
        // recovery factory, before attach_target and the normal monitor start.
        // Later Inspect reports this initial observation, never a claim that
        // the live store must still have the same unresolved outcome.
        let startup_retained = host.writer().retained_pending_hos2(16).await.map_err(error)?
            .into_iter().map(|(occurrence_key, original)| commands::StartupRetained {
                occurrence_key, topic:original.topic, payload_json:original.payload_json,
                state:original.state,
            }).collect::<Vec<_>>();
        let grants=Arc::new(crate::AgentdUnixFinalUseGrantProvider::from_root_stream(issuer,root_peer.pid,
            transferred_root.try_clone()?,IO_TIMEOUT,remaining(deadline)?).map_err(error)?);
        let target=Arc::new(ProductionHos2Target::new(device.clone()));
        let host=Arc::new(host.attach_target(owners[0].clone(),target.clone(),grants).map_err(error)?);
        let config=config.with_production_writer_host(host.clone()).map_err(error)?;
        let sender=config.original_objective_sender(coordinator,IO_TIMEOUT).map_err(error)?;
        sender.acknowledge_owner_cut().await.map_err(error)?;
        let rpc_stream=connect(&Path::new(RUNTIME).join(format!("{name}.rpc")),deadline)?;
        let release_stream=connect(&Path::new(RUNTIME).join(format!("{name}.release")),deadline)?;
        let release_rpc=commands::Rpc::new(release_stream,&root_peer,transferred_root.try_clone()?,deadline)?;
        let rpc=commands::Rpc::new(rpc_stream,&root_peer,transferred_root,deadline)?;
        // Retain these exact original owners through the authenticated release
        // observation/ACK. No worker can mutate the retired SQLite pool.
        let retained_host=host.clone();
        let ingress=Arc::new(crate::native_cpu_ingress::NativeCpuIngress::new());
        let control=commands::Owner {host,device,target,sender,root:session.clone(),
            device_owner:owners[0].clone(),notes_owner:owners[1].clone(),bundle,queue:None,
            startup_retained,kernel_bootstrap,ingress:ingress.clone()};
        let released=crate::native_cpu_runtime::run_native_cpu_owner_until(config,session.clone(),ingress,
            allow_effects,control.run(rpc)).await.map_err(error)?;
        tokio::task::spawn_blocking(move || commands::finish_release(release_rpc,released))
            .await.map_err(error)??;
        drop(retained_host);
        drop(session);
        Ok(())
    })
}
