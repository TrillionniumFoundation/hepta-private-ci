//! Actual canonical Registry/key/proof handoff around the cold-recovery wrapper.
//! This component test does not install a recovered CognitiveStore owner or
//! activate production authority. Only independently retained material is used.
use super::*;
use codex_hepta_memory::CognitiveCheckpointHead;
use codex_hepta_memory::CognitiveCheckpointPhase;
use pretty_assertions::assert_eq;

#[path = "authority_host_recovery_fixture.rs"]
mod fixture;
#[path = "authority_host_recovery_client_tests.rs"]
mod client;
#[path = "authority_host_required_startup_tests.rs"]
mod required_startup;
#[path = "authority_host_canonical_lifecycle_tests.rs"]
mod canonical;

const RECOVERY_CLIENT: &str =
    "authority_host_service::tests::root::recovery::client::recovered_service_client";
const STORE_OWNER: &str = "root-cognitive-checkpoint-v1";

#[test]
#[ignore = "explicit Root/SSD original Registry, physical material and five-lane qualification"]
fn original_registry_rotation_recovers_material_then_captures_and_serves() {
    let mut f = fixture::Fixture::new();
    assert_eq!(f.previous.head.phase, CognitiveCheckpointPhase::Dirty);
    assert_eq!((f.previous.head.counter, f.previous.head.publisher_epoch), (2, 1));
    assert_ne!(f.original_cut, f.dirty_cut);
    let directory = f.config.checkpoint_state_dir.as_ref().unwrap();
    let store = codex_hepta_contracts::HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
        RootAuthorityDirectory::open(directory).unwrap(), STORE_OWNER.into(),
    ).unwrap();
    assert_eq!(store.load(STORE_OWNER).unwrap(), f.previous.head);
    // Revocation closes the actual predecessor service, rather than merely
    // replacing a digest in an otherwise synthetic checkpoint registration.
    let read = serde_json::to_vec(&serde_json::json!({"schema_version":1,
        "operation":"runtime.cognitive.checkpoint.v1", "request_id":"00000000000000010000000000000003",
        "command":"read_head", "expected":null, "proposal":null})).unwrap();
    assert!(f.old_service.handle(HostAuthorityLane::Checkpoint, &read).is_err());
    let mut wrong = f.service();
    let proof = &mut wrong.writer.as_mut().unwrap().proof;
    let first = if proof.signature_hex.starts_with('0') { "1" } else { "0" };
    proof.signature_hex.replace_range(..1, first);
    let result = wrong.with_recovered_checkpoint(
        RootAuthorityDirectory::open(directory).unwrap(), &f.previous, &f.retired,
        &f.successor, /*publisher_epoch*/ 2, &f.another_material(),
    );
    assert!(result.is_err(), "wrong retained proof must return no assembled service");
    assert_eq!(store.load(STORE_OWNER).unwrap(), f.previous.head);
    assert_eq!(f.issuer.retained_writer_authorization(f.config.writer.as_ref().unwrap()).unwrap(), f.new_proof);
    let before = f.issuer.revocations().unwrap();
    let service = f.service();
    let service = service.with_recovered_checkpoint(
        RootAuthorityDirectory::open(directory).unwrap(), &f.previous, &f.retired,
        &f.successor, /*publisher_epoch*/ 2, &f.material,
    ).unwrap().with_registered_consumers(&f.config.state_dir, f.config.consumers.as_ref().unwrap()).unwrap();
    let paths = &f.config.sockets;
    let service = service.with_bootstrap_registration(crate::HostAuthorityBootstrapLocations {
        sockets: crate::HostAuthorityFiveLanePathsV1 {
            observation: paths.observation.clone(), issuer: paths.issuer.clone(), checkpoint: paths.checkpoint.clone(),
            device_frontier: paths.device_frontier.clone().unwrap(), notes_frontier: paths.notes_frontier.clone().unwrap(),
        },
        device_local_state_dir: f.runtime.path().join("consumer-local/device"),
        notes_local_state_dir: f.runtime.path().join("consumer-local/notes"),
        lifetime: Duration::from_millis(f.config.lifetime_ms),
    }, f.new_peer.pidfd.try_clone().unwrap()).unwrap();
    let bundle = service.capture_public_bootstrap().unwrap();
    let registered = service.writer.as_ref().unwrap().checkpoint_registration(
        &f.issuer, /*publisher_epoch*/ 2, f.new_peer.lifetime.clone(),
    ).unwrap();
    let mut expected = f.previous.head.clone();
    expected.counter += 1;
    expected.publisher_epoch = registered.publisher_epoch;
    expected.writer_binding = registered.writer_binding;
    expected.peer_lifetime = registered.peer_lifetime;
    expected.phase = CognitiveCheckpointPhase::Current;
    expected.last_mutation_sequence = 0;
    expected.last_request = None;
    expected.proposal = None;
    assert_eq!(bundle.checkpoint, expected);
    assert_eq!(bundle.writer_proof, f.new_proof);
    assert_eq!(bundle.writer.spawn_generation, 3);
    assert_eq!(bundle.writer.local_lease_generation, 2);
    assert_eq!(bundle.checkpoint.phase, CognitiveCheckpointPhase::Current);
    assert_eq!((bundle.checkpoint.counter, bundle.checkpoint.publisher_epoch,
        bundle.checkpoint.last_mutation_sequence), (3, 2, 0));
    assert_eq!(bundle.checkpoint.last_current, f.original_cut);
    assert_ne!(bundle.checkpoint.last_current, f.dirty_cut);
    assert_eq!(bundle.revocations, before);
    assert_eq!(store.load(STORE_OWNER).unwrap(), bundle.checkpoint);
    assert_eq!(serde_json::to_value(service.capture_public_bootstrap().unwrap()).unwrap(), serde_json::to_value(&bundle).unwrap());
    let mut sealed = crate::seal_host_authority_bootstrap(&bundle).unwrap();
    let mut bytes = Vec::new();
    sealed.read_to_end(&mut bytes).unwrap();
    assert_eq!(bytes, serde_json::to_vec(&bundle).unwrap());
    // The real producer's bytes travel through a controlled pipe only in this
    // component fixture. This does not qualify production sealed-FD reception.
    let mut stdin = f.new_peer.child.stdin.take().unwrap();
    stdin.write_all(&f.config.expected_verifying_key).unwrap();
    stdin.write_all(&(bytes.len() as u32).to_be_bytes()).unwrap();
    stdin.write_all(&bytes).unwrap();
    drop(stdin);
    let result = crate::authority_host_runtime::listeners::serve_lanes(
        &service, &f.config, &f.registration, &f.new_peer.pidfd,
    );
    assert!(f.new_peer.child.wait().unwrap().success(), "actual successor client failed: {result:?}");
    // The client ends with one malformed closed-DTO checkpoint frame; neither
    // a new cut nor any ACK may be produced by that deliberate final negative.
    assert!(result.is_err());
    assert_eq!(store.load(STORE_OWNER).unwrap(), bundle.checkpoint);
    assert_eq!(f.issuer.revocations().unwrap(), before);
    assert_eq!(f.issuer.retained_writer_authorization(f.config.writer.as_ref().unwrap()).unwrap(), f.new_proof);
    let retained = crate::DeploymentFrontierStore::<serde_json::Value>::open_protected(&f.config.state_dir.join("issuer")).unwrap();
    assert_eq!(retained.load("local-final-use-issuer").unwrap()["sequence"], 4);
    for slot in [&f.config.consumers.as_ref().unwrap().device, &f.config.consumers.as_ref().unwrap().notes] {
        let frontier = codex_hepta_contracts::HostAuthorityFrontierStore::<codex_hepta_contracts::FinalUseFrontier>::open(
            RootAuthorityDirectory::open(&slot.state_dir).unwrap(), slot.owner_id.clone(),
        ).unwrap();
        assert_eq!(frontier.load(&slot.owner_id).unwrap(), codex_hepta_contracts::FinalUseFrontier::for_initial_head(&before).unwrap());
    }
    println!("{}", serde_json::json!({"qualification":"original_registry_cold_recovery_wrapper",
        "retired_spawn":1,"successor_spawn":3,"local_generation":2,"publisher_epoch":2,"current_counter":3,
        "original_key_head_sequence":true,"wrong_retained_proof_refused":true,"retained_cut_preserved":true,
        "same_captured_service_served":true,"five_lanes":true,"recovered_owner_installed":false,
        "production_ready":false,"sealed_fd_receiver_qualified":false}));
}
