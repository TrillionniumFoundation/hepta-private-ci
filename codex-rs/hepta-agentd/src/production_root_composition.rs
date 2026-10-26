//! Trusted five-lane assembly of the original production owners.
//!
//! All descriptors and the public bundle come from the trusted launcher. This
//! module never discovers peers, creates a signer, provisions a checkpoint, or
//! substitutes a local database digest for the protected Current receipt.

use std::os::fd::OwnedFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::AuthorityFrontierStore;
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
use codex_hepta_memory::FinalUseProductionOutboxTarget;
use codex_hepta_memory::ProtectedCognitiveCheckpoint;

use crate::AgentdCognitiveCheckpointPeer;
use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdProductionOperationRuntimeConfig;
use crate::AgentdProductionWriterHost;
use crate::AgentdProtectedCheckpointInputs;
use crate::AgentdRootAuthorityPeer;
use crate::AgentdRootAuthoritySession;
use crate::AgentdRootWriterTrust;
use crate::AgentdUnixCognitiveCheckpointTransport;
use crate::AgentdUnixFinalUseGrantProvider;
use crate::HOST_AUTHORITY_BOOTSTRAP_V1;
use crate::HostAuthorityPublicBootstrapV1;
use crate::root_observation_diagnostic::AttachStage;
use crate::root_writer_proof::VerifiedRootWriterProof;

/// Fixed-purpose lanes. There is no path-based reconnect or lane selection.
pub struct AgentdRootAuthorityLanes {
    pub observation: UnixStream,
    pub issuer: UnixStream,
    pub checkpoint: UnixStream,
    pub device_frontier: UnixStream,
    pub notes_frontier: UnixStream,
    pub root_pidfd: OwnedFd,
}

/// Explicit destination selected by the trusted host. Both original consumers
/// are opened even when only one destination is attached. Their journals and
/// protected frontiers stay separate, using the same canonical signer.
pub enum AgentdRootPrimaryTarget {
    Device(Arc<dyn FinalUseProductionOutboxTarget>),
    Notes(Arc<dyn FinalUseProductionOutboxTarget>),
}

pub struct AgentdRootProductionInputs {
    pub bootstrap: HostAuthorityPublicBootstrapV1,
    pub lanes: AgentdRootAuthorityLanes,
    pub target: AgentdRootPrimaryTarget,
    pub timeout: Duration,
    pub lifetime: Duration,
    pub reconcile_interval: Duration,
}

/// Keep this guard alive until the original daemon and its writer have shut
/// down. Dropping it fences the protected clock/live verifier immediately.
/// Initialization and shutdown must be awaited; they are not cancel-safe.
pub struct AgentdRootProductionAttachment {
    session: AgentdRootAuthoritySession,
    host: Arc<AgentdProductionWriterHost>,
    checkpoint: Arc<ProtectedCognitiveCheckpoint<AgentdUnixCognitiveCheckpointTransport>>,
    issuer: Arc<AgentdUnixFinalUseGrantProvider>,
    device: FinalUseAuthority,
    notes: FinalUseAuthority,
}

impl AgentdRootProductionAttachment {
    /// The recovered original owner; Agentd runtime attaches dispatchers from
    /// its installed operation configuration without opening another store.
    pub fn writer_host(&self) -> Arc<AgentdProductionWriterHost> {
        Arc::clone(&self.host)
    }

    /// Call after the daemon/config and all externally retained host clones
    /// have been released. Keep the live Root session until pool close finishes.
    pub async fn close(self) -> Result<(), AgentdError> {
        let Self {
            session,
            host,
            checkpoint,
            issuer,
            device,
            notes,
        } = self;
        let host = Arc::try_unwrap(host)
            .map_err(|_| refused("protected shutdown still has shared host handles"))?;
        let result = host.close().await;
        drop((checkpoint, issuer, device, notes, session));
        result
    }

    pub fn checkpoint(
        &self,
    ) -> Arc<ProtectedCognitiveCheckpoint<AgentdUnixCognitiveCheckpointTransport>> {
        Arc::clone(&self.checkpoint)
    }

    /// The original typed issuer remains the only signer. Call its synchronous
    /// operations from a bounded blocking worker after retaining the intent.
    pub fn issuer(&self) -> Arc<AgentdUnixFinalUseGrantProvider> {
        Arc::clone(&self.issuer)
    }

    pub fn device_final_use(&self) -> FinalUseAuthority {
        self.device.clone()
    }

    pub fn notes_final_use(&self) -> FinalUseAuthority {
        self.notes.clone()
    }

    pub fn verify_live(&self) -> Result<(), AgentdError> {
        let authority = self.session.authority();
        self.session
            .verifier()
            .verify(&authority, &authority.agent_id)
            .map_err(AgentdError::GenerationFenced)
    }
}

/// Assemble and install the real original owner atomically. Every ordinary
/// failure after SQLite opens awaits its original pool-close barrier. A late
/// failure may leave original durable authority state advanced; it is never
/// deleted, reset, or silently re-provisioned for a retry.
pub async fn attach_root_production_host(
    config: &mut AgentdConfig,
    inputs: AgentdRootProductionInputs,
) -> Result<AgentdRootProductionAttachment, AgentdError> {
    config.require_unconfigured_production_hosts()?;
    let bundle = inputs.bootstrap;
    validate_bundle(config, &bundle)?;
    if inputs.timeout.is_zero()
        || inputs.timeout > Duration::from_millis(500)
        || inputs.lifetime.is_zero()
        || inputs.lifetime > Duration::from_secs(300)
        || inputs.reconcile_interval.is_zero()
    {
        return Err(refused("invalid protected lane deadline/lifetime"));
    }
    let trust = writer_trust(&bundle);
    let bootstrap_proof =
        VerifiedRootWriterProof::verify(bundle.writer_proof.clone(), &trust).map_err(protocol)?;
    let root = &bundle.root;
    let lanes = inputs.lanes;
    let session = AgentdRootAuthoritySession::connect(
        lanes.observation,
        AgentdRootAuthorityPeer {
            pid: root.pid,
            boot_id: root.boot_id.clone(),
            process_start_ticks: root.process_start_ticks,
        },
        lanes.root_pidfd.try_clone().map_err(protocol)?,
        inputs.timeout,
        inputs.lifetime,
        trust,
    )
    .await
    .map_err(protocol)?;
    session.diagnose_attach(AttachStage::Connected);
    if session.authority() != *bootstrap_proof.authority()
        || session.revocations().map_err(protocol)? != bundle.revocations
    {
        return Err(refused("bootstrap differs from original Root observation"));
    }
    let issuer = Arc::new(
        AgentdUnixFinalUseGrantProvider::from_root_stream(
            lanes.issuer,
            root.pid,
            lanes.root_pidfd.try_clone().map_err(protocol)?,
            inputs.timeout,
            inputs.lifetime,
        )
        .map_err(protocol)?,
    );
    let transport = Arc::new(
        AgentdUnixCognitiveCheckpointTransport::from_stream(
            lanes.checkpoint,
            AgentdCognitiveCheckpointPeer {
                pid: root.pid,
                boot_id: root.boot_id.clone(),
                process_start_ticks: root.process_start_ticks,
            },
            lanes.root_pidfd.try_clone().map_err(protocol)?,
            inputs.timeout,
            inputs.lifetime,
        )
        .map_err(protocol)?,
    );
    let mut frontiers = Vec::with_capacity(2);
    for stream in [lanes.device_frontier, lanes.notes_frontier] {
        frontiers.push(Arc::new(
            RootFinalUseFrontierClient::from_stream(
                stream,
                bundle.issuer_key.key_id.clone(),
                RootPeerIdentity {
                    pid: root.pid,
                    boot_id: root.boot_id.clone(),
                    process_start_ticks: root.process_start_ticks,
                },
                lanes.root_pidfd.try_clone().map_err(protocol)?,
                inputs.timeout,
                inputs.lifetime,
            )
            .map_err(protocol)?,
        ));
    }
    let consumers = bundle.consumers.clone();
    let key = FinalUseIssuerTrustKey::from(bundle.issuer_key.clone());
    let revocations = bundle.revocations.clone();
    let clock = session.clock();
    session.diagnose_attach(AttachStage::OpeningFrontiers);
    let owners = tokio::task::spawn_blocking(move || {
        let mut owners = Vec::with_capacity(2);
        for (slot, frontier) in [consumers.device, consumers.notes]
            .into_iter()
            .zip(frontiers)
        {
            if frontier.load(&slot.owner_id).map_err(protocol)? != slot.frontier {
                return Err(refused("original FinalUse frontier differs from bootstrap"));
            }
            let owner = FinalUseAuthority::open_state_dir_with_issuer_keys(
                &slot.local_state_dir,
                slot.owner_id,
                vec![key.clone()],
                revocations.clone(),
                Arc::clone(&clock),
                frontier,
            )
            .map_err(protocol)?;
            if owner.frontier().map_err(protocol)? != slot.frontier {
                return Err(refused("original local FinalUse journal differs from Root"));
            }
            owners.push(owner);
        }
        Ok(owners)
    })
    .await
    .map_err(protocol)??;
    let [device, notes]: [FinalUseAuthority; 2] = owners
        .try_into()
        .map_err(|_| refused("incomplete original FinalUse consumers"))?;
    session.diagnose_attach(AttachStage::ActivatingOwners);
    session
        .activate_final_use_owners(vec![device.clone(), notes.clone()])
        .await
        .map_err(protocol)?;
    session.diagnose_attach(AttachStage::ReadingCurrent);
    let current_receipt = read_original_current(&transport, &bundle).await?;
    let authority = session.authority();
    let verifier = session.verifier();
    let (final_use, target) = match inputs.target {
        AgentdRootPrimaryTarget::Device(target) => (device.clone(), target),
        AgentdRootPrimaryTarget::Notes(target) => (notes.clone(), target),
    };
    let operations = AgentdProductionOperationRuntimeConfig::new(
        authority.clone(),
        Arc::clone(&verifier),
        bundle.writer.local_lease_id.clone(),
        bundle.writer.local_lease_generation,
        final_use,
        target,
        issuer.clone(),
        inputs.reconcile_interval,
    );
    operations.validate_for(config)?;
    session.diagnose_attach(AttachStage::OpeningWriter);
    let (host, checkpoint) = AgentdProductionWriterHost::open_with_protected_recovery(
        config,
        authority,
        verifier,
        bundle.writer.local_lease_id,
        bundle.writer.local_lease_generation,
        AgentdProtectedCheckpointInputs {
            transport,
            current_receipt,
            deadline: inputs.timeout,
        },
    )
    .await?;
    let host = Arc::new(host);
    session.diagnose_attach(AttachStage::InstallingWriter);
    let result = async {
        operations.validate_recovered_host(&host).await?;
        config.install_production_hosts(Arc::clone(&host), operations)
    }
    .await;
    if let Err(error) = result {
        Arc::try_unwrap(host)
            .map_err(|_| refused("failed protected assembly retained a shared owner"))?
            .close()
            .await?;
        return Err(error);
    }
    session.diagnose_attach(AttachStage::Attached);
    Ok(AgentdRootProductionAttachment {
        session,
        host,
        checkpoint,
        issuer,
        device,
        notes,
    })
}

fn writer_trust(bundle: &HostAuthorityPublicBootstrapV1) -> AgentdRootWriterTrust {
    AgentdRootWriterTrust {
        issuer_id: bundle.issuer_key.key_id.clone(),
        verifying_key: bundle.issuer_key.verifying_key,
        agent_id: bundle.writer.registered_agent_id.clone(),
        spawn_generation: bundle.writer.spawn_generation,
        owner_epoch: bundle.writer.owner_epoch,
        local_lease_id: bundle.writer.local_lease_id.clone(),
        local_lease_generation: bundle.writer.local_lease_generation,
        authority_lease: bundle.writer.authority_lease.clone(),
    }
}

fn validate_bundle(
    config: &AgentdConfig,
    bundle: &HostAuthorityPublicBootstrapV1,
) -> Result<(), AgentdError> {
    // SAFETY: geteuid takes no pointer arguments.
    let uid = unsafe { libc::geteuid() };
    let stat = std::fs::read_to_string("/proc/self/stat").map_err(protocol)?;
    let start = stat
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok());
    let boot = std::fs::read_to_string("/proc/sys/kernel/random/boot_id").map_err(protocol)?;
    let device_path = &bundle.consumers.device.local_state_dir;
    let notes_path = &bundle.consumers.notes.local_state_dir;
    let device = std::fs::symlink_metadata(device_path).map_err(protocol)?;
    let notes = std::fs::symlink_metadata(notes_path).map_err(protocol)?;
    if bundle.schema_version != 1
        || bundle.operation != HOST_AUTHORITY_BOOTSTRAP_V1
        || uid == 0
        || bundle.root.uid != 0
        || bundle.consumer.uid != uid
        || bundle.consumer.pid != std::process::id()
        || start != Some(bundle.consumer.process_start_ticks)
        || boot.trim() != bundle.consumer.boot_id
        || bundle.root.boot_id != bundle.consumer.boot_id
        || bundle.checkpoint.phase != codex_hepta_memory::CognitiveCheckpointPhase::Current
        || bundle.checkpoint.proposal.is_some()
        || bundle.consumer != bundle.checkpoint.peer_lifetime
        || bundle.registered_identity.identity().map_err(protocol)? != *config.identity()
        || bundle.writer.registered_agent_id != config.identity().agent_id
        || bundle.writer.spawn_generation != config.identity().spawn_generation
        || bundle.writer.local_lease_generation != config.identity().spawn_generation
        || bundle.checkpoint.owner_agent_id != config.identity().agent_id
        || bundle.consumers.device.owner_id != bundle.issuer_key.key_id
        || bundle.consumers.notes.owner_id != bundle.issuer_key.key_id
        || !device_path.is_absolute()
        || !notes_path.is_absolute()
        || !device.is_dir()
        || !notes.is_dir()
        || device_path.canonicalize().map_err(protocol)? != *device_path
        || notes_path.canonicalize().map_err(protocol)? != *notes_path
        || (device.dev(), device.ino()) == (notes.dev(), notes.ino())
        || bundle.revocations.authority_epoch < bundle.issuer_key.not_before_authority_epoch
        || bundle.revocations.authority_epoch > bundle.issuer_key.not_after_authority_epoch
    {
        return Err(refused(
            "trusted Root bootstrap does not bind this exact Agentd",
        ));
    }
    Ok(())
}

async fn read_original_current(
    transport: &AgentdUnixCognitiveCheckpointTransport,
    bundle: &HostAuthorityPublicBootstrapV1,
) -> Result<CognitiveCheckpointReceipt, AgentdError> {
    let sequence = bundle
        .checkpoint
        .last_mutation_sequence
        .checked_add(1)
        .ok_or_else(|| refused("protected checkpoint request sequence exhausted"))?;
    let request = CognitiveCheckpointRequest {
        schema_version: 1,
        operation: "runtime.cognitive.checkpoint.v1".into(),
        request_id: format!("{:016x}{sequence:016x}", bundle.checkpoint.publisher_epoch),
        command: CognitiveCheckpointCommand::ReadHead,
        expected: None,
        proposal: None,
    };
    let response: CognitiveCheckpointResponse = serde_json::from_slice(
        &transport
            .exchange(&serde_json::to_vec(&request).map_err(protocol)?)
            .await
            .map_err(protocol)?,
    )
    .map_err(protocol)?;
    if response.schema_version != 1
        || response.request_id != request.request_id
        || response.status != CognitiveCheckpointStatus::Ack
        || response.reason.is_some()
        || response.head.as_ref() != Some(&bundle.checkpoint)
    {
        return Err(refused(
            "original protected Current differs from trusted bootstrap",
        ));
    }
    Ok(CognitiveCheckpointReceipt {
        token: response
            .token
            .ok_or_else(|| refused("Root omitted its opaque Current token"))?,
        head: response
            .head
            .ok_or_else(|| refused("Root omitted its Current head"))?,
    })
}

fn refused(message: &str) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}

fn protocol(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Protocol(format!("original Root composition: {error}"))
}
