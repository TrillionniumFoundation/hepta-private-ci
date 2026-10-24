//! Source-bound public bundle from actual original root state, not a template.
use super::*;
use crate::deployment_issuer::WriterRegistrationExt;
use codex_hepta_contracts::AuthorityClock;
use pretty_assertions::assert_eq;

pub(super) fn capture(
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
) -> crate::HostAuthorityPublicBootstrapV1 {
    let (clock, leases, issuer) = open_registered_issuer(config).unwrap();
    let writer = config.writer.as_ref().unwrap();
    let peer = codex_hepta_memory::CognitiveCheckpointPeerLifetime {
        uid: config.peer_uid,
        pid: registration.peer_pid,
        boot_id: registration.boot_id.clone(),
        process_start_ticks: registration.process_start_ticks,
    };
    let service = HostAuthorityService::from_registered_owner(
        issuer.clone(),
        clock.clone(),
        crate::authority_host_config::registered_identity(&registration.registered_identity)
            .unwrap(),
    )
    .unwrap()
    .with_registered_writer(writer.clone(), leases.verifier())
    .unwrap();
    let expected = service
        .writer
        .as_ref()
        .unwrap()
        .checkpoint_registration(&issuer, registration.publisher_epoch, peer.clone())
        .unwrap();
    writer
        .with_live(&leases.verifier(), |_| {
            let proof = issuer.retained_writer_authorization(writer)?;
            assert_eq!(proof, service.writer.as_ref().unwrap().proof);
            let head = codex_hepta_contracts::HostAuthorityFrontierStore::<
                codex_hepta_memory::CognitiveCheckpointHead,
            >::open(
                RootAuthorityDirectory::open(config.checkpoint_state_dir.as_ref().unwrap())
                    .unwrap(),
                "root-cognitive-checkpoint-v1".into(),
            )
            .unwrap()
            .load("root-cognitive-checkpoint-v1")
            .unwrap();
            assert_eq!(head.writer_binding, expected.writer_binding);
            assert_eq!(head.peer_lifetime, expected.peer_lifetime);
            assert_eq!(head.owner_agent_id, expected.owner_agent_id);
            assert_eq!(head.publisher_epoch, expected.publisher_epoch);
            assert_eq!(
                head.phase,
                codex_hepta_memory::CognitiveCheckpointPhase::Current
            );
            assert!(head.counter > 0);
            let revocations = issuer.revocations()?;
            let read = |slot: &HostAuthorityConsumerConfig, purpose: &str| {
                let frontier = codex_hepta_contracts::HostAuthorityFrontierStore::<
                    codex_hepta_contracts::FinalUseFrontier,
                >::open(
                    RootAuthorityDirectory::open(&slot.state_dir).unwrap(),
                    slot.owner_id.clone(),
                )
                .unwrap()
                .load(&slot.owner_id)
                .unwrap();
                crate::HostAuthorityPublicConsumerV1 {
                    local_state_dir: config
                        .sockets
                        .observation
                        .parent()
                        .unwrap()
                        .join("consumer-local")
                        .join(purpose),
                    owner_id: slot.owner_id.clone(),
                    frontier,
                }
            };
            let slots = config.consumers.as_ref().unwrap();
            let stat = std::fs::read_to_string("/proc/self/stat")?;
            let start = stat
                .rsplit_once(") ")
                .unwrap()
                .1
                .split_whitespace()
                .nth(19)
                .unwrap()
                .parse()
                .unwrap();
            let bundle = crate::HostAuthorityPublicBootstrapV1 {
                schema_version: 1,
                operation: crate::HOST_AUTHORITY_BOOTSTRAP_V1.into(),
                root: codex_hepta_memory::CognitiveCheckpointPeerLifetime {
                    uid: 0,
                    pid: std::process::id(),
                    boot_id: registration.boot_id.clone(),
                    process_start_ticks: start,
                },
                consumer: peer,
                registered_identity: registration.registered_identity.clone(),
                issuer_key: issuer.trust_key()?.into(),
                revocations: revocations.clone(),
                writer: writer.clone(),
                writer_proof: proof,
                checkpoint: head,
                consumers: crate::HostAuthorityPublicConsumersV1 {
                    device: read(&slots.device, "device"),
                    notes: read(&slots.notes, "notes"),
                },
                sockets: crate::HostAuthorityFiveLanePathsV1 {
                    observation: config.sockets.observation.clone(),
                    issuer: config.sockets.issuer.clone(),
                    checkpoint: config.sockets.checkpoint.clone(),
                    device_frontier: config.sockets.device_frontier.clone().unwrap(),
                    notes_frontier: config.sockets.notes_frontier.clone().unwrap(),
                },
            };
            assert_eq!(issuer.revocations()?, revocations);
            crate::authority_host_service::validate_observation_lease(
                &writer.authority_lease,
                &revocations,
                clock.now_unix_ms().map_err(std::io::Error::other)?,
            )?;
            Ok(bundle)
        })
        .unwrap()
}
