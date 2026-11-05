//! Real Root, original persisted owners and actual dedicated Worker children.
//! These cases qualify lane custody/CAS only, never a FinalUse effect owner.

use super::*;
use super::super::floor::ReservedWorkerFloor;
use codex_hepta_contracts::FinalUseFrontier;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

#[path = "worker_root_lanes_fixture.rs"]
mod lanes_fixture;
use lanes_fixture::LaneFixture;

fn child(original: &Fixture, mode: &str) -> (QualificationChild, UnixDatagram) {
    let (root, socket) = UnixDatagram::pair().unwrap();
    (QualificationChild::spawn(mode, &original.identity.agent_id, original.identity.spawn_generation, Some(socket), ChildIdentity::Worker), root)
}

fn private_records(directory: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    let mut result = BTreeMap::new();
    for entry in std::fs::read_dir(directory).unwrap() {
        let entry = entry.unwrap();
        let metadata = entry.path().symlink_metadata().unwrap();
        assert!(metadata.is_file());
        assert_eq!((metadata.uid(), metadata.nlink(), metadata.mode() & 0o777), (0, 1, 0o600));
        assert!(metadata.len() <= 64 * 1024);
        result.insert(entry.path(), std::fs::read(entry.path()).unwrap());
    }
    assert!(!result.is_empty() && result.len() <= 16);
    result
}

fn frontier_json(directory: &Path) -> serde_json::Value {
    let files = private_records(directory);
    let records = files.iter().filter(|(path, _)| path.extension().is_some_and(|ext| ext == "json")).collect::<Vec<_>>();
    assert_eq!(records.len(), 1);
    let value: serde_json::Value = serde_json::from_slice(records[0].1).unwrap();
    value["frontier"].clone()
}

fn original_consumer_records(fixture: &LaneFixture) -> Vec<BTreeMap<PathBuf, Vec<u8>>> {
    let config = &fixture.original.config;
    let consumers = config.consumers.as_ref().unwrap();
    [config.checkpoint_state_dir.as_ref().unwrap(), &consumers.device.state_dir, &consumers.notes.state_dir]
        .into_iter().map(|path| private_records(path)).collect()
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces, original SQLite and frozen Worker example required"]
fn root_worker_three_lanes_bind_real_child_and_independent_durable_cas_without_effect_authority() {
    let mut fixture = LaneFixture::open();
    let original = original_consumer_records(&fixture);
    fixture.original.session.as_ref().unwrap().provision_worker_frontier_fresh().unwrap();
    let slot = fixture.worker_path().join("current-slot");
    let frontier = fixture.worker_path().join("consumer-floor");
    let pristine_slot = private_records(&slot);
    assert!(fixture.original.session.as_ref().unwrap().provision_worker_frontier_fresh().is_err());
    assert_eq!(private_records(&slot), pristine_slot);
    let config = &fixture.original.config;
    let consumers = config.consumers.as_ref().unwrap();
    let worker_path = fixture.worker_path();
    let inodes = [&config.state_dir, &worker_path, &slot, &frontier,
        config.checkpoint_state_dir.as_ref().unwrap(), &consumers.device.state_dir, &consumers.notes.state_dir]
        .into_iter().map(|path| { let meta = path.symlink_metadata().unwrap(); (meta.dev(), meta.ino()) }).collect::<BTreeSet<_>>();
    assert_eq!(inodes.len(), 7, "Worker floor must not alias original issuer/checkpoint/consumer directories");
    let (mut worker, root) = child(&fixture.original, "lanes-roundtrip");
    let held = fixture.original.session.as_ref().unwrap().register_worker_child(
        &fixture.original.registry, &mut worker.child, root, Duration::from_secs(5),
    ).unwrap();
    let registration = held.observation().clone();
    held.serve_worker_lanes(Duration::from_secs(5), Duration::from_secs(15)).unwrap();
    let message = worker.message();
    assert_eq!(message["kind"], "three_original_lanes");
    let bootstrap: crate::WorkerRootLaneBootstrapV1 = serde_json::from_value(message["bootstrap"].clone()).unwrap();
    assert_eq!(bootstrap.registration, registration);
    assert_eq!(bootstrap.owner_id, fixture.original.config.signer_id);
    assert_eq!(bootstrap.consumer_namespace, super::super::floor::stable_namespace(&fixture.original.identity.agent_id).unwrap());
    assert_eq!(bootstrap.slot_sequence, 1);
    assert_eq!(message["original_proof"], serde_json::to_value(&bootstrap.writer_proof).unwrap());
    assert_eq!(message["effect_owner_created"], false);
    assert!(!bootstrap.effect_authorization_available);
    let next: FinalUseFrontier = serde_json::from_value(message["next_frontier"].clone()).unwrap();
    assert_eq!(message["after_exact_conflict"], message["next_frontier"]);
    assert_eq!(serde_json::from_value::<FinalUseFrontier>(frontier_json(&frontier)).unwrap(), next);
    assert_eq!(frontier_json(&slot)["state"]["phase"], "Serving");
    assert_eq!(original_consumer_records(&fixture), original);
    worker.finish();
    let retained = private_records(&slot);
    fixture.reopen_original();
    let (mut successor, root) = child(&fixture.original, "receive");
    let held = fixture.original.session.as_ref().unwrap().register_worker_child(
        &fixture.original.registry, &mut successor.child, root, Duration::from_secs(5),
    ).unwrap();
    assert_ne!(held.observation().consumer_namespace, registration.consumer_namespace);
    assert!(held.serve_worker_lanes(Duration::from_secs(1), Duration::from_secs(5)).is_err(), "new nonce/reopen cannot reset a consumed stable Agent slot");
    assert_eq!(successor.message()["kind"], "receipt");
    successor.finish();
    assert_eq!(private_records(&slot), retained);
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces, original SQLite and frozen Worker example required"]
fn root_worker_missing_or_partial_floor_is_never_genesis_repaired_by_runtime() {
    let fixture = LaneFixture::open();
    let (mut worker, root) = child(&fixture.original, "receive");
    let held = fixture.original.session.as_ref().unwrap().register_worker_child(
        &fixture.original.registry, &mut worker.child, root, Duration::from_secs(5),
    ).unwrap();
    assert!(held.serve_worker_lanes(Duration::from_secs(1), Duration::from_secs(5)).is_err());
    assert!(!fixture.worker_path().exists());
    assert_eq!(worker.message()["kind"], "receipt");
    worker.finish();
    std::fs::create_dir(fixture.worker_path()).unwrap();
    std::fs::set_permissions(fixture.worker_path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let partial = fixture.worker_path().symlink_metadata().unwrap();
    assert!(fixture.original.session.as_ref().unwrap().provision_worker_frontier_fresh().is_err());
    assert_eq!(std::fs::read_dir(fixture.worker_path()).unwrap().count(), 0);
    let after = fixture.worker_path().symlink_metadata().unwrap();
    assert_eq!((after.dev(), after.ino()), (partial.dev(), partial.ino()));
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces, original SQLite and two frozen Worker children required"]
fn root_worker_two_actual_children_cannot_claim_two_current_slots() {
    let fixture = LaneFixture::open();
    let session = fixture.original.session.as_ref().unwrap();
    session.provision_worker_frontier_fresh().unwrap();
    let (mut first, root1) = child(&fixture.original, "receive");
    let (mut second, root2) = child(&fixture.original, "receive");
    let held1 = session.register_worker_child(&fixture.original.registry, &mut first.child, root1, Duration::from_secs(5)).unwrap();
    let held2 = session.register_worker_child(&fixture.original.registry, &mut second.child, root2, Duration::from_secs(5)).unwrap();
    assert_ne!(held1.observation().worker, held2.observation().worker);
    assert_ne!(held1.observation().consumer_namespace, held2.observation().consumer_namespace);
    let reserved = ReservedWorkerFloor::reserve(session, held1.observation()).unwrap();
    assert!(ReservedWorkerFloor::reserve(session, held2.observation()).is_err());
    reserved.check_current().unwrap();
    let slot = frontier_json(&fixture.worker_path().join("current-slot"));
    assert_eq!(slot["slot_sequence"], 1);
    assert_eq!(slot["state"]["phase"], "Reserved");
    assert_eq!(slot["state"]["registration"], serde_json::to_value(held1.observation()).unwrap());
    drop(reserved); drop(held1); drop(held2);
    assert_eq!(first.message()["kind"], "receipt");
    assert_eq!(second.message()["kind"], "receipt");
    first.finish(); second.finish();
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces, original SQLite and frozen hostile original Child required"]
fn root_worker_second_ack_loss_leaves_consumed_slot_and_no_served_orphan_floor() {
    let mut fixture = LaneFixture::open();
    fixture.original.session.as_ref().unwrap().provision_worker_frontier_fresh().unwrap();
    let frontier = fixture.worker_path().join("consumer-floor");
    let before = private_records(&frontier);
    let (mut worker, root) = child(&fixture.original, "lanes-second-offer-no-ack");
    let held = fixture.original.session.as_ref().unwrap().register_worker_child(
        &fixture.original.registry, &mut worker.child, root, Duration::from_secs(5),
    ).unwrap();
    assert!(held.serve_worker_lanes(Duration::from_millis(500), Duration::from_secs(5)).is_err());
    let message = worker.message();
    assert_eq!(message["kind"], "second_offer_without_ack");
    assert_eq!(message["actual_connections"], 3);
    assert_eq!(message["frontier_response_bytes"], 0);
    assert_eq!(message["effect_owner_created"], false);
    assert_eq!(private_records(&frontier), before);
    let slot = fixture.worker_path().join("current-slot");
    let consumed = private_records(&slot);
    assert_eq!(frontier_json(&slot)["state"]["phase"], "Reserved");
    worker.finish();
    fixture.reopen_original();
    let (mut next, root) = child(&fixture.original, "receive");
    let held = fixture.original.session.as_ref().unwrap().register_worker_child(
        &fixture.original.registry, &mut next.child, root, Duration::from_secs(5),
    ).unwrap();
    assert!(held.serve_worker_lanes(Duration::from_secs(1), Duration::from_secs(5)).is_err());
    assert_eq!(next.message()["kind"], "receipt");
    next.finish();
    assert_eq!(private_records(&slot), consumed);
    assert_eq!(private_records(&frontier), before);
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces, original issuer registry and frozen daemon required"]
fn root_worker_revoked_original_issuer_cannot_provision_a_floor_with_live_writer() {
    let mut fixture = LaneFixture::open();
    drop(fixture.original.session.take());
    {
        let (_clock, leases, _issuer) = crate::authority_host_runtime::open_registered_issuer(&fixture.original.config).unwrap();
        leases.revoke(&fixture.original.config.lease_id, fixture.original.config.lease_revision, [0x62; 32]).unwrap();
        let writer = fixture.original.config.writer.as_ref().unwrap();
        leases.verifier().verify_use(&writer.authority_lease.lease_id, writer.authority_lease.revision, &writer.authority_lease.binding).unwrap();
    }
    fixture.reopen_original();
    assert!(fixture.original.session.as_ref().unwrap().provision_worker_frontier_fresh().is_err());
    assert!(!fixture.worker_path().exists(), "revocation cannot leave a freshly provisioned Worker slot");
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces, original Registry and frozen Worker required"]
fn root_worker_generation_change_after_registration_refuses_before_floor_reservation() {
    let fixture = LaneFixture::open();
    let session = fixture.original.session.as_ref().unwrap();
    session.provision_worker_frontier_fresh().unwrap();
    let slot = fixture.worker_path().join("current-slot");
    let before = private_records(&slot);
    let (mut worker, root) = child(&fixture.original, "receive");
    let held = session.register_worker_child(&fixture.original.registry, &mut worker.child, root, Duration::from_secs(5)).unwrap();
    let running = fixture.original.registry.compare_and_transition(&fixture.original.identity.agent_id, fixture.original.identity.spawn_generation, AgentLifecycle::Running).unwrap();
    fixture.original.registry.compare_and_transition(&fixture.original.identity.agent_id, running.generation, AgentLifecycle::Draining).unwrap();
    assert!(held.serve_worker_lanes(Duration::from_secs(1), Duration::from_secs(5)).is_err());
    assert_eq!(worker.message()["kind"], "receipt");
    worker.finish();
    assert_eq!(private_records(&slot), before, "stale original generation cannot consume an unclaimed slot");
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces, original Registry and frozen daemon required"]
fn root_worker_fresh_floor_requires_the_original_current_starting_or_running_agent() {
    let fixture = LaneFixture::open();
    let running = fixture.original.registry.compare_and_transition(&fixture.original.identity.agent_id, fixture.original.identity.spawn_generation, AgentLifecycle::Running).unwrap();
    fixture.original.registry.compare_and_transition(&fixture.original.identity.agent_id, running.generation, AgentLifecycle::Draining).unwrap();
    assert!(fixture.original.session.as_ref().unwrap().provision_worker_frontier_fresh().is_err());
    assert!(!fixture.worker_path().exists(), "a live old process cannot provision fresh state after its original Registry drains");
}

#[path = "worker_root_journal_root_tests.rs"]
mod journals;

#[path = "worker_root_current_head_root_tests.rs"]
mod current_head;
