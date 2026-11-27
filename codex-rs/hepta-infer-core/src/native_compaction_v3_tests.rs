use super::*;

use crate::durable_control::tests::held_journal_bytes;

#[test]
fn checkpoint_retains_complete_v3_input_authority_loss_and_uncertain_dispatch() -> TestResult<()> {
    let path = path("checkpoint-v3");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    control
        .reserve_native_prepared_v2(prepared_request()?, /*maximum_in_flight*/ 1, input()?)
        .unwrap();
    let (_, token) = control
        .dispatch_native_with_pre_effect_abort("r1", dispatch())
        .unwrap();
    drop(token);
    let dispatching = control.native_record("r1").unwrap().clone();
    control.compact_journal().unwrap();
    drop(control);
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    assert_eq!(control.native_record("r1"), Some(&dispatching));
    assert_eq!(dispatching.prepared_input_v2, Some(input()?));
    assert_eq!(
        control.dispatch_native("r1", dispatch()),
        Err(Error::InvalidTransition)
    );
    assert_eq!(
        control.stop_native_before_dispatch("r1", "not a recovered proof".into()),
        Err(Error::InvalidTransition)
    );
    let mut observed = output(NativeRunStatus::Indeterminate, None);
    observed.owner_authority = NativeOwnerAuthority::Lost {
        reason: "owner fenced".into(),
    };
    control.settle_native("r1", observed.clone()).unwrap();
    observed.status = NativeRunStatus::Completed;
    observed.boundary_status = NativeBoundaryStatus::Quarantined;
    observed.terminal_observed = true;
    observed.codex_terminal_correlation_digest = Some("d".repeat(64));
    let expected = control.settle_native("r1", observed.clone()).unwrap();
    control.compact_journal().unwrap();
    drop(control);
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    assert_eq!(control.native_record("r1"), Some(&expected));
    assert_eq!(expected.prepared_input_v2, Some(input()?));
    assert_eq!(expected.dispatch, dispatching.dispatch);
    assert!(!expected.observation.as_ref().unwrap().succeeded());
    observed.owner_authority = NativeOwnerAuthority::ObservedReady;
    assert_eq!(control.settle_native("r1", observed), Err(Error::Conflict));
    Ok(())
}

#[test]
fn checkpoint_v3_rejects_changed_snapshot_and_wrong_version_without_repair() -> TestResult<()> {
    let path = path("checkpoint-v3-corruption");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    control
        .reserve_native_prepared_v2(prepared_request()?, /*maximum_in_flight*/ 1, input()?)
        .unwrap();
    control.compact_journal().unwrap();
    drop(control);
    let original = std::fs::read_to_string(&path).unwrap();
    for damaged in [
        original.replace("original query", "different query"),
        original.replace("\"authority_epoch\":9", "\"authority_epoch\":10"),
        original.replace(CHECKPOINT_PREFIX, LEGACY_CHECKPOINT_PREFIX),
    ] {
        assert_ne!(damaged, original);
        std::fs::write(&path, &damaged).unwrap();
        assert!(DurableInferenceControl::open(&path, /*capacity*/ 8).is_err());
        assert_eq!(std::fs::read_to_string(&path).unwrap(), damaged);
    }
    std::fs::write(&path, &original).unwrap();
    let restored = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    assert_eq!(
        restored.native_record("r1").unwrap().prepared_input_v2,
        Some(input()?)
    );
    Ok(())
}

#[test]
fn legacy_checkpoint_without_prepared_input_remains_digest_only() -> TestResult<()> {
    let path = path("checkpoint-v1-digest-only");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    let expected = control
        .reserve_native(prepared_request()?, /*maximum_in_flight*/ 1)
        .unwrap();
    control.compact_journal().unwrap();
    drop(control);
    let image = std::fs::read_to_string(&path).unwrap();
    let legacy = image.replace(CHECKPOINT_PREFIX, LEGACY_CHECKPOINT_PREFIX);
    std::fs::write(&path, &legacy).unwrap();
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    assert_eq!(control.native_record("r1"), Some(&expected));
    let bytes = held_journal_bytes(&control.file)?;
    assert_eq!(
        control
            .reserve_native_prepared_v2(prepared_request()?, /*maximum_in_flight*/ 1, input()?)
            .unwrap(),
        expected
    );
    assert!(
        control
            .native_record("r1")
            .unwrap()
            .prepared_input_v2
            .is_none()
    );
    assert_eq!(held_journal_bytes(&control.file)?, bytes);
    Ok(())
}
