//! Two real canonical original-owner generations. No external effect, toy
//! authority, legacy lease token, metadata image or replay ticket is involved.
use super::*;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::CognitiveCheckpointResponse;
use codex_hepta_memory::CognitiveCheckpointStatus;
use pretty_assertions::assert_eq;
use std::process::Child;

#[path = "authority_host_canonical_fixture.rs"]
mod lifecycle_fixture;
#[path = "authority_host_canonical_client_tests.rs"]
mod client;

const CANONICAL_CLIENT: &str =
    "authority_host_service::tests::root::recovery::canonical::client::canonical_owner_child";

fn frame(stdin: &mut std::process::ChildStdin, bytes: &[u8]) {
    assert!(!bytes.is_empty() && bytes.len() <= crate::HOST_AUTHORITY_BOOTSTRAP_BOUND);
    stdin.write_all(&(bytes.len() as u32).to_be_bytes()).unwrap(); stdin.write_all(bytes).unwrap();
}

fn read(service: &HostAuthorityService, epoch: u64, sequence: u64) -> CognitiveCheckpointReceipt {
    let raw = serde_json::to_vec(&serde_json::json!({"schema_version":1,"operation":"runtime.cognitive.checkpoint.v1",
        "request_id":format!("{epoch:016x}{sequence:016x}"),"command":"read_head","expected":null,"proposal":null})).unwrap();
    let response: CognitiveCheckpointResponse = serde_json::from_slice(&service.handle(HostAuthorityLane::Checkpoint,&raw).unwrap()).unwrap();
    assert_eq!(response.status,CognitiveCheckpointStatus::Ack);
    CognitiveCheckpointReceipt {head:response.head.unwrap(),token:response.token.unwrap()}
}

fn phase(child: &mut Child, path: &Path, end: Instant) -> serde_json::Value {
    loop {
        match std::fs::symlink_metadata(path) {
            Ok(metadata) => {
                assert!(metadata.is_file() && metadata.uid()==60001 && metadata.nlink()==1 && metadata.mode() & 0o7777==0o600);
                // Test-only ready reporting, never authority or a Current source.
                if let Ok(bytes) = std::fs::read(path)
                    && let Ok(value) = serde_json::from_slice(&bytes)
                { return value; }
            }
            Err(error) if error.kind()==io::ErrorKind::NotFound => {}
            Err(error) => panic!("owned generation phase: {error}"),
        }
        assert!(child.try_wait().unwrap().is_none(),"owned canonical child exited before its phase");
        assert!(Instant::now()<end,"original bounded generation lifetime elapsed");
        std::thread::sleep(Duration::from_millis(5));
    }
}

fn run(f: &lifecycle_fixture::Fixture, generation: &mut lifecycle_fixture::Generation) -> CognitiveCheckpointReceipt {
    let started = Instant::now();
    let end = started+Duration::from_millis(f.config.lifetime_ms);
    let service=&generation.service;
    let bundle=service.capture_public_bootstrap().unwrap();
    let initial=read(service,generation.registration.publisher_epoch,1);
    assert_eq!(initial.head,bundle.checkpoint);
    let mut sealed=crate::seal_host_authority_bootstrap(&bundle).unwrap();
    let mut bytes=Vec::new(); sealed.read_to_end(&mut bytes).unwrap();
    assert_eq!(bytes,serde_json::to_vec(&bundle).unwrap());
    let mut stdin=generation.peer.child.stdin.take().unwrap();
    stdin.write_all(&f.config.expected_verifying_key).unwrap(); frame(&mut stdin,&bytes);
    // This additional trusted-parent fixture frame is an original server
    // Receipt, not a new production sealed schema or a recomputed client token.
    frame(&mut stdin,&serde_json::to_vec(&initial).unwrap());
    let local=bundle.writer.local_lease_generation;
    let owner=&generation.peer.pidfd;
    let child=&mut generation.peer.child;
    std::thread::scope(|scope| {
        let server=scope.spawn(|| crate::authority_host_runtime::listeners::serve_lanes(
            service,&f.config,&generation.registration,owner));
        let ready=phase(child,&f.runtime.path().join(format!("consumer-local/owner-{local}-ready.json")),end);
        assert_eq!(ready["owner_ready"],true);
        assert_eq!(ready["generation"],local);
        assert_eq!(ready["spawn"],bundle.writer.spawn_generation);
        assert_eq!(ready["recovered_cut"],serde_json::to_value(&initial.head.last_current).unwrap());
        assert!(service.require_material_startup_complete().is_err());
        service.confirm_recovered_owner_ready().unwrap();
        service.require_material_startup_complete().unwrap();
        assert!(service.confirm_recovered_owner_ready().is_err(),"duplicate Root Ready must be refused");
        service.require_material_startup_complete().unwrap();
        assert_eq!(service.capture_public_bootstrap().unwrap().checkpoint,initial.head);
        stdin.write_all(&[1]).unwrap();
        let terminal=phase(child,&f.runtime.path().join(format!("consumer-local/owner-{local}-terminal.json")),end);
        assert_eq!(terminal["owner_closed"],true);
        assert_eq!(terminal["terminal"]["state"],"released");
        assert_eq!(terminal["terminal"]["generation"],local);
        let retained=read(service,generation.registration.publisher_epoch,u64::MAX);
        assert_eq!(retained.head.phase,CognitiveCheckpointPhase::Current);
        assert_eq!(serde_json::to_value(&retained.head.last_current).unwrap(),terminal["cut"]);
        assert_ne!(retained.head.last_current,initial.head.last_current);
        assert_eq!(retained.head.writer_binding,initial.head.writer_binding);
        assert_eq!(retained.head.peer_lifetime,initial.head.peer_lifetime);
        let image=f.retained(&retained.head.last_current);
        image.verify_unchanged().unwrap();
        stdin.write_all(&[2]).unwrap(); drop(stdin);
        loop {
            if let Some(status)=child.try_wait().unwrap() { assert!(status.success(),"actual canonical owner failed"); break; }
            assert!(Instant::now()<end,"original bounded owner reap deadline elapsed");
            std::thread::sleep(Duration::from_millis(5));
        }
        // The child deliberately closes its issuer lane with one invalid DTO
        // after every positive assertion. No checkpoint Unknown is manufactured.
        assert!(server.join().unwrap().is_err());
        println!("CANONICAL_OWNER_PHASE {}",serde_json::json!({"generation":local,"spawn":bundle.writer.spawn_generation,
            "elapsed_ms":started.elapsed().as_millis(),"current_counter":retained.head.counter,
            "actual_original_writer":true,"terminal_current":true,"external_effect":false}));
        retained
    })
}

#[test]
#[ignore = "actual Root/SSD two canonical UID60001 owners and full physical startup qualification"]
fn canonical_two_generations_publish_terminal_current_install_recover_and_confirm_ready() {
    let mut f=lifecycle_fixture::Fixture::new();
    let before_head=f.issuer.revocations().unwrap(); let before_key=f.issuer.trust_key().unwrap();
    let mut old=f.first();
    let previous=run(&f,&mut old);
    assert_eq!(previous.head.writer_binding.generation,1);
    assert_eq!(previous.head.publisher_epoch,1);
    let material=f.retained(&previous.head.last_current);
    let retired=crate::RetiredCheckpointPublisher::observe(old.peer.lifetime.clone()).unwrap();
    let mut next=f.next(&previous,&retired,&material);
    let after_adoption=next.service.capture_public_bootstrap().unwrap();
    assert_eq!(after_adoption.checkpoint.last_current,previous.head.last_current);
    assert_eq!(after_adoption.checkpoint.counter,previous.head.counter+1);
    assert_eq!(after_adoption.checkpoint.publisher_epoch,2);
    assert_eq!(after_adoption.writer.spawn_generation,3);
    assert_eq!(after_adoption.writer.local_lease_generation,2);
    let installed=next.service.install_recovered_owner_material(material,&retired,&next.successor).unwrap();
    assert_eq!(installed.anchor(),&previous.head.last_current); installed.verify_unchanged().unwrap();
    // The fixed Host cannot obtain the original exclusive recovery lock until
    // Root explicitly releases this original installed-material capability.
    drop(installed);
    let final_current=run(&f,&mut next);
    assert_eq!(final_current.head.writer_binding.generation,2);
    assert_eq!(final_current.head.publisher_epoch,2);
    assert_eq!(f.issuer.revocations().unwrap(),before_head);
    assert_eq!(f.issuer.trust_key().unwrap().verifying_key,before_key.verifying_key);
    let state=crate::DeploymentFrontierStore::<serde_json::Value>::open_protected(&f.config.state_dir.join("issuer")).unwrap();
    assert_eq!(state.load("local-final-use-issuer").unwrap()["sequence"],2);
    println!("{}",serde_json::json!({"qualification":"canonical_two_generation_required_material_startup",
        "old_spawn":1,"new_spawn":3,"old_local_generation":1,"new_local_generation":2,
        "original_key_sequence_retained":true,"actual_legacy_token":false,"original_root_material":true,
        "owner_factory_exact_current":true,"same_service_zero_arg_ready":true,"physical_prepare_commit":true,
        "sealed_production_receiver_qualified":false,"production_ready":false,"external_effect":false}));
}
