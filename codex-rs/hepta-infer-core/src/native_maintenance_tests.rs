//! Storage regression matrix; child entry points are invoked by parent tests.
use super::*;
use std::io::Write;

#[test]
fn old_overcommitted_journal_can_release_without_admitting_new_work() {
    let path = path("old-liability-migration");
    drop(DurableInferenceControl::open(&path, 32).unwrap());
    let mut file = std::fs::OpenOptions::new()
        .append(true)
        .open(&path)
        .unwrap();
    // Valid pre-maintenance event history: the former fixed free-space test
    // accepted all these tiny reservations without reserving terminal bytes.
    for index in 0..12 {
        let event = Event::Reserve {
            request: request(&format!("old-{index}")),
            maximum_in_flight: 16,
        };
        writeln!(
            file,
            "{JOURNAL_PREFIX}{}",
            serde_json::to_string(&event).unwrap()
        )
        .unwrap();
    }
    file.sync_all().unwrap();
    drop(file);
    let mut control = DurableInferenceControl::open(&path, 32).unwrap();
    assert!(
        control.journal_capacity_status().reserved_headroom_bytes
            > super::super::super::MAX_JOURNAL_BYTES
    );
    assert_eq!(
        control.reserve_native(request("new"), 16),
        Err(Error::CapacityExceeded)
    );
    for index in 0..12 {
        let id = format!("old-{index}");
        let released = control
            .stop_native_before_dispatch(&id, "migration drain".into())
            .unwrap();
        assert_eq!(released.state, NativeReservationState::Released);
    }
    assert_eq!(control.native.active_reservations, 0);
    control.reserve_native(request("new"), 16).unwrap();
    drop(control);
    let control = DurableInferenceControl::open(&path, 32).unwrap();
    assert_eq!(control.native.active_reservations, 1);
}

#[test]
fn compaction_failure_retains_old_bytes_and_all_responsibilities() {
    let path = path("failed-checkpoint-publication");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "live");
    let before = control.native_record("live").unwrap().clone();
    let bytes = std::fs::read(&path).unwrap();
    let temp = crate::durable_control::compaction_path(&path);
    std::fs::create_dir(&temp).unwrap();
    assert!(control.compact_journal().is_err());
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    assert_eq!(control.native_record("live"), Some(&before));
    assert!(!control.poisoned);
    std::fs::remove_dir(&temp).unwrap();
    control.compact_journal().unwrap();
    let mut terminal = output(NativeRunStatus::Completed, Some(1));
    terminal.output = "finished".into();
    let final_record = control.settle_native("live", terminal.clone()).unwrap();
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(
        control.settle_native("live", terminal).unwrap(),
        final_record
    );
    assert_eq!(control.native.active_reservations, 0);
}

#[test]
fn checkpoint_revision_does_not_expand_into_historical_observation_copies() {
    let path = path("bounded-checkpoint-revision");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "live");
    control
        .settle_native("live", output(NativeRunStatus::Completed, Some(1)))
        .unwrap();
    // Exercise the snapshot validator at a very large (but non-overflowing)
    // history revision. Work must depend on record size, never revision count.
    control.native.records.get_mut("live").unwrap().revision = 1_000_000_000;
    let expected = control.native_record("live").unwrap().clone();
    control.compact_journal().unwrap();
    drop(control);
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native_record("live"), Some(&expected));
}

#[test]
fn oversized_total_journal_is_rejected_without_rewriting_source() {
    let path = path("total-byte-replay-budget");
    let mut file = std::fs::File::create(&path).unwrap();
    // Empty historical lines are accepted by replay, but still consume bytes.
    let chunk = vec![b'\n'; 1024 * 1024];
    for _ in 0..64 {
        file.write_all(&chunk).unwrap();
    }
    file.write_all(b"\n").unwrap();
    file.sync_all().unwrap();
    drop(file);
    let before = std::fs::metadata(&path).unwrap().len();
    assert!(matches!(
        DurableInferenceControl::open(&path, 8),
        Err(Error::CapacityExceeded)
    ));
    assert_eq!(std::fs::metadata(&path).unwrap().len(), before);
    std::fs::remove_file(path).unwrap();
}

#[test]
#[ignore = "subprocess entry; executed by writer_exclusion_survives_compaction_and_process_handoff"]
fn writer_process_child() {
    let path = std::env::var_os("HEPTA_INFERENCE_WRITER_TEST_PATH").unwrap();
    match DurableInferenceControl::open(PathBuf::from(path), 8) {
        Ok(control) => {
            assert!(control.native_record("live").is_some());
            std::process::exit(81);
        }
        Err(Error::WriterUnavailable) => std::process::exit(82),
        Err(error) => panic!("unexpected open result: {error}"),
    }
}

#[test]
fn writer_exclusion_survives_compaction_and_process_handoff() {
    let path = path("cross-process-writer");
    let run_child = || {
        std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "durable_control::native::tests::maintenance::writer_process_child",
                "--ignored",
                "--nocapture",
            ])
            .env("HEPTA_INFERENCE_WRITER_TEST_PATH", &path)
            .status()
            .unwrap()
            .code()
    };
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("live"), 1).unwrap();
    assert_eq!(run_child(), Some(82));
    control.compact_journal().unwrap();
    assert_eq!(run_child(), Some(82));
    let expected = control.native_record("live").unwrap().clone();
    drop(control);
    assert_eq!(run_child(), Some(81));
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native_record("live"), Some(&expected));
}

#[test]
fn reserved_metadata_and_maximum_terminal_can_consume_their_own_headroom() {
    let path = path("liability-at-byte-boundary");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("live"), 1).unwrap();
    fill_admissible_bytes(&mut control);
    let full = control.journal_capacity_status();
    assert_eq!(full.admissible_bytes, 0);
    control.dispatch_native("live", dispatch()).unwrap();
    control.native_started("live", "turn-1".into()).unwrap();
    control.cancel_native("live").unwrap();
    let mut terminal = output(NativeRunStatus::Interrupted, None);
    terminal.output = "\0".repeat(1024 * 1024);
    let settled = control.settle_native("live", terminal).unwrap();
    assert_eq!(settled.state, NativeReservationState::Released);
    let final_capacity = control.journal_capacity_status();
    assert_eq!(final_capacity.reserved_headroom_bytes, USAGE_HEADROOM_BYTES);
    // No checkpoint reclamation was needed: already-owned bytes were consumed.
    assert!(final_capacity.journal_bytes > full.journal_bytes);
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn checkpoint_truncation_at_a_complete_record_never_publishes_a_prefix() {
    let path = path("checkpoint-prefix-truncation");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("first"), 2).unwrap();
    control.reserve_native(request("second"), 2).unwrap();
    control.compact_journal().unwrap();
    let full = std::fs::read_to_string(&path).unwrap();
    drop(control);
    let lines: Vec<_> = full.split_inclusive('\n').collect();
    assert_eq!(lines.len(), 4);
    for prefix in 1..lines.len() {
        let bytes = lines[..prefix].concat();
        std::fs::write(&path, &bytes).unwrap();
        assert!(matches!(
            DurableInferenceControl::open(&path, 8),
            Err(Error::CorruptJournal(_))
        ));
        assert_eq!(std::fs::read_to_string(&path).unwrap(), bytes);
    }
    // Removing the header or dropping a complete identity while keeping the
    // closing marker must also be rejected, without editing the damaged file.
    for bytes in [lines[1..].concat(), [lines[0], lines[1], lines[3]].concat()] {
        std::fs::write(&path, &bytes).unwrap();
        assert!(matches!(
            DurableInferenceControl::open(&path, 8),
            Err(Error::CorruptJournal(_))
        ));
    }
    std::fs::write(&path, full).unwrap();
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native.active_reservations, 2);
}

#[test]
fn checkpoint_state_mutation_is_rejected_without_repairing_the_source() {
    let path = path("checkpoint-state-mutation");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "live");
    control
        .settle_native("live", output(NativeRunStatus::Completed, Some(1)))
        .unwrap();
    control.compact_journal().unwrap();
    let full = std::fs::read_to_string(&path).unwrap();
    drop(control);
    let lines: Vec<_> = full.lines().collect();
    let checkpoint: serde_json::Value =
        serde_json::from_str(lines[1].strip_prefix(CHECKPOINT_PREFIX).unwrap()).unwrap();
    for field in ["state", "revision", "turn_id"] {
        let mut changed = checkpoint.clone();
        changed["record"][field] = match field {
            "state" => serde_json::json!("reserved"),
            "revision" => serde_json::json!(0),
            "turn_id" => serde_json::json!("different-turn"),
            _ => unreachable!(),
        };
        let bytes = format!("{}\n{CHECKPOINT_PREFIX}{changed}\n{}\n", lines[0], lines[2]);
        std::fs::write(&path, &bytes).unwrap();
        assert!(DurableInferenceControl::open(&path, 8).is_err());
        assert_eq!(std::fs::read_to_string(&path).unwrap(), bytes);
    }
    std::fs::write(&path, full).unwrap();
    assert!(DurableInferenceControl::open(&path, 8).is_ok());
}

/// Durable fixture padding, not a logical transaction. One sync avoids turning
/// a capacity-boundary test into dozens of unrelated storage-latency samples.
pub(super) fn fill_admissible_bytes(control: &mut DurableInferenceControl) {
    let padding = vec![b'\n'; 1024 * 1024];
    let amount = control.journal_capacity_status().admissible_bytes;
    let mut remaining = amount;
    while remaining > 0 {
        let bytes = remaining.min(padding.len() as u64) as usize;
        control.file.write_all(&padding[..bytes]).unwrap();
        remaining -= bytes as u64;
    }
    control.file.flush().unwrap();
    control.file.sync_all().unwrap();
    control.journal_bytes += amount;
    assert_eq!(
        control.file.metadata().unwrap().len(),
        control.journal_bytes
    );
}
