//! Privileged original-factory tests. These qualify only registration custody.

use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use pretty_assertions::assert_eq;

#[path = "worker_root_registration_fixture.rs"]
mod fixture;
use fixture::ChildIdentity;
use fixture::Fixture;
use fixture::QualificationChild;

#[path = "worker_root_lanes_root_tests.rs"]
mod lanes;

#[test]
#[ignore = "actual UID0, private data bind and frozen dedicated child example required"]
fn root_worker_receives_exact_sealed_registration_with_independent_namespace() {
    let fixture = Fixture::open();
    let (root, child) = UnixDatagram::pair().unwrap();
    let mut worker = QualificationChild::spawn(
        "receive",
        &fixture.identity.agent_id,
        fixture.identity.spawn_generation,
        Some(child),
        ChildIdentity::Worker,
    );
    let actual = process::observe(worker.child.id()).unwrap();
    let held = fixture
        .session
        .as_ref()
        .unwrap()
        .register_worker_child(
            &fixture.registry,
            &mut worker.child,
            root,
            Duration::from_secs(5),
        )
        .unwrap();
    let expected = held.observation().clone();
    assert_eq!(expected.worker, actual);
    assert_eq!(expected.root, process::observe(std::process::id()).unwrap());
    assert_eq!(
        expected.agentd,
        process::observe(fixture.daemon.child.id()).unwrap()
    );
    assert_eq!(expected.writer, fixture.config.writer.clone().unwrap());
    assert_eq!(expected.registered_agent_id, fixture.identity.agent_id);
    assert_eq!(expected.spawn_generation, fixture.identity.spawn_generation);
    assert!(
        expected
            .consumer_namespace
            .starts_with("worker-final-use-v1:")
    );
    assert!(!fixture.config.state_dir.join("device-consumer").exists());
    assert!(!fixture.config.state_dir.join("notes-consumer").exists());
    // Read the child's response directly while the exact Child borrow and
    // Root owner are retained. No File/JSON value can activate a consumer.
    let stdout = held._child.stdout.as_mut().unwrap();
    let mut length = [0; 4];
    stdout.read_exact(&mut length).unwrap();
    let length = u32::from_be_bytes(length) as usize;
    assert!((1..=64 * 1024).contains(&length));
    let mut bytes = vec![0; length];
    stdout.read_exact(&mut bytes).unwrap();
    let message: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(
        message,
        serde_json::json!({"kind":"receipt", "observation":expected})
    );
    drop(held);
    worker.finish();
}

#[test]
#[ignore = "actual UID0, private data bind and frozen dedicated child example required"]
fn root_worker_lost_ack_retains_no_activated_registration() {
    let fixture = Fixture::open();
    let (root, child) = UnixDatagram::pair().unwrap();
    let mut worker = QualificationChild::spawn(
        "drop-ack",
        &fixture.identity.agent_id,
        fixture.identity.spawn_generation,
        Some(child),
        ChildIdentity::Worker,
    );
    let result = fixture.session.as_ref().unwrap().register_worker_child(
        &fixture.registry,
        &mut worker.child,
        root,
        Duration::from_millis(500),
    );
    assert!(
        result.is_err(),
        "a delivered offer without ACK must never return Root custody"
    );
    drop(result);
    let message = worker.message();
    assert_eq!(message["kind"], "offered_unacknowledged");
    assert!(message["sealed_bytes"].as_u64().unwrap() > 0);
    assert!(!fixture.config.state_dir.join("worker-consumer").exists());
    worker.finish();
}

#[test]
#[ignore = "actual UID0, private data bind and frozen dedicated child example required"]
fn root_worker_send_failure_and_receiver_exit_leave_no_held_registration() {
    let fixture = Fixture::open();
    let (root, child) = UnixDatagram::pair().unwrap();
    let mut closed = QualificationChild::spawn(
        "closed-receiver",
        &fixture.identity.agent_id,
        fixture.identity.spawn_generation,
        Some(child),
        ChildIdentity::Worker,
    );
    assert_eq!(closed.message()["kind"], "receiver_closed_before_offer");
    let result = fixture.session.as_ref().unwrap().register_worker_child(
        &fixture.registry,
        &mut closed.child,
        root,
        Duration::from_millis(500),
    );
    assert!(
        result.is_err(),
        "failed descriptor delivery cannot return retained Root custody"
    );
    drop(result);
    assert!(!fixture.config.state_dir.join("worker-consumer").exists());
    closed.finish();

    let (root, child) = UnixDatagram::pair().unwrap();
    let mut interrupted = QualificationChild::spawn(
        "exit-after-offer",
        &fixture.identity.agent_id,
        fixture.identity.spawn_generation,
        Some(child),
        ChildIdentity::Worker,
    );
    let result = fixture.session.as_ref().unwrap().register_worker_child(
        &fixture.registry,
        &mut interrupted.child,
        root,
        Duration::from_millis(500),
    );
    assert!(
        result.is_err(),
        "receiver exit after the real sealed offer cannot return Root custody"
    );
    drop(result);
    let message = interrupted.message();
    assert_eq!(message["kind"], "offered_unacknowledged");
    assert!(message["sealed_bytes"].as_u64().unwrap() > 0);
    interrupted.wait_for_exit();
    assert!(!fixture.config.state_dir.join("worker-consumer").exists());
}

#[test]
#[ignore = "actual UID0, private data bind and frozen dedicated child example required"]
fn root_worker_wrong_agent_receiver_refuses_before_ack() {
    let fixture = Fixture::open();
    let (root, child) = UnixDatagram::pair().unwrap();
    let wrong = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").unwrap();
    let mut worker = QualificationChild::spawn(
        "wrong-agent",
        &wrong,
        fixture.identity.spawn_generation,
        Some(child),
        ChildIdentity::Worker,
    );
    let result = fixture.session.as_ref().unwrap().register_worker_child(
        &fixture.registry,
        &mut worker.child,
        root,
        Duration::from_millis(500),
    );
    assert!(result.is_err());
    drop(result);
    let message = worker.message();
    assert_eq!(message["kind"], "refused");
    assert!(
        message["error"]
            .as_str()
            .unwrap()
            .contains("expected original Agent differs")
    );
    worker.finish();
}

#[test]
#[ignore = "actual UID0, private data bind and frozen dedicated child example required"]
fn root_worker_cannot_reuse_agentd_or_root_or_dead_child_lifetime() {
    let mut fixture = Fixture::open();
    let (root, _unused) = UnixDatagram::pair().unwrap();
    let error = fixture
        .session
        .as_ref()
        .unwrap()
        .register_worker_child(
            &fixture.registry,
            &mut fixture.daemon.child,
            root,
            Duration::from_secs(1),
        )
        .err()
        .expect("actual Agentd cannot be a dedicated Worker");
    assert!(error.to_string().contains("cannot impersonate"));

    let mut privileged = QualificationChild::spawn(
        "owner",
        &fixture.identity.agent_id,
        fixture.identity.spawn_generation,
        /*socket*/ None,
        ChildIdentity::Root,
    );
    let (root, _unused) = UnixDatagram::pair().unwrap();
    let error = fixture
        .session
        .as_ref()
        .unwrap()
        .register_worker_child(
            &fixture.registry,
            &mut privileged.child,
            root,
            Duration::from_secs(1),
        )
        .err()
        .expect("Root child must be refused");
    assert!(error.to_string().contains("dedicated non-Root Worker"));
    privileged.finish();

    let mut same_principal = QualificationChild::spawn(
        "owner",
        &fixture.identity.agent_id,
        fixture.identity.spawn_generation,
        /*socket*/ None,
        ChildIdentity::Agentd,
    );
    let (root, _unused) = UnixDatagram::pair().unwrap();
    let error = fixture
        .session
        .as_ref()
        .unwrap()
        .register_worker_child(
            &fixture.registry,
            &mut same_principal.child,
            root,
            Duration::from_secs(1),
        )
        .err()
        .expect("a distinct PID under the Agentd principal is not an independent Worker");
    assert!(error.to_string().contains("independent non-Root UID/GID"));
    same_principal.finish();

    let mut retired = QualificationChild::spawn(
        "owner",
        &fixture.identity.agent_id,
        fixture.identity.spawn_generation,
        /*socket*/ None,
        ChildIdentity::Worker,
    );
    retired.finish();
    let (root, _unused) = UnixDatagram::pair().unwrap();
    let error = fixture
        .session
        .as_ref()
        .unwrap()
        .register_worker_child(
            &fixture.registry,
            &mut retired.child,
            root,
            Duration::from_secs(1),
        )
        .err()
        .expect("exited Child must be refused");
    assert!(error.to_string().contains("child already exited"));
}

#[test]
#[ignore = "actual UID0, private data bind and frozen dedicated child example required"]
fn root_worker_draining_and_newer_spawn_refuse_old_original_generation() {
    let fixture = Fixture::open();
    let mut worker = QualificationChild::spawn(
        "owner",
        &fixture.identity.agent_id,
        fixture.identity.spawn_generation,
        /*socket*/ None,
        ChildIdentity::Worker,
    );
    let current = fixture
        .registry
        .compare_and_transition(
            &fixture.identity.agent_id,
            fixture.identity.spawn_generation,
            AgentLifecycle::Running,
        )
        .unwrap();
    let draining = fixture
        .registry
        .compare_and_transition(
            &fixture.identity.agent_id,
            current.generation,
            AgentLifecycle::Draining,
        )
        .unwrap();
    let (root, _unused) = UnixDatagram::pair().unwrap();
    let error = fixture
        .session
        .as_ref()
        .unwrap()
        .register_worker_child(
            &fixture.registry,
            &mut worker.child,
            root,
            Duration::from_secs(1),
        )
        .err()
        .expect("Draining cannot register a new Worker");
    assert!(
        error
            .to_string()
            .contains("current Starting or Running spawn")
    );
    let stopped = fixture
        .registry
        .compare_and_transition(
            &fixture.identity.agent_id,
            draining.generation,
            AgentLifecycle::Stopped,
        )
        .unwrap();
    fixture
        .registry
        .compare_and_transition(
            &fixture.identity.agent_id,
            stopped.generation,
            AgentLifecycle::Starting,
        )
        .unwrap();
    let (root, _unused) = UnixDatagram::pair().unwrap();
    let error = fixture
        .session
        .as_ref()
        .unwrap()
        .register_worker_child(
            &fixture.registry,
            &mut worker.child,
            root,
            Duration::from_secs(1),
        )
        .err()
        .expect("new Starting generation must fence the prior spawn");
    assert!(error.to_string().contains("latest Starting transition"));
    worker.finish();
}

#[test]
#[ignore = "actual UID0, private data bind and frozen dedicated child example required"]
fn root_worker_revoked_canonical_issuer_refuses_even_with_live_original_writer() {
    let mut fixture = Fixture::open();
    drop(fixture.session.take());
    {
        let (_clock, leases, _issuer) =
            crate::authority_host_runtime::open_registered_issuer(&fixture.config).unwrap();
        leases
            .revoke(
                &fixture.config.lease_id,
                fixture.config.lease_revision,
                [8; 32],
            )
            .unwrap();
        let writer = fixture.config.writer.as_ref().unwrap();
        leases
            .verifier()
            .verify_use(
                &writer.authority_lease.lease_id,
                writer.authority_lease.revision,
                &writer.authority_lease.binding,
            )
            .unwrap();
    }
    // Historical retained writer readback is allowed to reopen. This test
    // isolates the NEW Worker registration's canonical issuer veto.
    fixture.session = Some(
        PreparedHostAuthoritySession::open(
            &fixture.config_path,
            &fixture.registration_path,
            fixture.daemon.pidfd.try_clone().unwrap(),
        )
        .unwrap(),
    );
    let mut worker = QualificationChild::spawn(
        "owner",
        &fixture.identity.agent_id,
        fixture.identity.spawn_generation,
        /*socket*/ None,
        ChildIdentity::Worker,
    );
    let (root, _unused) = UnixDatagram::pair().unwrap();
    let error = fixture
        .session
        .as_ref()
        .unwrap()
        .register_worker_child(
            &fixture.registry,
            &mut worker.child,
            root,
            Duration::from_secs(1),
        )
        .err()
        .expect("revoked original issuer cannot register a Worker");
    assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
    worker.finish();
}
