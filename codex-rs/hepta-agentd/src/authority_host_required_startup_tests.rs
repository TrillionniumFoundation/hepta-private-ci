//! Actual Root cold-composition negatives. These do not claim a recovered
//! owner Ready: the complete two-generation owner positive is a separate case.
use super::*;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_memory::CognitiveCheckpointResponse;
use pretty_assertions::assert_eq;
use std::sync::Barrier;

fn service(f: &fixture::Fixture) -> HostAuthorityService {
    let archive = f.config.state_dir.join("required-physical-material");
    std::fs::DirBuilder::new().mode(0o700).create(&archive).unwrap();
    let service = f.service().with_recovered_checkpoint(
        RootAuthorityDirectory::open(f.config.checkpoint_state_dir.as_ref().unwrap()).unwrap(),
        &f.previous, &f.retired, &f.successor, /*publisher_epoch*/ 2, &f.material,
    ).unwrap().with_registered_consumers(&f.config.state_dir, f.config.consumers.as_ref().unwrap()).unwrap()
        .with_required_material_startup(&archive).unwrap();
    let paths = &f.config.sockets;
    service.with_bootstrap_registration(crate::HostAuthorityBootstrapLocations {
        sockets: crate::HostAuthorityFiveLanePathsV1 {
            observation: paths.observation.clone(), issuer: paths.issuer.clone(), checkpoint: paths.checkpoint.clone(),
            device_frontier: paths.device_frontier.clone().unwrap(), notes_frontier: paths.notes_frontier.clone().unwrap(),
        },
        device_local_state_dir: f.runtime.path().join("consumer-local/device"),
        notes_local_state_dir: f.runtime.path().join("consumer-local/notes"),
        lifetime: Duration::from_millis(f.config.lifetime_ms),
    }, f.new_peer.pidfd.try_clone().unwrap()).unwrap()
}

fn snapshot(f: &fixture::Fixture) -> (serde_json::Value, CognitiveCheckpointHead, [FinalUseFrontier; 2]) {
    let issuer = crate::DeploymentFrontierStore::<serde_json::Value>::open_protected(
        &f.config.state_dir.join("issuer"),
    ).unwrap().load("local-final-use-issuer").unwrap();
    let current = codex_hepta_contracts::HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
        RootAuthorityDirectory::open(f.config.checkpoint_state_dir.as_ref().unwrap()).unwrap(), STORE_OWNER.into(),
    ).unwrap().load(STORE_OWNER).unwrap();
    let consumers = f.config.consumers.as_ref().unwrap();
    let frontier = |slot: &crate::HostAuthorityConsumerConfig| {
        codex_hepta_contracts::HostAuthorityFrontierStore::<FinalUseFrontier>::open(
            RootAuthorityDirectory::open(&slot.state_dir).unwrap(), slot.owner_id.clone(),
        ).unwrap().load(&slot.owner_id).unwrap()
    };
    (issuer, current, [frontier(&consumers.device), frontier(&consumers.notes)])
}

fn request(command: &str, sequence: u64, expected: serde_json::Value) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({"schema_version":1,
        "operation":"runtime.cognitive.checkpoint.v1", "request_id":format!("0000000000000002{sequence:016x}"),
        "command":command, "expected":expected, "proposal":null})).unwrap()
}

fn assert_closed(service: &HostAuthorityService) {
    assert!(service.require_material_startup_complete().is_err());
    assert_eq!(service.checkpoint.as_ref().unwrap().backend.retained_current_for_root(),
        Err(AuthorityTrustError::Unavailable));
    assert!(service.confirm_recovered_owner_ready().is_err());
    assert!(service.capture_public_bootstrap().is_err());
}

#[test]
#[ignore = "actual Root/SSD canonical pending-startup no-mutation qualification"]
fn required_pending_reads_preserve_all_original_heads_and_refuse_mutations() {
    let f = fixture::Fixture::new();
    let service = service(&f);
    let before = snapshot(&f);
    let bundle = service.capture_public_bootstrap().unwrap();
    for (schema_version, operation) in [(1, crate::HOST_WRITER_AUTHORIZATION_V1), (2, crate::HOST_AUTHORITY_OBSERVATION_V2)] {
        assert!(service.handle(HostAuthorityLane::Observation,
            &serde_json::to_vec(&serde_json::json!({"schema_version":schema_version,"operation":operation})).unwrap()).is_ok());
    }
    let current: CognitiveCheckpointResponse = serde_json::from_slice(&service.handle(
        HostAuthorityLane::Checkpoint, &request("read_head", 1, serde_json::Value::Null),
    ).unwrap()).unwrap();
    assert_eq!(current.status, codex_hepta_memory::CognitiveCheckpointStatus::Ack);
    assert_eq!(current.head.as_ref(), Some(&bundle.checkpoint));
    for lane in [HostAuthorityLane::DeviceConsumerFrontier, HostAuthorityLane::NotesConsumerFrontier] {
        let response = service.handle(lane, &serde_json::to_vec(&codex_hepta_contracts::HostConsumerFrontierRequestV1::Load {
            schema_version:1, request_id:1,
        }).unwrap()).unwrap();
        let response: codex_hepta_contracts::HostConsumerFrontierResponseV1 = serde_json::from_slice(&response).unwrap();
        assert_eq!(response.status, codex_hepta_contracts::HostConsumerFrontierStatusV1::Ack);
        let raw = serde_json::to_vec(&codex_hepta_contracts::HostConsumerFrontierRequestV1::CompareAndSet {
            schema_version:1, request_id:2, expected:response.frontier.unwrap(), next:response.frontier.unwrap(),
        }).unwrap();
        assert!(service.handle(lane, &raw).is_err());
    }
    for command in ["begin_writes", "prepare_publication", "commit_publication", "fence_publisher"] {
        assert!(service.handle(HostAuthorityLane::Checkpoint,
            &request(command, 2, serde_json::to_value(&current.token).unwrap())).is_err());
    }
    let mut objective = body(); objective.spawn_generation = 3;
    for issuer in [serde_json::json!({"schema_version":1,"operation":"runtime.authbus.objective.sign.v1","body":objective}),
        serde_json::json!({"schema_version":1,"operation":"runtime.agentd.production_operation",
            "binding":binding(f.registration.registered_identity.agent_id.as_str())})] {
        assert!(service.handle(HostAuthorityLane::Issuer, &serde_json::to_vec(&issuer).unwrap()).is_err());
    }
    assert_eq!(snapshot(&f), before);
    // A trusted Root call out of order cannot manufacture owner readiness.
    assert!(service.confirm_recovered_owner_ready().is_err());
    assert_closed(&service);
    assert_eq!(snapshot(&f), before);
}

#[test]
#[ignore = "actual Root/SSD retained-image change permanently rejects installation"]
fn required_install_changed_material_cannot_retry_or_repair_unknown() {
    let f = fixture::Fixture::new();
    let service = service(&f);
    let before = snapshot(&f);
    let material = f.another_material();
    let path = material.path().to_path_buf();
    let bytes = std::fs::read(&path).unwrap();
    let mut file = OpenOptions::new().append(true).open(&path).unwrap();
    file.write_all(b"controlled changed retained image").unwrap(); file.sync_all().unwrap();
    assert!(service.install_recovered_owner_material(material, &f.retired, &f.successor).is_err());
    std::fs::write(&path, bytes).unwrap(); std::fs::File::open(&path).unwrap().sync_all().unwrap();
    assert!(service.install_recovered_owner_material(f.another_material(), &f.retired, &f.successor).is_err());
    assert_closed(&service);
    assert_eq!(snapshot(&f), before);
}

#[test]
#[ignore = "actual Root/SSD changed pointer and competing Ready attempts stay fenced"]
fn required_changed_pointer_and_competing_ready_never_publish_late_ready() {
    let f = fixture::Fixture::new();
    let service = service(&f);
    let before = snapshot(&f);
    // Root's earlier controlled Dirty append can create new WAL/SHM files.
    // Prepare the fixed actual UID60001 source; keep production OwnerRule exact.
    let layout = f.registration.registered_identity.identity().unwrap().layout;
    for entry in std::fs::read_dir(layout.cognitive_root()).unwrap() {
        let path = entry.unwrap().path();
        if path.is_file() {
            std::os::unix::fs::chown(&path, Some(60001), Some(60001)).unwrap();
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
        }
    }
    let installed = service.install_recovered_owner_material(f.another_material(), &f.retired, &f.successor).unwrap();
    installed.verify_unchanged().unwrap();
    let pointer = installed.path().parent().unwrap().join(".cognitive-active-v1");
    let bytes = std::fs::read(&pointer).unwrap();
    drop(installed);
    std::fs::write(&pointer, b"unregistered.sqlite3\n").unwrap();
    let start = Barrier::new(3);
    std::thread::scope(|scope| {
        let attempt = || { start.wait(); service.confirm_recovered_owner_ready() };
        let first = scope.spawn(attempt); let second = scope.spawn(attempt);
        start.wait();
        assert!(first.join().unwrap().is_err()); assert!(second.join().unwrap().is_err());
    });
    std::fs::write(&pointer, bytes).unwrap(); std::fs::File::open(&pointer).unwrap().sync_all().unwrap();
    assert_closed(&service);
    assert_eq!(snapshot(&f), before);
}
