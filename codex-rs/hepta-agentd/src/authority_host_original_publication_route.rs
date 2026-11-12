//! Capture a purpose-bound publication route from the actual retained learning
//! owner on the same Root service. A late caller supplies its original end.

use super::*;
use crate::authority_host_service::RegisteredHostLearningCheckpointV1;

pub(in crate::authority_host_runtime::session) fn prepare_original_publication_route(
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner_pidfd: &OwnedFd,
    learning: &RegisteredHostLearningCheckpointV1,
    original_end: Option<Instant>,
    version: PublicationVersion,
) -> io::Result<(
    PublicationRuntime,
    RootGenerationPublicationEnrollmentCapabilityV1,
    crate::RootGenerationPublicationOfferV1,
)> {
    crate::authority_host_service::generation_publication::original_root()?;
    if let Some(end) = original_end {
        crate::authority_host_runtime::owner_alive(owner_pidfd, end)?;
    }
    let (bundle, bootstrap) = service.with_learning_profile(
        config,
        registration,
        owner_pidfd,
        &learning.profile,
        |initial, proof| {
            let scope = learning.profile.require_cell_scope(&initial)?;
            if learning.backend.frozen_scope_binding() != Some(scope.binding()) {
                return Err(io::Error::other(
                    "actual learning scope differs from publication route",
                ));
            }
            // A registered vacant checkpoint is legitimate before the
            // original learning client starts. Capture only its route;
            // late enrollment still requires the actual completed decision.
            let before = learning
                .backend
                .restore(&initial.request)
                .map_err(io::Error::other)?;
            if let Some(snapshot) = &before {
                scope
                    .validate_snapshot(snapshot)
                    .map_err(io::Error::other)?;
            }
            let bundle = PublicationBootstrap {
                purpose: version.purpose().into(),
                learning_operation: initial.request.operation_id.to_string(),
                root: codex_hepta_memory::CognitiveCheckpointPeerLifetime {
                    uid: 0,
                    pid: std::process::id(),
                    boot_id: registration.boot_id.clone(),
                    process_start_ticks: root_start()?,
                },
                consumer: codex_hepta_memory::CognitiveCheckpointPeerLifetime {
                    uid: config.peer_uid,
                    pid: registration.peer_pid,
                    boot_id: registration.boot_id.clone(),
                    process_start_ticks: registration.process_start_ticks,
                },
                identity: registration.registered_identity.clone(),
                initial: initial.head_digest.to_string(),
                scope: scope.binding().to_string(),
                writer: proof,
                socket: config
                    .sockets
                    .observation
                    .parent()
                    .ok_or_else(|| io::Error::other("original Root listener parent missing"))?
                    .join(version.socket()),
            };
            let bootstrap = crate::authority_host_bootstrap_seal::seal_bytes(
                &serde_json::to_vec(&bundle).map_err(io::Error::other)?,
            )?;
            if learning
                .backend
                .restore(&initial.request)
                .map_err(io::Error::other)?
                != before
            {
                return Err(io::Error::other(
                    "original learning changed during publication capture",
                ));
            }
            Ok((bundle, bootstrap))
        },
    )?;
    if let Some(end) = original_end {
        crate::authority_host_runtime::owner_alive(owner_pidfd, end)?;
    }
    let (sender, receiver) = mpsc::sync_channel(1);
    let phase = Arc::new(AtomicU8::new(PREPARED));
    let runtime = PublicationRuntime {
        receiver: Mutex::new(receiver),
        phase: Arc::clone(&phase),
        socket: bundle.socket,
        version,
    };
    Ok((
        runtime,
        RootGenerationPublicationEnrollmentCapabilityV1 {
            sender,
            phase,
            root_pid: bundle.root.pid,
            consumer_uid: config.peer_uid,
            boot_id: bundle.root.boot_id,
            process_start_ticks: bundle.root.process_start_ticks,
            lifetime: Duration::from_millis(config.lifetime_ms),
            original_end,
            version,
        },
        crate::RootGenerationPublicationOfferV1 { bootstrap },
    ))
}
