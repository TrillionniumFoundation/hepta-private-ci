//! Original real Root factories and Child processes. These qualify a journal
//! composition, not final provider/tool use, cross-process successor recovery,
//! a Fleet/floor cross-store transaction or hostile-Root rollback resistance.

use super::*;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsRawFd;

fn journal_parent() -> tempfile::TempDir {
    let directory = tempfile::Builder::new().prefix("hepta-worker-journal-parent-").tempdir_in("/run").unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o711)).unwrap();
    let metadata = directory.path().symlink_metadata().unwrap();
    assert_eq!((metadata.uid(), metadata.mode() & 0o7777), (0, 0o711));
    directory
}

fn directory_for(parent: &Path, fixture: &LaneFixture) -> PathBuf {
    parent.join(crate::worker_root_registration::journal_wire::journal_basename(&fixture.original.identity.agent_id).unwrap())
}

fn run_real_child(mode: &str) -> (LaneFixture, tempfile::TempDir, serde_json::Value) {
    let fixture = LaneFixture::open();
    let parent = journal_parent();
    fixture.original.session.as_ref().unwrap().provision_worker_frontier_fresh().unwrap();
    let (mut worker, root) = child(&fixture.original, mode);
    let held = fixture.original.session.as_ref().unwrap().register_worker_child(&fixture.original.registry, &mut worker.child, root, Duration::from_secs(5)).unwrap();
    held.serve_worker_journal_lanes(parent.path(), Duration::from_secs(5), Duration::from_secs(15)).unwrap();
    let message = worker.message();
    worker.finish();
    (fixture, parent, message)
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces, original SQLite and frozen Worker example required"]
fn root_worker_journal_fresh_actual_uid_and_same_custody_reopen_use_original_floor() {
    let (mut fixture, parent, message) = run_real_child("journal-roundtrip");
    assert_eq!(message["kind"], "journal_roundtrip");
    let first = &message["first"];
    let second = &message["second"];
    assert_eq!(first["frontier"], second["frontier"]);
    assert_eq!(first["journal"], second["journal"]);
    assert_eq!(first["effect_authorization_available"], false);
    assert_eq!(second["effect_authorization_available"], false);
    assert_eq!(first["journal"]["worker_uid"], 60003);
    let directory = directory_for(parent.path(), &fixture);
    let metadata = directory.symlink_metadata().unwrap();
    assert_eq!((metadata.uid(), metadata.gid(), metadata.mode() & 0o7777), (60003, 60003, 0o700));
    assert_eq!(metadata.dev(), first["journal"]["directory_device"].as_u64().unwrap());
    assert_eq!(metadata.ino(), first["journal"]["directory_inode"].as_u64().unwrap());
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 3);
    for name in ["authority.lock", "authority.json", "authority.claims"] {
        let metadata = directory.join(name).symlink_metadata().unwrap();
        assert_eq!((metadata.uid(), metadata.gid(), metadata.mode() & 0o7777, metadata.nlink()), (60003, 60003, 0o600, 1));
    }
    let floor = fixture.worker_path().join("consumer-floor");
    assert_eq!(frontier_json(&floor), first["frontier"]);
    let binding = frontier_json(&fixture.worker_path().join("local-journal-custody-v1"));
    assert_eq!(binding["confirmed_after_original_child_ack"], true);
    assert_eq!(binding["directory"], first["journal"]);
    let slot = fixture.worker_path().join("current-slot");
    let consumed = private_records(&slot);
    let retained_floor = private_records(&floor);
    fixture.reopen_original();
    let (mut successor, root) = child(&fixture.original, "journal-refuse-before-offer");
    let held = fixture.original.session.as_ref().unwrap().register_worker_child(&fixture.original.registry, &mut successor.child, root, Duration::from_secs(5)).unwrap();
    assert!(held.serve_worker_journal_lanes(parent.path(), Duration::from_secs(1), Duration::from_secs(5)).is_err());
    assert_eq!(successor.message()["kind"], "journal_refused");
    successor.finish();
    assert_eq!(private_records(&slot), consumed);
    assert_eq!(private_records(&floor), retained_floor);
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces and frozen hostile original Worker required"]
fn root_worker_journal_second_ack_loss_never_initializes_or_serves_a_journal() {
    let fixture = LaneFixture::open();
    let parent = journal_parent();
    fixture.original.session.as_ref().unwrap().provision_worker_frontier_fresh().unwrap();
    let floor = fixture.worker_path().join("consumer-floor");
    let original = private_records(&floor);
    let (mut worker, root) = child(&fixture.original, "journal-second-offer-no-ack");
    let held = fixture.original.session.as_ref().unwrap().register_worker_child(&fixture.original.registry, &mut worker.child, root, Duration::from_secs(5)).unwrap();
    assert!(held.serve_worker_journal_lanes(parent.path(), Duration::from_millis(500), Duration::from_secs(5)).is_err());
    let message = worker.message();
    assert_eq!(message["kind"], "journal_offer_without_ack");
    assert_eq!(message["journal_files_created"], 0);
    assert_eq!(message["frontier_response_bytes"], 0);
    assert_eq!(message["actual_connections"], 3);
    assert!(std::fs::read_dir(directory_for(parent.path(), &fixture)).unwrap().next().is_none());
    assert_eq!(frontier_json(&fixture.worker_path().join("current-slot"))["state"]["phase"], "Reserved");
    assert_eq!(frontier_json(&fixture.worker_path().join("local-journal-custody-v1"))["confirmed_after_original_child_ack"], false);
    assert_eq!(private_records(&floor), original);
    worker.finish();
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces and frozen Worker required"]
fn root_worker_journal_partial_leaf_is_not_repaired_or_reclassified_fresh() {
    let fixture = LaneFixture::open();
    let parent = journal_parent();
    fixture.original.session.as_ref().unwrap().provision_worker_frontier_fresh().unwrap();
    let directory = directory_for(parent.path(), &fixture);
    std::fs::create_dir(&directory).unwrap();
    std::os::unix::fs::chown(&directory, Some(60003), Some(60003)).unwrap();
    std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).unwrap();
    let marker = directory.join("authority.lock");
    std::fs::write(&marker, b"retain partial first attempt").unwrap();
    std::os::unix::fs::chown(&marker, Some(60003), Some(60003)).unwrap();
    std::fs::set_permissions(&marker, std::fs::Permissions::from_mode(0o600)).unwrap();
    let before = directory.symlink_metadata().unwrap();
    let (mut worker, root) = child(&fixture.original, "journal-refuse-before-offer");
    let held = fixture.original.session.as_ref().unwrap().register_worker_child(&fixture.original.registry, &mut worker.child, root, Duration::from_secs(5)).unwrap();
    assert!(held.serve_worker_journal_lanes(parent.path(), Duration::from_secs(1), Duration::from_secs(5)).is_err());
    assert_eq!(worker.message()["kind"], "journal_refused");
    worker.finish();
    let after = directory.symlink_metadata().unwrap();
    assert_eq!((after.dev(), after.ino(), after.uid(), after.gid(), after.mode()), (before.dev(), before.ino(), before.uid(), before.gid(), before.mode()));
    assert_eq!(std::fs::read(marker).unwrap(), b"retain partial first attempt");
    assert_eq!(std::fs::read_dir(directory).unwrap().count(), 1);
    assert_eq!(frontier_json(&fixture.worker_path().join("current-slot"))["state"]["phase"], "Reserved");
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces and frozen Worker required"]
fn root_worker_journal_missing_snapshot_is_not_genesis_repaired() {
    let (fixture, parent, message) = run_real_child("journal-missing-snapshot");
    assert_eq!(message["kind"], "journal_missing_snapshot_refused");
    assert_eq!(message["snapshot_recreated"], false);
    assert!(!directory_for(parent.path(), &fixture).join("authority.json").exists());
    assert_eq!(frontier_json(&fixture.worker_path().join("consumer-floor")), message["first"]["frontier"]);
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces and frozen Worker required"]
fn root_worker_journal_replaced_lock_cannot_revive_after_restoring_original_name() {
    let (_fixture, _parent, message) = run_real_child("journal-replaced-lock");
    assert_eq!(message["kind"], "journal_replacement_refused");
    assert_eq!(message["file"], "authority.lock");
    assert_eq!(message["bytes_equal_before_refusal"], true);
    assert_ne!(message["original_inode"], message["copied_inode"]);
    assert_eq!(message["restored_owner_revived"], false);
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces and frozen Worker required"]
fn root_worker_journal_byte_identical_claims_copy_is_not_the_retained_owner() {
    let (_fixture, _parent, message) = run_real_child("journal-copied-claims");
    assert_eq!(message["kind"], "journal_replacement_refused");
    assert_eq!(message["file"], "authority.claims");
    assert_eq!(message["bytes_equal_before_refusal"], true);
    assert_ne!(message["original_inode"], message["copied_inode"]);
    assert_eq!(message["restored_owner_revived"], false);
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces and frozen Worker required"]
fn root_worker_journal_stale_projection_cannot_be_refreshed_into_a_new_owner() {
    let (_fixture, _parent, message) = run_real_child("journal-clock-stale");
    assert_eq!(message["kind"], "journal_clock_stale_refused");
    assert_eq!(message["same_owner_revived"], false);
    assert_eq!(message["clock_window_ns"], 500_000_000_u64);
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces, original Registry and frozen Worker required"]
fn root_worker_journal_original_generation_change_refuses_before_any_directory_handoff() {
    let fixture = LaneFixture::open();
    let parent = journal_parent();
    let session = fixture.original.session.as_ref().unwrap();
    session.provision_worker_frontier_fresh().unwrap();
    let slot = fixture.worker_path().join("current-slot");
    let original = private_records(&slot);
    let (mut worker, root) = child(&fixture.original, "journal-refuse-before-offer");
    let held = session.register_worker_child(&fixture.original.registry, &mut worker.child, root, Duration::from_secs(5)).unwrap();
    let running = fixture.original.registry.compare_and_transition(&fixture.original.identity.agent_id, fixture.original.identity.spawn_generation, AgentLifecycle::Running).unwrap();
    fixture.original.registry.compare_and_transition(&fixture.original.identity.agent_id, running.generation, AgentLifecycle::Draining).unwrap();
    assert!(held.serve_worker_journal_lanes(parent.path(), Duration::from_secs(1), Duration::from_secs(5)).is_err());
    assert_eq!(worker.message()["kind"], "journal_refused");
    worker.finish();
    assert!(std::fs::read_dir(parent.path()).unwrap().next().is_none());
    assert_eq!(private_records(&slot), original);
}

#[test]
#[ignore = "actual UID0, private bind/run namespaces, original issuer revoke and frozen Worker required"]
fn root_worker_journal_original_revoke_advances_real_floor_then_rejects_old_snapshot() {
    let fixture = LaneFixture::open();
    let parent = journal_parent();
    let session = fixture.original.session.as_ref().unwrap();
    session.provision_worker_frontier_fresh().unwrap();
    let (mut worker, root) = child(&fixture.original, "journal-head-and-rollback");
    let mut output = worker.child.stdout.take().unwrap();
    let mut input = worker.child.stdin.take().unwrap();
    let held = session.register_worker_child(&fixture.original.registry, &mut worker.child, root, Duration::from_secs(5)).unwrap();
    let (first, advanced, rejected, original_head) = std::thread::scope(|scope| {
        let server = scope.spawn(|| held.serve_worker_journal_lanes(parent.path(), Duration::from_secs(5), Duration::from_secs(15)));
        let first = read_message(&mut output);
        assert_eq!(first["kind"], "journal_ready_for_original_root_revoke");
        // This test-only forwarder calls the SAME retained original issuer.
        // It creates no alternate key, injected clock or synthetic owner.
        let head = session.service.revoke_worker_journal_qualification_grant("worker-journal-original-root-revocation").unwrap();
        input.write_all(&[2]).unwrap();
        let advanced = read_message(&mut output);
        assert_eq!(advanced["kind"], "journal_original_head_and_floor_advanced");
        assert_eq!(advanced["advanced"]["revocations"], serde_json::to_value(&head).unwrap());
        input.write_all(&[3]).unwrap();
        let rejected = read_message(&mut output);
        assert_eq!(rejected["kind"], "journal_old_snapshot_refused");
        assert_eq!(rejected["snapshot_repaired"], false);
        server.join().unwrap().unwrap();
        (first, advanced, rejected, head)
    });
    worker.child.stdout = Some(output);
    worker.child.stdin = Some(input);
    worker.finish();
    assert_ne!(first["first"]["frontier"], advanced["advanced"]["frontier"]);
    assert_eq!(frontier_json(&fixture.worker_path().join("consumer-floor")), advanced["advanced"]["frontier"]);
    assert_eq!(rejected["advanced"]["revocations"], serde_json::to_value(original_head).unwrap());
    assert_eq!(rejected["effect_authorization_available"], false);
}

fn read_message(output: &mut std::process::ChildStdout) -> serde_json::Value {
    let mut descriptor = libc::pollfd { fd: output.as_raw_fd(), events: libc::POLLIN, revents: 0 };
    // SAFETY: this is the retained original owned Child's stdout. The bound
    // matches the pre-existing fixture message reader; no PID lookup is used.
    assert!(unsafe { libc::poll(&mut descriptor, 1, 10_000) } > 0);
    let mut length = [0; 4];
    output.read_exact(&mut length).unwrap();
    let length = u32::from_be_bytes(length) as usize;
    assert!((1..=64 * 1024).contains(&length));
    let mut bytes = vec![0; length];
    output.read_exact(&mut bytes).unwrap();
    serde_json::from_slice(&bytes).unwrap()
}
