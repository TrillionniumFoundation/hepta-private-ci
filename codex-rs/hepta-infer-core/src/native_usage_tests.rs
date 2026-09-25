//! Late settlement is a durable responsibility even after execution releases.
use super::*;

#[test]
fn terminal_without_usage_retains_settlement_liability_across_reopen() {
    let path = path("missing-usage-liability");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "live");
    let terminal = output(NativeRunStatus::Completed, None);
    let released = control.settle_native("live", terminal).unwrap();
    assert_eq!(released.state, NativeReservationState::Released);
    assert_eq!(control.native.active_reservations, 0);
    assert_eq!(
        control.journal_capacity_status().reserved_headroom_bytes,
        4 * 1024
    );
    control.compact_journal().unwrap();
    drop(control);
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native_record("live"), Some(&released));
    assert_eq!(
        control.journal_capacity_status().reserved_headroom_bytes,
        4 * 1024
    );
}

#[test]
fn full_journal_accepts_small_usage_delta_without_rewriting_terminal_body() {
    let path = path("usage-at-full-byte-boundary");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "live");
    let mut terminal = output(NativeRunStatus::Completed, None);
    terminal.output = "\0".repeat(1024 * 1024);
    control.settle_native("live", terminal.clone()).unwrap();
    maintenance::fill_admissible_bytes(&mut control);
    let full = control.journal_capacity_status();
    assert_eq!(full.admissible_bytes, 0);
    assert_eq!(full.reserved_headroom_bytes, USAGE_HEADROOM_BYTES);
    terminal.observed_output_tokens = Some(u64::MAX);
    let settled = control.settle_native("live", terminal.clone()).unwrap();
    let after = control.journal_capacity_status();
    assert!(after.journal_bytes > full.journal_bytes);
    assert!(after.journal_bytes - full.journal_bytes < USAGE_HEADROOM_BYTES);
    assert_eq!(after.reserved_headroom_bytes, 0);
    assert_eq!(control.native.active_reservations, 0);
    assert_eq!(control.settle_native("live", terminal).unwrap(), settled);
    assert_eq!(control.journal_capacity_status(), after);
    drop(control);
    let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(reopened.native_record("live"), Some(&settled));
    assert_eq!(reopened.native.active_reservations, 0);
    reopened.compact_journal().unwrap();
    drop(reopened);
    let reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(reopened.native_record("live"), Some(&settled));
    assert_eq!(
        reopened.journal_capacity_status().reserved_headroom_bytes,
        0
    );
}

#[test]
fn usage_delta_rejects_stale_predecessor_and_nonmonotonic_usage_before_append() {
    let path = path("usage-predecessor");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "live");
    let terminal = output(NativeRunStatus::Completed, Some(2));
    let settled = control.settle_native("live", terminal).unwrap();
    let bytes = std::fs::read(&path).unwrap();
    for (revision, tokens) in [
        (settled.revision - 1, 3),
        (settled.revision, 1),
        (settled.revision, 2),
    ] {
        assert_eq!(
            control.commit_native(
                "live",
                Event::RefineUsage {
                    request_id: "live".into(),
                    expected_revision: revision,
                    observed_output_tokens: tokens,
                }
            ),
            Err(Error::Conflict)
        );
        assert_eq!(control.native_record("live"), Some(&settled));
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
    let delta = Event::RefineUsage {
        request_id: "live".into(),
        expected_revision: settled.revision,
        observed_output_tokens: 3,
    };
    let mut replay = control.native.clone();
    replay.apply(delta.clone()).unwrap();
    assert_eq!(replay.apply(delta), Err(Error::Conflict));
}

#[test]
fn usage_optimization_does_not_hide_terminal_identity_or_body_mutation() {
    let path = path("usage-body-conflict");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "live");
    let terminal = output(NativeRunStatus::Completed, None);
    let settled = control.settle_native("live", terminal.clone()).unwrap();
    let bytes = std::fs::read(&path).unwrap();
    for variant in 0..5 {
        let mut changed = terminal.clone();
        changed.observed_output_tokens = Some(4);
        match variant {
            0 => changed.output.push('x'),
            1 => changed.thread_id.push('x'),
            2 => changed.turn_id.push('x'),
            3 => changed.status = NativeRunStatus::Failed,
            4 => changed.codex_terminal_correlation_digest = Some("0".repeat(64)),
            _ => unreachable!(),
        }
        assert!(control.settle_native("live", changed).is_err());
        assert_eq!(control.native_record("live"), Some(&settled));
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
}

#[test]
fn failed_usage_append_preserves_missing_usage_and_poisoned_owner_cannot_retry() {
    let path = path("usage-write-failure");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "live");
    let terminal = output(NativeRunStatus::Completed, None);
    let before = control.settle_native("live", terminal.clone()).unwrap();
    let bytes = std::fs::read(&path).unwrap();
    let writable = std::mem::replace(&mut control.file, std::fs::File::open(&path).unwrap());
    let mut usage = terminal;
    usage.observed_output_tokens = Some(5);
    assert!(matches!(
        control.settle_native("live", usage.clone()),
        Err(Error::Io(_))
    ));
    assert_eq!(control.native_record("live"), Some(&before));
    assert_eq!(control.native.active_reservations, 0);
    assert_eq!(
        control.journal_capacity_status().reserved_headroom_bytes,
        USAGE_HEADROOM_BYTES
    );
    assert!(control.poisoned);
    assert_eq!(
        control.settle_native("live", usage),
        Err(Error::WriterUnavailable)
    );
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    drop(writable);
    drop(control);
    let reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(reopened.native_record("live"), Some(&before));
}

#[test]
fn legacy_full_observation_usage_refinement_replays_and_compacts() {
    let path = path("legacy-usage-frame");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "live");
    control
        .settle_native("live", output(NativeRunStatus::Completed, None))
        .unwrap();
    let usage = output(NativeRunStatus::Completed, Some(9));
    let expected = control
        .commit_native(
            "live",
            Event::Observe {
                request_id: "live".into(),
                output: usage,
            },
        )
        .unwrap();
    drop(control);
    let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(reopened.native_record("live"), Some(&expected));
    reopened.compact_journal().unwrap();
    drop(reopened);
    let reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(reopened.native_record("live"), Some(&expected));
}
