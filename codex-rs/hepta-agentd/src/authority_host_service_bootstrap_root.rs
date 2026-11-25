//! Component fixture delegates to the actual public Root capture API.
use super::*;
use pretty_assertions::assert_eq;

pub(super) fn capture(
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    preheld_host_pidfd: std::os::fd::OwnedFd,
) -> (HostAuthorityService, crate::HostAuthorityPublicBootstrapV1) {
    let (clock, leases, issuer) = open_registered_issuer(config).unwrap();
    let peer = codex_hepta_memory::CognitiveCheckpointPeerLifetime {
        uid: config.peer_uid,
        pid: registration.peer_pid,
        boot_id: registration.boot_id.clone(),
        process_start_ticks: registration.process_start_ticks,
    };
    let service = HostAuthorityService::from_registered_owner(
        issuer,
        clock,
        crate::authority_host_config::registered_identity(&registration.registered_identity)
            .unwrap(),
    )
    .unwrap()
    .with_registered_writer(config.writer.as_ref().unwrap().clone(), leases.verifier())
    .unwrap()
    .with_registered_checkpoint(
        RootAuthorityDirectory::open(config.checkpoint_state_dir.as_ref().unwrap()).unwrap(),
        registration.publisher_epoch,
        peer,
    )
    .unwrap()
    .with_registered_consumers(&config.state_dir, config.consumers.as_ref().unwrap())
    .unwrap();
    assert!(
        service.capture_public_bootstrap().is_err(),
        "unregistered Root producer must refuse"
    );
    let runtime = config.sockets.observation.parent().unwrap();
    let service = service
        .with_bootstrap_registration(
            crate::HostAuthorityBootstrapLocations {
                sockets: crate::HostAuthorityFiveLanePathsV1 {
                    observation: config.sockets.observation.clone(),
                    issuer: config.sockets.issuer.clone(),
                    checkpoint: config.sockets.checkpoint.clone(),
                    device_frontier: config.sockets.device_frontier.clone().unwrap(),
                    notes_frontier: config.sockets.notes_frontier.clone().unwrap(),
                },
                device_local_state_dir: runtime.join("consumer-local/device"),
                notes_local_state_dir: runtime.join("consumer-local/notes"),
                lifetime: Duration::from_millis(config.lifetime_ms),
            },
            preheld_host_pidfd,
        )
        .unwrap();
    let installed = service.bootstrap.as_ref().unwrap();
    assert!(
        installed
            .validate_peer(codex_hepta_contracts::HostIssuerPeer {
                uid: 0,
                pid: registration.peer_pid,
            })
            .is_err()
    );
    assert!(
        installed
            .validate_peer(codex_hepta_contracts::HostIssuerPeer {
                uid: config.peer_uid,
                pid: std::process::id(),
            })
            .is_err()
    );
    let bundle = service.capture_public_bootstrap().unwrap();
    let again = service.capture_public_bootstrap().unwrap();
    assert_eq!(
        serde_json::to_value(&bundle).unwrap(),
        serde_json::to_value(again).unwrap()
    );
    assert_eq!(
        bundle.checkpoint.phase,
        codex_hepta_memory::CognitiveCheckpointPhase::Current
    );
    assert_eq!(
        (
            bundle.checkpoint.counter,
            bundle.checkpoint.last_mutation_sequence
        ),
        (1, 0)
    );
    // The caller serves this very same object; no reopen can bypass a backend's
    // permanently Unknown state. Stdin remains a component transport fixture.
    (service, bundle)
}
