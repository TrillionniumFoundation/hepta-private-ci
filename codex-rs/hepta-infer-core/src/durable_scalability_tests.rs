//! Real-file regression tests for the cooperative local journal profile.
//! The paused-worker fixture is not a provider or target-host qualification.

use super::*;
use native::NativeDispatch;
use native::NativeRequest;
use native::NativeReservationState;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "hepta-journal-regression-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).unwrap();
        Self(path)
    }

    fn path(&self) -> PathBuf {
        self.0.join("inference.journal")
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn request(id: &str) -> NativeRequest {
    NativeRequest {
        request_id: id.to_string(),
        principal_id: "agent-1".to_string(),
        worker_generation: 1,
        model: "fixture-model".to_string(),
        payload_digest: "a".repeat(64),
    }
}

fn dispatch() -> NativeDispatch {
    NativeDispatch {
        thread_id: "thread-1".to_string(),
        model_provider: "fixture-provider".to_string(),
        context_digest: "b".repeat(64),
    }
}

#[test]
fn duplicate_reserved_callers_cannot_both_claim_external_dispatch() {
    let fixture = Fixture::new();
    let mut first = DurableInferenceControl::open(fixture.path(), 8).unwrap();
    let mut second = DurableInferenceControl::open(fixture.path(), 8).unwrap();
    first.reserve_native(request("r1"), 2).unwrap();
    second.reserve_native(request("r1"), 2).unwrap();
    first.dispatch_native("r1", dispatch()).unwrap();
    let committed = fs::read(fixture.path()).unwrap();
    assert_eq!(second.dispatch_native("r1", dispatch()), Err(Error::InvalidTransition));
    assert_eq!(fs::read(fixture.path()).unwrap(), committed);
    drop(first);
    drop(second);
    let mut reopened = DurableInferenceControl::open(fixture.path(), 8).unwrap();
    assert_eq!(reopened.dispatch_native("r1", dispatch()), Err(Error::InvalidTransition));
    assert_eq!(reopened.native_record("r1").unwrap().state, NativeReservationState::Dispatching);
}

#[test]
fn paused_external_work_does_not_hold_the_journal_writer() {
    let fixture = Fixture::new();
    let path = fixture.path();
    let (ready_tx, ready_rx) = mpsc::channel();
    let (resume_tx, resume_rx) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        let mut control = DurableInferenceControl::open(path, 8).unwrap();
        control.reserve_native(request("slow"), 2).unwrap();
        control.dispatch_native("slow", dispatch()).unwrap();
        ready_tx.send(()).unwrap();
        resume_rx.recv_timeout(Duration::from_secs(10)).unwrap();
        // Keep the control handle alive throughout the simulated external wait.
        control.cancel_native("slow").unwrap();
    });
    ready_rx.recv_timeout(Duration::from_secs(10)).unwrap();
    let mut independent = DurableInferenceControl::open(fixture.path(), 8).unwrap();
    independent.reserve_native(request("fast"), 2).unwrap();
    independent.dispatch_native("fast", dispatch()).unwrap();
    resume_tx.send(()).unwrap();
    worker.join().unwrap();
    drop(independent);
    let reopened = DurableInferenceControl::open(fixture.path(), 8).unwrap();
    assert_eq!(reopened.native_record("slow").unwrap().state, NativeReservationState::Cancelling);
    assert_eq!(reopened.native_record("fast").unwrap().state, NativeReservationState::Dispatching);
}

#[test]
fn unchanged_owner_reuses_cut_but_peer_writes_force_refresh() {
    let fixture = Fixture::new();
    let mut first = DurableInferenceControl::open(fixture.path(), 512).unwrap();
    for index in 0..128 {
        let id = format!("r{index}");
        first.reserve_native(request(&id), 2).unwrap();
        first.stop_native_before_dispatch(&id, "fixture stop".to_string()).unwrap();
    }
    assert_eq!(first.replay_stats().full_replays, 1);
    assert_eq!(first.replay_stats().replayed_bytes, 0);
    assert_eq!(first.replay_stats().unchanged_reuses, 256);
    let mut peer = DurableInferenceControl::open(fixture.path(), 512).unwrap();
    peer.reserve_native(request("peer"), 2).unwrap();
    first.reserve_native(request("local"), 2).unwrap();
    assert_eq!(first.replay_stats().full_replays, 2);
    assert!(first.replay_stats().replayed_bytes > 0);
    assert!(first.native_record("peer").is_some());
    assert_eq!(first.native_record("r0").unwrap().state, NativeReservationState::Released);
}

#[test]
fn missing_active_journal_is_not_recreated_by_a_stale_handle() {
    let fixture = Fixture::new();
    let mut control = DurableInferenceControl::open(fixture.path(), 8).unwrap();
    control.reserve_native(request("r1"), 2).unwrap();
    fs::remove_file(fixture.path()).unwrap();
    assert!(control.reserve_native(request("r2"), 2).is_err());
    assert!(!fixture.path().exists());
}

#[test]
fn same_size_replacement_is_not_mistaken_for_an_unchanged_cut() {
    let fixture = Fixture::new();
    let mut control = DurableInferenceControl::open(fixture.path(), 8).unwrap();
    control.reserve_native(request("r1"), 2).unwrap();
    let mut corrupt = fs::read(fixture.path()).unwrap();
    corrupt[0] = b'!';
    let replacement = fixture.0.join("replacement");
    let mut file = fresh_private_temporary(&replacement).unwrap();
    file.write_all(&corrupt).unwrap();
    file.sync_all().unwrap();
    fs::rename(replacement, fixture.path()).unwrap();
    assert!(control.dispatch_native("r1", dispatch()).is_err());
    assert_eq!(fs::read(fixture.path()).unwrap(), corrupt);
}

#[test]
fn compaction_preserves_private_modes_reclaims_orphan_and_refreshes_peers() {
    let fixture = Fixture::new();
    let mut first = DurableInferenceControl::open(fixture.path(), 8).unwrap();
    let mut peer = DurableInferenceControl::open(fixture.path(), 8).unwrap();
    first.reserve_native(request("r1"), 2).unwrap();
    fs::write(sibling_temp_path(&fixture.path(), "compact"), "interrupted checkpoint").unwrap();
    let archive = first.compact_with_archive().unwrap();
    for path in [&archive, &fixture.path()] {
        assert_eq!(fs::metadata(path).unwrap().permissions().mode() & 0o777, 0o600);
    }
    peer.dispatch_native("r1", dispatch()).unwrap();
    assert_eq!(peer.replay_stats().full_replays, 2);
    assert_eq!(first.dispatch_native("r1", dispatch()), Err(Error::InvalidTransition));
    fs::remove_file(archive).unwrap();
    assert!(first.cancel_native("r1").is_err());
}

#[test]
fn temporary_symlink_never_truncates_an_unrelated_file() {
    let fixture = Fixture::new();
    let mut control = DurableInferenceControl::open(fixture.path(), 8).unwrap();
    control.reserve_native(request("r1"), 2).unwrap();
    let victim = fixture.0.join("unrelated");
    fs::write(&victim, "must survive").unwrap();
    std::os::unix::fs::symlink(&victim, sibling_temp_path(&fixture.path(), "compact")).unwrap();
    assert!(control.compact_with_archive().is_err());
    assert_eq!(fs::read_to_string(victim).unwrap(), "must survive");
    control.dispatch_native("r1", dispatch()).unwrap();
}

#[test]
fn reserved_headroom_can_be_used_for_cancel_and_proven_pre_dispatch_stop() {
    let fixture = Fixture::new();
    let mut control = DurableInferenceControl::open(fixture.path(), 8).unwrap();
    control.reserve_native(request("reserved"), 2).unwrap();
    control.reserve_native(request("running"), 2).unwrap();
    control.dispatch_native("running", dispatch()).unwrap();
    // Exercise the admission predicate without manufacturing 48 MiB of events.
    // Stream bounds and actual replay are covered separately.
    control.journal_bytes = MAX_JOURNAL_BYTES - 2 * MAX_JOURNAL_LINE_BYTES as u64 + 1;
    assert_eq!(control.dispatch_native("reserved", dispatch()), Err(Error::CapacityExceeded));
    assert_eq!(control.reserve_native(request("new"), 2), Err(Error::CapacityExceeded));
    control.cancel_native("running").unwrap();
    control.stop_native_before_dispatch("reserved", "no turn sent".to_string()).unwrap();
    drop(control);
    let reopened = DurableInferenceControl::open(fixture.path(), 8).unwrap();
    assert_eq!(reopened.native_record("running").unwrap().state, NativeReservationState::Cancelling);
    assert_eq!(reopened.native_record("reserved").unwrap().state, NativeReservationState::Released);
}

#[test]
fn failed_single_record_preparation_preserves_all_other_records_and_bytes() {
    let fixture = Fixture::new();
    let mut control = DurableInferenceControl::open(fixture.path(), 256).unwrap();
    for index in 0..100 {
        let id = format!("r{index}");
        control.reserve_native(request(&id), 2).unwrap();
        control.stop_native_before_dispatch(&id, "done".to_string()).unwrap();
    }
    let first = control.native_record("r0").unwrap().clone();
    let last = control.native_record("r99").unwrap().clone();
    let before = fs::read(fixture.path()).unwrap();
    assert_eq!(control.dispatch_native("r50", dispatch()), Err(Error::InvalidTransition));
    assert_eq!(fs::read(fixture.path()).unwrap(), before);
    assert_eq!(control.native_record("r0"), Some(&first));
    assert_eq!(control.native_record("r99"), Some(&last));
    control.reserve_native(request("r100"), 2).unwrap();
}
