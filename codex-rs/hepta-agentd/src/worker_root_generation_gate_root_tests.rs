//! Actual Root/Worker requests contend with the original lifecycle writer.
//! A test-only scheduling pause does not supply any owner or response.

use super::*;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistryError;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsRawFd;

fn running_fixture() -> LaneFixture {
    let fixture = LaneFixture::open();
    fixture.original.registry.compare_and_transition(
        &fixture.original.identity.agent_id,
        fixture.original.identity.spawn_generation,
        AgentLifecycle::Running,
    ).unwrap();
    fixture.original.session.as_ref().unwrap().provision_worker_frontier_fresh().unwrap();
    fixture
}

fn other_process_write(fixture: &LaneFixture, expected: u64) -> serde_json::Value {
    let mut writer = QualificationChild::spawn(
        "root-lifecycle-write", &fixture.original.identity.agent_id, expected,
        /*socket*/ None, ChildIdentity::Root,
    );
    let bytes = serde_json::to_vec(fixture.original.registry.layout().fleet_root().as_path()).unwrap();
    let input = writer.child.stdin.as_mut().unwrap();
    input.write_all(&(bytes.len() as u32).to_be_bytes()).unwrap();
    input.write_all(&bytes).unwrap();
    input.flush().unwrap();
    let report = writer.message();
    assert_eq!(report["pid"], writer.child.id());
    assert_ne!(writer.child.id(), std::process::id());
    writer.finish();
    report
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces, original issuer and frozen Worker example required"]
fn root_worker_live_consumer_request_excludes_same_and_other_process_lifecycle_writers() {
    let fixture = running_fixture();
    let session = fixture.original.session.as_ref().unwrap();
    let agent = &fixture.original.identity.agent_id;
    let before = fixture.original.registry.load_agent(agent).unwrap();
    let floor = fixture.worker_path().join("consumer-floor");
    let original_floor = private_records(&floor);
    let consumers = original_consumer_records(&fixture);
    let (mut worker, root) = child(&fixture.original, "lanes-lifecycle-gate");
    let mut input = worker.child.stdin.take().unwrap();
    let mut output = worker.child.stdout.take().unwrap();
    let held = session.register_worker_child(
        &fixture.original.registry, &mut worker.child, root, Duration::from_secs(5),
    ).unwrap();
    let registration = held.observation().clone();
    let (ready, local, remote, during, first, successor, last, server) = std::thread::scope(|scope| {
        let server = scope.spawn(|| held.serve_worker_lanes(Duration::from_secs(5), Duration::from_secs(15)));
        let ready = read_message(&mut output);
        let pause = super::super::super::generation_pause::arm(&registration).unwrap();
        input.write_all(&[2]).unwrap();
        pause.wait_entered().unwrap();
        // The real Root callback is now in flight. Neither contender supplies
        // a fake generation, authority, lock result or alternate issuer.
        let local = fixture.original.registry.compare_and_transition(
            agent, before.lifecycle.generation, AgentLifecycle::Draining,
        );
        let remote = other_process_write(&fixture, before.lifecycle.generation);
        let during = fixture.original.registry.load_agent(agent).unwrap();
        drop(pause);
        let first = read_message(&mut output);
        // This is a new call after the independently observed gate closes.
        // A WouldBlock result published nothing; no unknown CAS is replayed.
        let successor = fixture.original.registry.compare_and_transition(
            agent, before.lifecycle.generation, AgentLifecycle::Draining,
        );
        input.write_all(&[3]).unwrap();
        let last = read_message(&mut output);
        let server = server.join().unwrap();
        (ready, local, remote, during, first, successor, last, server)
    });
    worker.child.stdin = Some(input);
    worker.child.stdout = Some(output);
    worker.finish();
    assert_eq!(ready["kind"], "worker_ready_for_lifecycle_gate");
    assert_eq!(ready["effect_authorization_available"], false);
    assert!(
        matches!(&local, Err(FleetRegistryError::Io(error)) if error.kind() == std::io::ErrorKind::WouldBlock),
        "a real in-flight Root consumer request must exclude the original same-process lifecycle writer: {local:?}",
    );
    assert_eq!((remote["kind"].as_str(), remote["uid"].as_u64(), remote["would_block"].as_bool(), remote["published"].as_bool()),
        (Some("original_lifecycle_writer_result"), Some(0), Some(true), Some(false)));
    assert_eq!(remote["before"], serde_json::to_value(&before.lifecycle).unwrap());
    assert_eq!(remote["after"], remote["before"]);
    assert_eq!(during, before);
    assert_eq!(first["accepted"], true);
    assert_eq!(first["frontier"], frontier_json(&floor));
    let successor = successor.unwrap();
    assert_eq!((successor.generation, successor.lifecycle),
        (before.lifecycle.generation + 1, AgentLifecycle::Draining));
    assert_eq!((last["load_refused"].as_bool(), last["observation_refused"].as_bool()),
        (Some(true), Some(true)));
    assert!(server.is_err());
    assert_eq!(private_records(&floor), original_floor);
    assert_eq!(original_consumer_records(&fixture), consumers);
    let proof = session.service.with_worker_floor_fence(/*expected*/ None, |view| {
        assert!(view.observed_unix_ms < view.expires_at_unix_ms);
        Ok(view.writer_proof.clone())
    }).unwrap();
    assert_eq!(serde_json::to_value(proof).unwrap(), ready["writer_proof"]);
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces, original issuer and frozen Worker example required"]
fn root_worker_request_refuses_a_live_exclusive_generation_gate_and_fences_its_receipt() {
    let fixture = running_fixture();
    let session = fixture.original.session.as_ref().unwrap();
    let agent = &fixture.original.identity.agent_id;
    let before = fixture.original.registry.load_agent(agent).unwrap();
    let floor = fixture.worker_path().join("consumer-floor");
    let original_floor = private_records(&floor);
    let (mut worker, root) = child(&fixture.original, "lanes-lifecycle-gate");
    let mut input = worker.child.stdin.take().unwrap();
    let mut output = worker.child.stdout.take().unwrap();
    let held = session.register_worker_child(
        &fixture.original.registry, &mut worker.child, root, Duration::from_secs(5),
    ).unwrap();
    let (ready, first, last, server) = std::thread::scope(|scope| {
        let server = scope.spawn(|| held.serve_worker_lanes(Duration::from_secs(5), Duration::from_secs(15)));
        let ready = read_message(&mut output);
        let exclusive = File::open(before.layout.run_root()).unwrap();
        exclusive.try_lock().unwrap();
        input.write_all(&[2]).unwrap();
        let first = read_message(&mut output);
        drop(exclusive);
        assert_eq!(fixture.original.registry.load_agent(agent).unwrap(), before);
        // Releasing a contended gate must not revive the same Worker receipt.
        input.write_all(&[3]).unwrap();
        let last = read_message(&mut output);
        let server = server.join().unwrap();
        (ready, first, last, server)
    });
    worker.child.stdin = Some(input);
    worker.child.stdout = Some(output);
    worker.finish();
    assert_eq!(ready["kind"], "worker_ready_for_lifecycle_gate");
    assert_eq!(first["accepted"], false,
        "the actual Root consumer lane must refuse an independently held exclusive generation gate");
    assert_eq!((last["load_refused"].as_bool(), last["observation_refused"].as_bool()),
        (Some(true), Some(true)));
    assert!(server.is_err());
    assert_eq!(fixture.original.registry.load_agent(agent).unwrap(), before);
    assert_eq!(private_records(&floor), original_floor);
    let proof = session.service.with_worker_floor_fence(/*expected*/ None, |view| {
        assert!(view.observed_unix_ms < view.expires_at_unix_ms);
        Ok(view.writer_proof.clone())
    }).unwrap();
    assert_eq!(serde_json::to_value(proof).unwrap(), ready["writer_proof"]);
}

fn read_message(output: &mut std::process::ChildStdout) -> serde_json::Value {
    let mut descriptor = libc::pollfd { fd: output.as_raw_fd(), events: libc::POLLIN, revents: 0 };
    // SAFETY: the retained original Child owns this stdout. This poll bounds
    // first readability; subsequent read_exact retains the native runner bound.
    assert!(unsafe { libc::poll(&mut descriptor, 1, 10_000) } > 0);
    let mut length = [0; 4];
    output.read_exact(&mut length).unwrap();
    let length = u32::from_be_bytes(length) as usize;
    assert!((1..=64 * 1024).contains(&length));
    let mut bytes = vec![0; length];
    output.read_exact(&mut bytes).unwrap();
    serde_json::from_slice(&bytes).unwrap()
}
