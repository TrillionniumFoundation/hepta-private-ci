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
    assert_eq!(
        second.dispatch_native("r1", dispatch()),
        Err(Error::InvalidTransition)
    );
    assert_eq!(fs::read(fixture.path()).unwrap(), committed);
    drop(first);
    drop(second);
    let mut reopened = DurableInferenceControl::open(fixture.path(), 8).unwrap();
    assert_eq!(
        reopened.dispatch_native("r1", dispatch()),
        Err(Error::InvalidTransition)
    );
    assert_eq!(
        reopened.native_record("r1").unwrap().state,
        NativeReservationState::Dispatching
    );
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
    assert_eq!(
        reopened.native_record("slow").unwrap().state,
        NativeReservationState::Cancelling
    );
    assert_eq!(
        reopened.native_record("fast").unwrap().state,
        NativeReservationState::Dispatching
    );
}

#[test]
fn unchanged_owner_reuses_cut_but_peer_writes_force_refresh() {
    let fixture = Fixture::new();
    let mut first = DurableInferenceControl::open(fixture.path(), 512).unwrap();
    for index in 0..128 {
        let id = format!("r{index}");
        first.reserve_native(request(&id), 2).unwrap();
        first
            .stop_native_before_dispatch(&id, "fixture stop".to_string())
            .unwrap();
    }
    assert_eq!(first.replay_stats().full_replays, 1);
    assert_eq!(first.replay_stats().replayed_bytes, 0);
    assert_eq!(first.replay_stats().unchanged_reuses, 256);
    let mut peer = DurableInferenceControl::open(fixture.path(), 512).unwrap();
    peer.reserve_native(request("peer"), 2).unwrap();
    first.reserve_native(request("local"), 2).unwrap();
    assert_eq!(first.replay_stats().full_replays, 1);
    assert_eq!(first.replay_stats().incremental_replays, 1);
    assert!(first.replay_stats().replayed_bytes > 0);
    assert!(first.native_record("peer").is_some());
    assert_eq!(
        first.native_record("r0").unwrap().state,
        NativeReservationState::Released
    );
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
    fs::write(
        sibling_temp_path(&fixture.path(), "compact"),
        "interrupted checkpoint",
    )
    .unwrap();
    let archive = first.compact_with_archive().unwrap();
    for path in [&archive, &fixture.path()] {
        assert_eq!(
            fs::metadata(path).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
    peer.dispatch_native("r1", dispatch()).unwrap();
    assert_eq!(peer.replay_stats().full_replays, 2);
    assert_eq!(
        first.dispatch_native("r1", dispatch()),
        Err(Error::InvalidTransition)
    );
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
fn released_runs_leave_hot_state_but_keep_permanent_command_identity() {
    let fixture = Fixture::new();
    let mut control = DurableInferenceControl::open(fixture.path(), 4).unwrap();
    for index in 0..4 {
        let id = format!("released-{index}");
        control.reserve_native(request(&id), 1).unwrap();
        control
            .stop_native_before_dispatch(&id, "finished before dispatch".to_string())
            .unwrap();
    }
    let hot_before = fs::metadata(fixture.path()).unwrap().len();
    let receipt = control.archive_released_native().unwrap();
    assert_eq!(receipt.archived, 4);
    assert_eq!(receipt.remaining_native, 0);
    assert!(receipt.released_archive_bytes > 0);
    assert!(receipt.journal_bytes < hot_before);
    assert!(control.native_record("released-0").is_none());

    let active_before_duplicate = fs::metadata(fixture.path()).unwrap().len();
    let duplicate = control.reserve_native(request("released-0"), 1).unwrap();
    assert_eq!(duplicate.state, NativeReservationState::Released);
    assert_eq!(
        fs::metadata(fixture.path()).unwrap().len(),
        active_before_duplicate,
        "archived duplicate identity must not append a new hot event"
    );

    let mut conflict = request("released-0");
    conflict.model = "different-model".to_string();
    assert_eq!(
        control.reserve_native(conflict, 1),
        Err(Error::Conflict),
        "archived command identity must reject semantic reuse"
    );

    control.reserve_native(request("new-hot"), 1).unwrap();
    assert!(control.native_record("new-hot").is_some());

    let archive_dir = released_archive_dir(&fixture.path());
    assert_eq!(
        fs::metadata(&archive_dir).unwrap().permissions().mode() & 0o777,
        0o700
    );
    let archived_file = fs::read_dir(&archive_dir)
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    assert_eq!(
        fs::metadata(archived_file).unwrap().permissions().mode() & 0o777,
        0o600
    );

    drop(control);
    let mut reopened = DurableInferenceControl::open(fixture.path(), 4).unwrap();
    assert!(reopened.native_record("released-0").is_none());
    assert_eq!(
        reopened
            .reserve_native(request("released-0"), 1)
            .unwrap()
            .state,
        NativeReservationState::Released
    );
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
    assert_eq!(
        control.dispatch_native("reserved", dispatch()),
        Err(Error::CapacityExceeded)
    );
    assert_eq!(
        control.reserve_native(request("new"), 2),
        Err(Error::CapacityExceeded)
    );
    control.cancel_native("running").unwrap();
    control
        .stop_native_before_dispatch("reserved", "no turn sent".to_string())
        .unwrap();
    drop(control);
    let reopened = DurableInferenceControl::open(fixture.path(), 8).unwrap();
    assert_eq!(
        reopened.native_record("running").unwrap().state,
        NativeReservationState::Cancelling
    );
    assert_eq!(
        reopened.native_record("reserved").unwrap().state,
        NativeReservationState::Released
    );
}

#[test]
fn failed_single_record_preparation_preserves_all_other_records_and_bytes() {
    let fixture = Fixture::new();
    let mut control = DurableInferenceControl::open(fixture.path(), 256).unwrap();
    for index in 0..100 {
        let id = format!("r{index}");
        control.reserve_native(request(&id), 2).unwrap();
        control
            .stop_native_before_dispatch(&id, "done".to_string())
            .unwrap();
    }
    let first = control.native_record("r0").unwrap().clone();
    let last = control.native_record("r99").unwrap().clone();
    let before = fs::read(fixture.path()).unwrap();
    assert_eq!(
        control.dispatch_native("r50", dispatch()),
        Err(Error::InvalidTransition)
    );
    assert_eq!(fs::read(fixture.path()).unwrap(), before);
    assert_eq!(control.native_record("r0"), Some(&first));
    assert_eq!(control.native_record("r99"), Some(&last));
    control.reserve_native(request("r100"), 2).unwrap();
}

#[test]
#[ignore = "explicit retained multi-writer scalability measurement"]
fn alternating_writers_replay_only_peer_deltas() {
    use std::time::Instant;

    for scale in [64_usize, 256, 1_024] {
        let fixture = Fixture::new();
        let mut first = DurableInferenceControl::open(fixture.path(), scale + 8).unwrap();
        let mut second = DurableInferenceControl::open(fixture.path(), scale + 8).unwrap();
        let mut tail_update_micros = Vec::new();

        for index in 0..scale {
            let id = format!("peer-curve-{index}");
            let started = Instant::now();
            let owner = if index % 2 == 0 {
                &mut first
            } else {
                &mut second
            };
            owner.reserve_native(request(&id), 1).unwrap();
            owner
                .stop_native_before_dispatch(&id, "peer curve terminal".to_string())
                .unwrap();
            if index + 64 >= scale {
                tail_update_micros.push(started.elapsed().as_micros() as u64);
            }
        }

        tail_update_micros.sort_unstable();
        let p95_index = ((tail_update_micros.len() * 95).div_ceil(100)).saturating_sub(1);
        let p95_micros = tail_update_micros[p95_index];
        let first_stats = first.replay_stats();
        let second_stats = second.replay_stats();
        assert_eq!(first_stats.full_replays, 1);
        assert_eq!(second_stats.full_replays, 1);
        assert!(
            first_stats.incremental_replays + second_stats.incremental_replays
                >= (scale.saturating_sub(1)) as u64
        );
        println!(
            "HEPTA_INFERENCE_MULTIWRITER scale={scale} update_p95_us={p95_micros} \
             first_incremental={} second_incremental={} replayed_bytes={}",
            first_stats.incremental_replays,
            second_stats.incremental_replays,
            first_stats.replayed_bytes + second_stats.replayed_bytes,
        );
    }
}

fn peak_rss_kib() -> Option<u64> {
    let status = fs::read_to_string("/proc/self/status").ok()?;
    status.lines().find_map(|line| {
        let value = line.strip_prefix("VmHWM:")?;
        value.split_whitespace().next()?.parse().ok()
    })
}

#[test]
#[ignore = "explicit retained scalability measurement"]
fn history_growth_emits_update_recovery_memory_and_disk_curve() {
    use std::time::Instant;

    for scale in [64_usize, 256, 1_024] {
        let fixture = Fixture::new();
        let mut control = DurableInferenceControl::open(fixture.path(), scale + 8).unwrap();
        let mut tail_update_micros = Vec::new();

        for index in 0..scale {
            let id = format!("curve-{index}");
            let started = Instant::now();
            control.reserve_native(request(&id), 1).unwrap();
            control
                .stop_native_before_dispatch(&id, "curve terminal".to_string())
                .unwrap();
            if index + 64 >= scale {
                tail_update_micros.push(started.elapsed().as_micros() as u64);
            }
        }

        tail_update_micros.sort_unstable();
        let p95_index = ((tail_update_micros.len() * 95).div_ceil(100)).saturating_sub(1);
        let update_p95_micros = tail_update_micros[p95_index];
        let steady_stats = control.replay_stats();
        assert_eq!(steady_stats.full_replays, 1);
        assert_eq!(steady_stats.incremental_replays, 0);
        assert!(steady_stats.unchanged_reuses >= (scale * 2) as u64);
        let journal_before_bytes = fs::metadata(fixture.path()).unwrap().len();
        drop(control);

        let recovery_started = Instant::now();
        let mut reopened = DurableInferenceControl::open(fixture.path(), scale + 8).unwrap();
        let recovery_micros = recovery_started.elapsed().as_micros() as u64;
        assert_eq!(
            reopened.native_record("curve-0").unwrap().state,
            NativeReservationState::Released
        );
        assert_eq!(
            reopened
                .native_record(&format!("curve-{}", scale - 1))
                .unwrap()
                .state,
            NativeReservationState::Released
        );

        let archive_receipt = reopened.archive_released_native().unwrap();
        assert_eq!(archive_receipt.archived, scale);
        assert_eq!(archive_receipt.remaining_native, 0);
        let active_after_archive_bytes = fs::metadata(fixture.path()).unwrap().len();
        assert!(active_after_archive_bytes < journal_before_bytes);
        let before_duplicate = active_after_archive_bytes;
        let duplicate = reopened.reserve_native(request("curve-0"), 1).unwrap();
        assert_eq!(duplicate.state, NativeReservationState::Released);
        assert_eq!(
            fs::metadata(fixture.path()).unwrap().len(),
            before_duplicate
        );
        drop(reopened);

        let compacted_recovery_started = Instant::now();
        let mut compacted = DurableInferenceControl::open(fixture.path(), scale + 8).unwrap();
        let compacted_recovery_micros = compacted_recovery_started.elapsed().as_micros() as u64;
        assert!(compacted.native_record("curve-0").is_none());
        assert_eq!(
            compacted.reserve_native(request("curve-0"), 1).unwrap().state,
            NativeReservationState::Released
        );

        let audit_archive_bytes = fs::read_dir(&fixture.0)
            .unwrap()
            .filter_map(Result::ok)
            .filter_map(|entry| {
                let name = entry.file_name();
                let name = name.to_string_lossy();
                (name.starts_with("inference.journal.archive-"))
                    .then(|| entry.metadata().ok()?.len())
            })
            .sum::<u64>();
        let total_after_archive_bytes = active_after_archive_bytes
            + archive_receipt.released_archive_bytes
            + audit_archive_bytes;
        let journal_bytes_per_run = journal_before_bytes.div_ceil(scale as u64);

        println!(
            "HEPTA_INFERENCE_SCALE scale={scale} update_p95_us={update_p95_micros} \
             recovery_us={recovery_micros} compacted_recovery_us={compacted_recovery_micros} \
             peak_rss_kib={} journal_before_bytes={journal_before_bytes} \
             journal_bytes_per_run={journal_bytes_per_run} \
             active_after_archive_bytes={active_after_archive_bytes} \
             released_archive_bytes={} audit_archive_bytes={audit_archive_bytes} \
             total_after_archive_bytes={total_after_archive_bytes}",
            peak_rss_kib().unwrap_or(0),
            archive_receipt.released_archive_bytes,
        );
    }
}
