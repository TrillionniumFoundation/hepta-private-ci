//! Regressions for one-record preparation and replay-built reservation counts.
use super::*;

fn assert_active(control: &DurableInferenceControl, expected: usize) {
    assert_eq!(control.native.active_reservations, expected);
    assert_eq!(
        control
            .native
            .records
            .values()
            .filter(|record| { record.state != NativeReservationState::Released })
            .count(),
        expected,
    );
}

#[test]
fn unrelated_updates_do_not_copy_historical_output_or_lose_other_reservations() {
    let path = path("incremental-history");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "historical");
    let mut observed = output(NativeRunStatus::Completed, Some(1));
    observed.output = "x".repeat(1024 * 1024);
    control
        .settle_native("historical", observed.clone())
        .unwrap();
    let retained = control.native_record("historical").unwrap().clone();
    let allocation = control
        .native_record("historical")
        .unwrap()
        .observation
        .as_ref()
        .unwrap()
        .output
        .as_ptr();
    control.reserve_native(request("current"), 1).unwrap();
    assert_active(&control, 1);
    assert_eq!(
        control
            .native_record("historical")
            .unwrap()
            .observation
            .as_ref()
            .unwrap()
            .output
            .as_ptr(),
        allocation
    );
    // Refining a historical terminal must not release the current request slot.
    observed.observed_output_tokens = Some(2);
    control.settle_native("historical", observed).unwrap();
    assert_active(&control, 1);
    assert_eq!(
        control.reserve_native(request("excess"), 1),
        Err(Error::CapacityExceeded)
    );
    let allocation = {
        // The refinement may replace its OWN allocation, but later unrelated
        // operations must retain this allocation and all historical semantics.
        control
            .native_record("historical")
            .unwrap()
            .observation
            .as_ref()
            .unwrap()
            .output
            .as_ptr()
    };
    control
        .stop_native_before_dispatch("current", "cancelled before dispatch".to_string())
        .unwrap();
    assert_active(&control, 0);
    assert_eq!(
        control
            .native_record("historical")
            .unwrap()
            .observation
            .as_ref()
            .unwrap()
            .output
            .as_ptr(),
        allocation
    );
    assert_eq!(
        control.native_record("historical").unwrap().request,
        retained.request
    );
    let records = control.native.records.clone();
    drop(control);
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_active(&control, 0);
    assert_eq!(control.native.records, records);
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn rejected_transition_and_failed_append_preserve_records_and_slot_count() {
    let path = path("incremental-atomicity");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("one"), 2).unwrap();
    control.reserve_native(request("two"), 2).unwrap();
    assert_active(&control, 2);
    let before = control.native.records.clone();
    let bytes = std::fs::read(&path).unwrap();
    let invalid = Event::Started {
        request_id: "one".to_string(),
        turn_id: "turn".to_string(),
    };
    assert_eq!(
        control.commit_native("one", invalid),
        Err(Error::InvalidTransition)
    );
    assert_eq!(control.native.records, before);
    assert_active(&control, 2);
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    // Keep the original locked descriptor alive while forcing an actual I/O
    // failure on the append descriptor. No production fault hook is introduced.
    let locked = std::mem::replace(&mut control.file, std::fs::File::open(&path).unwrap());
    assert!(
        control
            .stop_native_before_dispatch("one", "stop".to_string())
            .is_err()
    );
    assert!(control.poisoned);
    assert_active(&control, 2);
    assert_eq!(control.native.records, before);
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    drop(control);
    drop(locked);
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native.records, before);
    assert_active(&control, 2);
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn active_count_survives_unknown_outcome_reopen_and_terminal_refinement() {
    let path = path("incremental-active-replay");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "one");
    control
        .settle_native("one", output(NativeRunStatus::Indeterminate, None))
        .unwrap();
    assert_active(&control, 1);
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_active(&control, 1);
    assert_eq!(
        control.reserve_native(request("two"), 1),
        Err(Error::CapacityExceeded)
    );
    control
        .settle_native("one", output(NativeRunStatus::Completed, Some(1)))
        .unwrap();
    assert_active(&control, 0);
    control.reserve_native(request("two"), 1).unwrap();
    control
        .settle_native("one", output(NativeRunStatus::Completed, Some(2)))
        .unwrap();
    assert_active(&control, 1);
    let before = control.native.records.clone();
    drop(control);
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_active(&control, 1);
    assert_eq!(control.native.records, before);
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn owner_drop_releases_locks_held_by_duplicate_descriptors() {
    let path = path("owner-drop-duplicates");
    let mut owner = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut owner, "held");
    let records = owner.native.records.clone();
    // A forked child can briefly retain these open file descriptions until exec.
    // Duplicates must not keep a retired owner locked, nor unlock its successor.
    let data = owner.file.try_clone().unwrap();
    let lock = owner._writer_lock.try_clone().unwrap();
    assert_eq!(
        DurableInferenceControl::open(&path, 8).unwrap_err(),
        Error::WriterUnavailable
    );
    drop(owner);
    let successor = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(successor.native.records, records);
    drop(data);
    drop(lock);
    assert_eq!(
        DurableInferenceControl::open(&path, 8).unwrap_err(),
        Error::WriterUnavailable
    );
    drop(successor);
    let reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(reopened.native.records, records);
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}
