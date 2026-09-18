//! Real-file and actual child-process interruption regressions. These do not
//! substitute for power-loss testing or deployment-host performance evidence.
use super::*;
use native::NativeRequest;
use native::NativeReservationState;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;

static NEXT: AtomicU64 = AtomicU64::new(0);
struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "hepta-maintenance-{}-{}", std::process::id(), NEXT.fetch_add(1, Ordering::Relaxed),
        ));
        fs::create_dir(&path).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).unwrap();
        Self(path)
    }
    fn path(&self) -> PathBuf { self.0.join("inference.journal") }
}
impl Drop for Fixture {
    fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); }
}
fn request(id: &str) -> NativeRequest {
    NativeRequest {
        request_id: id.to_owned(), principal_id: "agent-1".to_owned(),
        worker_generation: 1, model: "fixture-model".to_owned(), payload_digest: "a".repeat(64),
    }
}
fn release(control: &mut DurableInferenceControl, id: &str) {
    control.reserve_native(request(id), 1).unwrap();
    control.stop_native_before_dispatch(id, "fixture completed".to_owned()).unwrap();
}

#[test]
fn post_compaction_peer_updates_reuse_verified_archive() {
    let fixture = Fixture::new();
    let mut first = DurableInferenceControl::open(fixture.path(), 256).unwrap();
    for i in 0..32 { release(&mut first, &format!("seed-{i}")); }
    first.compact_with_archive().unwrap();
    let mut second = DurableInferenceControl::open(fixture.path(), 256).unwrap();
    let first_bytes = first.maintenance_stats().archive_verified_bytes;
    let second_bytes = second.maintenance_stats().archive_verified_bytes;
    assert!(first_bytes > 0 && second_bytes > 0);
    for i in 0..64 {
        let id = format!("peer-{i}");
        first.reserve_native(request(&id), 1).unwrap();
        second.stop_native_before_dispatch(&id, "peer finished".to_owned()).unwrap();
    }
    assert_eq!(first.maintenance_stats().archive_verified_bytes, first_bytes);
    assert_eq!(second.maintenance_stats().archive_verified_bytes, second_bytes);
    assert!(first.maintenance_stats().archive_cache_reuses >= 64);
    assert!(second.maintenance_stats().archive_cache_reuses >= 64);
    assert!(first.replay_stats().incremental_replays > 0);
    assert!(second.replay_stats().incremental_replays > 0);
    assert!(first.maintenance_stats().lock_held_ns > 0);
    assert!(second.maintenance_stats().lock_held_ns > 0);
}

fn retry_writer<T>(mut operation: impl FnMut() -> Result<T, Error>) -> T {
    let deadline = Instant::now() + std::time::Duration::from_secs(30);
    loop {
        match operation() {
            Ok(value) => return value,
            Err(Error::WriterUnavailable) if Instant::now() < deadline => {
                std::thread::yield_now();
            }
            Err(error) => panic!("cooperating writer failed: {error:?}"),
        }
    }
}

#[test]
fn simultaneous_post_compaction_writers_preserve_every_retired_identity() {
    let fixture = Fixture::new();
    let mut seed = DurableInferenceControl::open(fixture.path(), 512).unwrap();
    release(&mut seed, "seed");
    seed.archive_released_native().unwrap();
    drop(seed);
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let mut handles = Vec::new();
    for writer in 0..2 {
        let path = fixture.path();
        let barrier = barrier.clone();
        handles.push(std::thread::spawn(move || {
            let mut control = retry_writer(|| DurableInferenceControl::open(&path, 512));
            let verified = control.maintenance_stats().archive_verified_bytes;
            barrier.wait();
            for i in 0..128 {
                let id = format!("writer-{writer}-{i}");
                retry_writer(|| control.reserve_native(request(&id), 1));
                retry_writer(|| control.stop_native_before_dispatch(&id, "finished".to_owned()));
            }
            assert_eq!(control.maintenance_stats().archive_verified_bytes, verified);
            control.maintenance_stats()
        }));
    }
    for handle in handles {
        let stats = handle.join().unwrap();
        assert!(stats.lock_acquisitions >= 257);
        assert!(stats.lock_held_ns > 0);
    }
    let mut reopened = DurableInferenceControl::open(fixture.path(), 512).unwrap();
    assert_eq!(reopened.archive_released_native().unwrap().archived, 256);
    let before = fs::read(fixture.path()).unwrap();
    for writer in 0..2 {
        for i in 0..128 {
            assert_eq!(reopened.reserve_native(request(&format!("writer-{writer}-{i}")), 1).unwrap().state, NativeReservationState::Released);
        }
    }
    assert_eq!(fs::read(fixture.path()).unwrap(), before);
}

#[test]
fn peer_append_does_not_hide_same_length_archive_corruption_or_removal() {
    for remove in [false, true] {
        let fixture = Fixture::new();
        let mut first = DurableInferenceControl::open(fixture.path(), 32).unwrap();
        release(&mut first, "seed");
        let archive = first.compact_with_archive().unwrap();
        let mut peer = DurableInferenceControl::open(fixture.path(), 32).unwrap();
        peer.reserve_native(request("peer"), 1).unwrap();
        if remove {
            fs::remove_file(archive).unwrap();
        } else {
            let mut bytes = fs::read(&archive).unwrap();
            bytes[0] ^= 1;
            fs::write(archive, bytes).unwrap();
        }
        let before = fs::read(fixture.path()).unwrap();
        assert!(first.reserve_native(request("must-not-write"), 1).is_err());
        assert_eq!(fs::read(fixture.path()).unwrap(), before);
    }
}

#[test]
fn cumulative_released_inventory_is_incremental_and_survives_reopen() {
    let fixture = Fixture::new();
    let mut control = DurableInferenceControl::open(fixture.path(), 64).unwrap();
    for generation in 0..16 {
        for i in 0..16 { release(&mut control, &format!("g{generation}-{i}")); }
        let receipt = control.archive_released_native().unwrap();
        assert_eq!(receipt.archived, 16);
        assert_eq!(receipt.remaining_native, 0);
        let scans = control.maintenance_stats().inventory_scans;
        for _ in 0..3 {
            assert_eq!(control.archive_released_native().unwrap().released_archive_bytes, receipt.released_archive_bytes);
        }
        assert_eq!(control.maintenance_stats().inventory_scans, scans);
        assert_eq!(control.maintenance_stats().inventory_entries, 0);
    }
    drop(control);
    let mut control = DurableInferenceControl::open(fixture.path(), 64).unwrap();
    control.archive_released_native().unwrap();
    assert_eq!(control.maintenance_stats().inventory_entries, 0);
    assert_eq!(control.reserve_native(request("g0-0"), 1).unwrap().state, NativeReservationState::Released);
    let bytes = fs::read(fixture.path()).unwrap();
    let mut changed = request("g0-0");
    changed.model = "semantic-conflict".to_owned();
    assert_eq!(control.reserve_native(changed, 1), Err(Error::Conflict));
    assert_eq!(fs::read(fixture.path()).unwrap(), bytes);
}

#[test]
fn invalid_inventory_rebuilds_once_without_reviving_commands() {
    let fixture = Fixture::new();
    let mut control = DurableInferenceControl::open(fixture.path(), 32).unwrap();
    for i in 0..8 { release(&mut control, &format!("r{i}")); }
    let total = control.archive_released_native().unwrap().released_archive_bytes;
    fs::write(sibling_temp_path(&fixture.path(), "released.index"), "{}").unwrap();
    assert_eq!(control.archive_released_native().unwrap().released_archive_bytes, total);
    let stats = control.maintenance_stats();
    assert_eq!(stats.inventory_scans, 1);
    assert_eq!(stats.inventory_entries, 8);
    control.archive_released_native().unwrap();
    assert_eq!(control.maintenance_stats().inventory_entries, stats.inventory_entries);
    assert_eq!(control.reserve_native(request("r0"), 1).unwrap().state, NativeReservationState::Released);
}

#[test]
fn released_publisher_reclaims_partial_temporary_but_never_overwrites_conflict() {
    let fixture = Fixture::new();
    let mut control = DurableInferenceControl::open(fixture.path(), 16).unwrap();
    release(&mut control, "r1");
    ensure_released_archive_dir(&fixture.path()).unwrap();
    let target = released_record_path(&fixture.path(), "r1").unwrap();
    let temporary = sibling_temp_path(&target, "tmp");
    fs::write(&temporary, b"partial").unwrap();
    control.archive_released_native().unwrap();
    assert!(!temporary.exists());
    let bytes = fs::read(&target).unwrap();
    assert_eq!(maintenance::publish_released(&target, b"conflicting"), Err(Error::Conflict));
    assert_eq!(fs::read(target).unwrap(), bytes);
}

#[test]
fn released_temporary_symlink_does_not_touch_unrelated_data() {
    let fixture = Fixture::new();
    let mut control = DurableInferenceControl::open(fixture.path(), 16).unwrap();
    release(&mut control, "r1");
    ensure_released_archive_dir(&fixture.path()).unwrap();
    let target = released_record_path(&fixture.path(), "r1").unwrap();
    let unrelated = fixture.0.join("unrelated");
    fs::write(&unrelated, "must survive").unwrap();
    std::os::unix::fs::symlink(&unrelated, sibling_temp_path(&target, "tmp")).unwrap();
    assert!(control.archive_released_native().is_err());
    assert_eq!(fs::read_to_string(unrelated).unwrap(), "must survive");
    assert!(!target.exists());
}

#[test]
#[ignore = "invoked only as an isolated subprocess by the crash-restart parent"]
fn released_archive_process_exit_child() {
    let directory = std::env::var("HEPTA_TEST_RELEASED_DIRECTORY").expect("child directory");
    let mut control = DurableInferenceControl::open(Path::new(&directory).join("inference.journal"), 16).unwrap();
    for i in 0..8 { release(&mut control, &format!("child-{i}")); }
    control.archive_released_native().unwrap();
    panic!("requested interruption point was not reached");
}

#[test]
fn released_archive_process_exit_at_each_publication_boundary_is_retryable() {
    let child_name = concat!(module_path!(), "::released_archive_process_exit_child");
    let child_name = child_name.split_once("::").unwrap().1;
    for phase in ["inventory-invalidated", "temp-created", "temp-written", "temp-synced", "linked", "directory-synced", "inventory-published", "hot-compacted"] {
        let fixture = Fixture::new();
        let status = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", child_name, "--ignored", "--nocapture"])
            .env("HEPTA_TEST_RELEASED_DIRECTORY", &fixture.0)
            .env("HEPTA_TEST_RELEASED_CRASH_PHASE", phase)
            .status().unwrap();
        assert_eq!(status.code(), Some(86), "phase {phase}");
        let mut reopened = DurableInferenceControl::open(fixture.path(), 16).unwrap();
        let receipt = reopened.archive_released_native().unwrap();
        assert_eq!(receipt.archived, if phase == "hot-compacted" { 0 } else { 8 }, "{phase}");
        assert_eq!(receipt.remaining_native, 0);
        let actual: u64 = fs::read_dir(released_archive_dir(&fixture.path())).unwrap()
            .map(|e| e.unwrap()).filter(|e| e.file_name().to_string_lossy().ends_with(".json"))
            .map(|e| e.metadata().unwrap().len()).sum();
        assert_eq!(receipt.released_archive_bytes, actual, "{phase}");
        let before = fs::read(fixture.path()).unwrap();
        for i in 0..8 {
            assert_eq!(reopened.reserve_native(request(&format!("child-{i}")), 1).unwrap().state, NativeReservationState::Released);
        }
        assert_eq!(fs::read(fixture.path()).unwrap(), before, "{phase}");
    }
}

#[test]
fn legacy_request_cannot_reuse_an_archived_native_identity() {
    let fixture = Fixture::new();
    let mut control = DurableInferenceControl::open(fixture.path(), 8).unwrap();
    release(&mut control, "retired");
    control.archive_released_native().unwrap();
    let request = InferenceRequest {
        request_id: "retired".to_owned(), principal_id: "agent-1".to_owned(),
        model_digest: "a".repeat(64), payload_digest: "b".repeat(64),
        maximum_tokens: 1, deadline_ms: 100, semantic_digest: "c".repeat(64),
    };
    let before = fs::read(fixture.path()).unwrap();
    assert_eq!(control.submit(1, request), Err(Error::Conflict));
    assert_eq!(fs::read(fixture.path()).unwrap(), before);
}

fn percentile(values: &mut [u64], percent: usize) -> u64 {
    values.sort_unstable();
    values[(values.len() * percent).div_ceil(100).saturating_sub(1).min(values.len() - 1)]
}
fn process_io() -> BTreeMap<String, u64> {
    fs::read_to_string("/proc/self/io").unwrap_or_default().lines().filter_map(|line| {
        let (name, value) = line.split_once(':')?;
        Some((name.to_owned(), value.trim().parse().ok()?))
    }).collect()
}
fn io_delta(before: &BTreeMap<String, u64>, after: &BTreeMap<String, u64>) -> BTreeMap<String, u64> {
    after.iter().map(|(key, value)| (key.clone(), value.saturating_sub(*before.get(key).unwrap_or(&0)))).collect()
}
fn disk_bytes(path: &Path) -> u64 {
    fs::read_dir(path).unwrap().map(|e| {
        let e = e.unwrap();
        if e.file_type().unwrap().is_dir() { disk_bytes(&e.path()) } else { e.metadata().unwrap().len() }
    }).sum()
}

#[test]
#[ignore = "explicit process-I/O curve; run alone with --test-threads=1"]
fn post_compaction_multi_generation_curve() {
    for history in [64, 1024, 32_768] {
        let fixture = Fixture::new();
        let mut first = DurableInferenceControl::open(fixture.path(), 256).unwrap();
        for generation in 0..history / 32 {
            for i in 0..32 { release(&mut first, &format!("h{generation}-{i}")); }
            first.archive_released_native().unwrap();
        }
        let mut second = DurableInferenceControl::open(fixture.path(), 256).unwrap();
        let verified_before = first.maintenance_stats().archive_verified_bytes + second.maintenance_stats().archive_verified_bytes;
        let mut update_us = Vec::new();
        let mut lock_ns = Vec::new();
        let before_io = process_io();
        let before_journal_bytes = fs::metadata(fixture.path()).unwrap().len();
        for i in 0..128 {
            let id = format!("update-{i}");
            let started = Instant::now();
            let before = first.maintenance_stats().lock_held_ns;
            first.reserve_native(request(&id), 1).unwrap();
            lock_ns.push(first.maintenance_stats().lock_held_ns - before);
            update_us.push(started.elapsed().as_micros() as u64);
            let started = Instant::now();
            let before = second.maintenance_stats().lock_held_ns;
            second.stop_native_before_dispatch(&id, "curve complete".to_owned()).unwrap();
            lock_ns.push(second.maintenance_stats().lock_held_ns - before);
            update_us.push(started.elapsed().as_micros() as u64);
        }
        let update_io = process_io();
        let update_journal_bytes = fs::metadata(fixture.path()).unwrap().len() - before_journal_bytes;
        let verified_after = first.maintenance_stats().archive_verified_bytes + second.maintenance_stats().archive_verified_bytes;
        assert_eq!(verified_after, verified_before, "peer updates reread an unchanged archive");
        let entries_before = first.maintenance_stats().inventory_entries;
        let maintenance_lock_before = first.maintenance_stats().lock_held_ns;
        let started = Instant::now();
        first.archive_released_native().unwrap();
        let maintenance_us = started.elapsed().as_micros();
        let maintenance_io = process_io();
        let maintenance_lock_ns = first.maintenance_stats().lock_held_ns - maintenance_lock_before;
        assert_eq!(first.maintenance_stats().inventory_entries, entries_before, "ordinary maintenance scanned cumulative history");
        drop(first);
        drop(second);
        let started = Instant::now();
        let mut reopened = DurableInferenceControl::open(fixture.path(), 256).unwrap();
        let recovery_us = started.elapsed().as_micros();
        assert_eq!(reopened.reserve_native(request("h0-0"), 1).unwrap().state, NativeReservationState::Released);
        let recovery_io = process_io();
        let resident = fs::read_to_string("/proc/self/status").unwrap_or_default().lines()
            .find(|line| line.starts_with("VmRSS:")).unwrap_or("unavailable").to_owned();
        println!("{}", serde_json::json!({
            "schema": "hepta.inference-maintenance-curve.v1", "prior_retired_commands": history,
            "operations": 256, "update_p95_us": percentile(&mut update_us, 95),
            "update_p99_us": percentile(&mut update_us, 99), "writer_lock_p95_ns": percentile(&mut lock_ns, 95),
            "writer_lock_p99_ns": percentile(&mut lock_ns, 99), "maintenance_us": maintenance_us, "maintenance_writer_lock_ns": maintenance_lock_ns,
            "recovery_us": recovery_us, "archive_verification_bytes_during_updates": verified_after - verified_before,
            "inventory_entries_during_maintenance": 0, "update_process_io": io_delta(&before_io, &update_io),
            "maintenance_process_io": io_delta(&update_io, &maintenance_io), "recovery_process_io": io_delta(&maintenance_io, &recovery_io),
            "update_journal_bytes": update_journal_bytes,
            "update_write_amplification_syscall": io_delta(&before_io, &update_io).get("wchar").map(|value| *value as f64 / update_journal_bytes.max(1) as f64),
            "resident_memory": resident,
            "total_local_disk_bytes": disk_bytes(&fixture.0), "scope": "cooperative-local-files-process-not-target-host"
        }));
    }
}
