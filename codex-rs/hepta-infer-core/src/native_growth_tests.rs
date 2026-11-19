//! Real file-backed owner curves. This measurement exercises append/replay growth
//! without requesting compaction; separate crash-cut tests qualify current-state
//! checkpoint compaction. Neither suite proves multi-writer replay or archival.
use super::*;
use std::time::Instant;

fn rss_kib() -> Option<u64> {
    std::fs::read_to_string("/proc/self/status")
        .ok()?
        .lines()
        .find_map(|line| {
            line.strip_prefix("VmRSS:")?
                .split_whitespace()
                .next()?
                .parse()
                .ok()
        })
}

fn percentile(samples: &mut [u128], percent: usize) -> u128 {
    samples.sort_unstable();
    samples[(samples.len() - 1) * percent / 100]
}

#[test]
#[ignore = "explicit real file-backed history growth measurement"]
fn history_growth_emits_update_recovery_memory_and_disk_curve() {
    let path = path("native-history-growth");
    let mut control = DurableInferenceControl::open(&path, 4096).unwrap();
    let mut count = 0;
    for records in [64_usize, 256, 1024, 4096] {
        let mut samples = Vec::with_capacity((records - count) * 4);
        for index in count..records {
            let id = format!("growth.{index}");
            let began = Instant::now();
            control.reserve_native(request(&id), 1).unwrap();
            samples.push(began.elapsed().as_nanos());
            let began = Instant::now();
            control.dispatch_native(&id, dispatch()).unwrap();
            samples.push(began.elapsed().as_nanos());
            let began = Instant::now();
            control.native_started(&id, "turn-1".to_string()).unwrap();
            samples.push(began.elapsed().as_nanos());
            let mut observed = output(NativeRunStatus::Completed, Some(1));
            observed.output = format!("{index}:{}", "x".repeat(1024));
            let began = Instant::now();
            control.settle_native(&id, observed).unwrap();
            samples.push(began.elapsed().as_nanos());
        }
        assert_eq!(control.native.active_reservations, 0);
        let first = control.native_record("growth.0").unwrap().clone();
        let mut lookup = Vec::with_capacity(100);
        for _ in 0..100 {
            let began = Instant::now();
            assert_eq!(control.native_record("growth.0"), Some(&first));
            lookup.push(began.elapsed().as_nanos());
        }
        let bytes = std::fs::metadata(&path).unwrap().len();
        let before_rss = rss_kib();
        drop(control);
        let began = Instant::now();
        control = DurableInferenceControl::open(&path, 4096).unwrap();
        let reopen_ns = began.elapsed().as_nanos();
        assert_eq!(control.native.records.len(), records);
        assert_eq!(control.native.active_reservations, 0);
        assert_eq!(
            control.reserve_native(request("growth.0"), 1).unwrap(),
            first
        );
        assert_eq!(std::fs::metadata(&path).unwrap().len(), bytes);
        println!(
            "HEPTA_INFERENCE_GROWTH_V1 {}",
            serde_json::json!({
                "profile": "exclusive_writer_full_replay_v1",
                "records": records, "samples": samples.len(),
                "append_p50_ns": percentile(&mut samples, 50),
                "append_p95_ns": percentile(&mut samples, 95),
                "append_p99_ns": percentile(&mut samples, 99),
                "lookup_p99_ns": percentile(&mut lookup, 99),
                "reopen_ns": reopen_ns, "journal_bytes": bytes,
                "rss_before_reopen_kib": before_rss, "rss_after_reopen_kib": rss_kib(),
                "compaction_proved": false, "multiwriter_delta_replay_proved": false,
            })
        );
        count = records;
    }
    let bytes = std::fs::metadata(&path).unwrap().len();
    assert_eq!(
        control.reserve_native(request("over-capacity"), 1),
        Err(Error::CapacityExceeded)
    );
    assert_eq!(std::fs::metadata(&path).unwrap().len(), bytes);
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn exclusive_owner_handoff_preserves_exact_history_and_pending_admission() {
    let path = path("owner-handoff-history");
    let mut control = DurableInferenceControl::open(&path, 64).unwrap();
    for generation in 0..16 {
        let id = format!("handoff.{generation}");
        control.reserve_native(request(&id), 1).unwrap();
        assert!(matches!(
            DurableInferenceControl::open(&path, 64),
            Err(Error::WriterUnavailable)
        ));
        let pending = control.native.records.clone();
        drop(control);
        control = DurableInferenceControl::open(&path, 64).unwrap();
        assert_eq!(control.native.records, pending);
        assert_eq!(control.native.active_reservations, 1);
        assert_eq!(
            control.reserve_native(request("cannot-steal-pending"), 1),
            Err(Error::CapacityExceeded)
        );
        control
            .stop_native_before_dispatch(&id, "handoff complete".to_string())
            .unwrap();
        let before_bytes = std::fs::metadata(&path).unwrap().len();
        let original = control.native_record("handoff.0").unwrap().clone();
        assert_eq!(
            control.reserve_native(request("handoff.0"), 1).unwrap(),
            original
        );
        assert_eq!(std::fs::metadata(&path).unwrap().len(), before_bytes);
        assert_eq!(control.native.active_reservations, 0);
    }
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
#[ignore = "entry point called only by the parent crash test"]
fn native_commit_crash_child() {
    let Some(path) = std::env::var_os("HEPTA_INFERENCE_CRASH_JOURNAL") else {
        return;
    };
    let mut control = DurableInferenceControl::open(PathBuf::from(path), 8).unwrap();
    control.reserve_native(request("lost-ack"), 1).unwrap();
    // The file has been fsynced; terminate without destructors or returning the
    // receipt to the parent. No provider is contacted by this owner-state test.
    std::process::exit(73);
}

#[test]
fn process_loss_after_commit_reopens_without_duplicate_admission() {
    let path = path("process-loss");
    let status = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "durable_control::native::tests::growth::native_commit_crash_child",
            "--ignored",
            "--nocapture",
        ])
        .env("HEPTA_INFERENCE_CRASH_JOURNAL", &path)
        .status()
        .unwrap();
    assert_eq!(status.code(), Some(73));
    let before_bytes = std::fs::metadata(&path).unwrap().len();
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let pending = control.native_record("lost-ack").unwrap().clone();
    assert_eq!(
        control.reserve_native(request("lost-ack"), 1).unwrap(),
        pending
    );
    assert_eq!(std::fs::metadata(&path).unwrap().len(), before_bytes);
    assert_eq!(control.native.active_reservations, 1);
    assert_eq!(
        control.reserve_native(request("another"), 1),
        Err(Error::CapacityExceeded)
    );
    control
        .stop_native_before_dispatch("lost-ack", "reconciled without effect".to_string())
        .unwrap();
    control.reserve_native(request("another"), 1).unwrap();
    assert_eq!(control.native.active_reservations, 1);
    drop(control);
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native.active_reservations, 1);
    assert_eq!(
        control.native_record("lost-ack").unwrap().state,
        NativeReservationState::Released
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
#[ignore = "entry point called only by the parent compaction crash test"]
fn native_compaction_crash_child() {
    let Some(path) = std::env::var_os("HEPTA_INFERENCE_COMPACTION_JOURNAL") else {
        return;
    };
    let stage =
        std::env::var("HEPTA_INFERENCE_COMPACTION_CRASH_STAGE").expect("compaction crash stage");
    assert!(matches!(stage.as_str(), "before_rename" | "after_rename"));
    let mut control = DurableInferenceControl::open(PathBuf::from(path), 8).unwrap();
    let _ = control.compact_journal().unwrap();
    panic!("compaction crash hook did not terminate the child");
}

#[test]
fn compaction_crash_cuts_reopen_one_exact_state_without_duplicate_release() {
    let path = path("compaction-crash-cuts");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "r1");
    let mut observed = output(NativeRunStatus::Completed, Some(1));
    observed.output = "x".repeat(64 * 1024);
    for tokens in 1..=4 {
        observed.observed_output_tokens = Some(tokens);
        control.settle_native("r1", observed.clone()).unwrap();
    }
    let expected = control.native_record("r1").unwrap().clone();
    drop(control);

    for (stage, exit_code) in [("before_rename", 74), ("after_rename", 75)] {
        let status = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "durable_control::native::tests::growth::native_compaction_crash_child",
                "--ignored",
                "--nocapture",
            ])
            .env("HEPTA_INFERENCE_COMPACTION_JOURNAL", &path)
            .env("HEPTA_INFERENCE_COMPACTION_CRASH_STAGE", stage)
            .status()
            .unwrap();
        assert_eq!(status.code(), Some(exit_code), "stage={stage}");

        let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
        assert_eq!(reopened.native_record("r1"), Some(&expected));
        assert_eq!(reopened.native.active_reservations, 0);
        let before_duplicate = reopened.journal_capacity_status().journal_bytes;
        assert_eq!(
            reopened.settle_native("r1", observed.clone()).unwrap(),
            expected
        );
        assert_eq!(
            reopened.journal_capacity_status().journal_bytes,
            before_duplicate
        );
        drop(reopened);
    }
    assert!(!crate::durable_control::compaction_path(&path).exists());
    std::fs::remove_file(path).unwrap();
}
