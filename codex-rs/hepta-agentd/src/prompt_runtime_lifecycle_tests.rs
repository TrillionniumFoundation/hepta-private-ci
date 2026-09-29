//! Default-profile regressions for the existing durable runtime projection.
use super::*;

fn attachment(text: String) -> PromptRuntimeAttachmentV1 {
    PromptRuntimeAttachmentV1::new(
        StableId::new("compilation:lifecycle").expect("id"),
        Digest32::of_bytes(b"attachment"), Digest32::of_bytes(text.as_bytes()),
        "model", 10_000,
        vec![PromptRuntimeDeveloperFragmentV1::new(text).expect("fragment")],
    ).expect("attachment")
}

fn stage(owner: &AgentdPromptRuntimeOwner, turn: &str, value: PromptRuntimeAttachmentV1)
    -> Result<(), AgentdPromptRuntimeError>
{
    owner.commit_state(|state| {
        state.staged.insert(PromptRuntimeKey { thread_id: "thread".into(), turn_id: turn.into() }, value);
        Ok(())
    })
}

fn dispatch(value: &PromptRuntimeAttachmentV1) -> PromptRuntimeDispatchRecordV1 {
    PromptRuntimeDispatchRecordV1 {
        compilation_id: value.compilation_id.clone(),
        context_attachment_digest: value.context_attachment_digest,
        context_payload_digest: value.context_payload_digest,
        source_binding_digest: value.source_binding_digest,
        thread_id: "thread".into(), turn_id: "turn".into(), attempt_id: "attempt".into(),
        request_binding_id: "binding".into(), provider_request_digest: Digest32::of_bytes(b"body"),
        dispatched_unix_ms: 1,
    }
}

fn terminal(value: &PromptRuntimeAttachmentV1) -> PromptRuntimeTerminalRecordV1 {
    PromptRuntimeTerminalRecordV1 {
        compilation_id: value.compilation_id.clone(),
        context_attachment_digest: value.context_attachment_digest,
        context_payload_digest: value.context_payload_digest,
        source_binding_digest: value.source_binding_digest,
        thread_id: "thread".into(), turn_id: "turn".into(), attempt_id: "attempt".into(),
        request_binding_id: "binding".into(), provider_request_digest: Digest32::of_bytes(b"body"),
        outcome: PromptRuntimeTerminalOutcomeV1::NotDispatched, end_turn: None,
        terminal_reason_code: Some("fixture_not_dispatched".into()),
        delivery_observation: None, observed_unix_ms: 2,
    }
}

#[test]
fn explicit_retirement_survives_reopen_without_raw_context() {
    let directory = tempfile::tempdir().expect("directory");
    let value = attachment("PRIVATE-CONTEXT-LIFECYCLE".into());
    let owner = AgentdPromptRuntimeOwner::open_state_dir(directory.path()).expect("open");
    stage(&owner, "turn", value.clone()).expect("stage");
    owner.record_dispatch(dispatch(&value)).expect("dispatch");
    owner.record(terminal(&value)).expect("not dispatched");
    assert!(owner.clear_turn("thread", "turn").expect("explicit abort"));
    drop(owner);
    let bytes = std::fs::read(directory.path().join(STATE_FILE)).expect("state bytes");
    assert!(!String::from_utf8_lossy(&bytes).contains("PRIVATE-CONTEXT-LIFECYCLE"));
    let owner = AgentdPromptRuntimeOwner::open_state_dir(directory.path()).expect("reopen");
    assert_eq!(owner.staged_count().expect("count"), 0);
    assert!(owner.terminal_record("attempt").expect("history").is_some());
    assert!(owner.record_dispatch(dispatch(&value)).is_ok()); // exact historical retry only
    let mut changed = dispatch(&value);
    changed.attempt_id = "second-attempt".into();
    assert!(owner.record_dispatch(changed).is_err());
}

#[test]
fn unresolved_attempt_cannot_be_retired() {
    let owner = AgentdPromptRuntimeOwner::new();
    let value = attachment("context".into());
    stage(&owner, "turn", value.clone()).expect("stage");
    owner.record_dispatch(dispatch(&value)).expect("dispatch");
    let mut unknown = terminal(&value);
    unknown.outcome = PromptRuntimeTerminalOutcomeV1::Indeterminate;
    owner.record(unknown).expect("unknown");
    assert_eq!(owner.clear_turn("thread", "turn"), Err(AgentdPromptRuntimeError::IndeterminatePending));
    assert_eq!(owner.staged_count().expect("count"), 1);
}

#[test]
fn schema_one_cannot_smuggle_retirement_and_schema_two_rejects_orphans() {
    let mut stored = stored_state(&PromptRuntimeState::default());
    stored.schema = 1;
    assert!(restore_state(stored).is_ok());
    for schema in [1, PROMPT_RUNTIME_SCHEMA] {
        let mut stored = stored_state(&PromptRuntimeState::default());
        stored.schema = schema;
        stored.retired.push(PromptRuntimeKey { thread_id: "thread".into(), turn_id: "turn".into() });
        assert!(restore_state(stored).is_err());
    }
}

#[test]
fn new_staging_cannot_spend_an_admitted_attempts_completion_reserve() {
    let directory = tempfile::tempdir().expect("directory");
    let owner = AgentdPromptRuntimeOwner::open_state_dir(directory.path()).expect("owner");
    let value = attachment("context".into());
    stage(&owner, "turn", value.clone()).expect("stage");
    owner.record_dispatch(dispatch(&value)).expect("dispatch");
    let near_capacity = usize::try_from(MAX_DURABLE_STATE_BYTES - TERMINAL_RESERVE_BYTES - 32 * 1024)
        .expect("bounded capacity");
    stage(&owner, "large-turn", attachment("x".repeat(near_capacity))).expect("reserve-aware fill");
    assert_eq!(stage(&owner, "extra-turn", attachment("x".repeat(40 * 1024))),
        Err(AgentdPromptRuntimeError::CapacityExceeded));
    let mut final_record = terminal(&value);
    final_record.outcome = PromptRuntimeTerminalOutcomeV1::Delivered;
    final_record.end_turn = Some(true);
    final_record.terminal_reason_code = None;
    final_record.delivery_observation = Some(PromptDeliveryObservationV1 {
        compilation_id: value.compilation_id.clone(),
        provider_request_digest: final_record.provider_request_digest,
        delivered: true, rejected_reason: None,
        observed_token_positions: Some((u32::MAX - 8192..u32::MAX).collect()),
        truncation_observed: false,
    });
    owner.record(final_record.clone()).expect("maximum positions final fits reserved space");
    drop(owner);
    let owner = AgentdPromptRuntimeOwner::open_state_dir(directory.path()).expect("reopen final");
    assert_eq!(owner.terminal_record("attempt").expect("terminal"), Some(final_record));
}
