use super::*;

fn dispatch(value: &PromptRuntimeAttachmentV1) -> PromptRuntimeDispatchRecordV1 {
    tests::dispatch(
        value,
        "thread:one",
        "turn:one",
        "attempt:time-bound",
        "request:time-bound",
        Digest32::of_bytes(b"provider-request"),
    )
}

#[test]
fn dispatch_deadline_is_exclusive_and_failed_claim_does_not_mutate_state() {
    let value = tests::attachment();
    for dispatched_unix_ms in [
        value.deadline_ms - 1,
        value.deadline_ms,
        value.deadline_ms + 1,
    ] {
        let owner = AgentdPromptRuntimeOwner::new();
        tests::stage_raw(&owner, "thread:one", "turn:one", value.clone());
        let mut record = dispatch(&value);
        record.dispatched_unix_ms = dispatched_unix_ms;
        let accepted = dispatched_unix_ms < value.deadline_ms;
        assert_eq!(owner.record_dispatch(record.clone()).is_ok(), accepted);
        assert_eq!(
            owner.dispatch_record(&record.attempt_id),
            Ok(accepted.then_some(record))
        );
        assert_eq!(owner.staged_count(), Ok(1));
    }
}

#[test]
fn restored_pending_dispatch_cannot_postdate_attachment_expiry() {
    let owner = AgentdPromptRuntimeOwner::new();
    let value = tests::attachment();
    tests::stage_raw(&owner, "thread:one", "turn:one", value.clone());
    owner.record_dispatch(dispatch(&value)).expect("dispatch");
    let mut stored = stored_state(&owner.state.lock().expect("state"));
    stored.dispatches[0].dispatched_unix_ms = value.deadline_ms;
    assert_eq!(
        restore_state(stored),
        Err(AgentdPromptRuntimeError::CorruptState)
    );
}

#[test]
fn terminal_cannot_precede_dispatch_and_equal_timestamp_is_valid() {
    let owner = AgentdPromptRuntimeOwner::new();
    let value = tests::attachment();
    tests::stage_raw(&owner, "thread:one", "turn:one", value.clone());
    let dispatch = dispatch(&value);
    owner.record_dispatch(dispatch.clone()).expect("dispatch");
    let before = tests::delivered_terminal(
        &value,
        &dispatch.attempt_id,
        &dispatch.request_binding_id,
        dispatch.provider_request_digest,
        dispatch.dispatched_unix_ms - 1,
    );
    assert!(owner.record(before.clone()).is_err());
    assert_eq!(owner.terminal_record(&dispatch.attempt_id), Ok(None));
    assert_eq!(owner.staged_count(), Ok(1));
    let mut equal = before;
    equal.observed_unix_ms = dispatch.dispatched_unix_ms;
    owner
        .record(equal.clone())
        .expect("same timestamp terminal");
    assert_eq!(owner.terminal_record(&dispatch.attempt_id), Ok(Some(equal)));
    assert_eq!(owner.staged_count(), Ok(0));
}

#[test]
fn restored_terminal_cannot_predate_dispatch_after_stage_cleanup() {
    let owner = AgentdPromptRuntimeOwner::new();
    let value = tests::attachment();
    tests::stage_raw(&owner, "thread:one", "turn:one", value.clone());
    let dispatch = dispatch(&value);
    owner.record_dispatch(dispatch.clone()).expect("dispatch");
    owner
        .record(tests::delivered_terminal(
            &value,
            &dispatch.attempt_id,
            &dispatch.request_binding_id,
            dispatch.provider_request_digest,
            dispatch.dispatched_unix_ms,
        ))
        .expect("terminal");
    let mut stored = stored_state(&owner.state.lock().expect("state"));
    assert!(stored.staged.is_empty());
    stored.terminals[0].observed_unix_ms = dispatch.dispatched_unix_ms - 1;
    assert_eq!(
        restore_state(stored),
        Err(AgentdPromptRuntimeError::CorruptState)
    );
}
