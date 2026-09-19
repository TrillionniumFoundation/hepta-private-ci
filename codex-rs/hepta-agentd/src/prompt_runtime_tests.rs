use super::*;

use codex_hepta_types::Digest32;
use codex_hepta_types::PromptDeliveryObservationV1;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn attachment() -> PromptRuntimeAttachmentV1 {
    PromptRuntimeAttachmentV1::new(
        id("compilation:agentd-prompt"),
        digest("attachment"),
        digest("payload"),
        "gpt-test",
        10_000,
        vec![
            PromptRuntimeDeveloperFragmentV1::new("Verify before mutation.")
                .unwrap_or_else(|error| panic!("fragment: {error}")),
        ],
    )
    .unwrap_or_else(|error| panic!("attachment: {error}"))
}

fn stage_raw(
    owner: &AgentdPromptRuntimeOwner,
    thread_id: &str,
    turn_id: &str,
    value: PromptRuntimeAttachmentV1,
) {
    let mut state = owner
        .state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    state.staged.insert(
        PromptRuntimeKey {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
        },
        value,
    );
}

#[test]
fn staged_attachment_is_bound_to_exact_thread_and_turn() {
    let owner = AgentdPromptRuntimeOwner::new();
    stage_raw(&owner, "thread:one", "turn:one", attachment());

    let exact = owner
        .prepare(PromptRuntimePrepareRequest {
            thread_id: "thread:one".to_owned(),
            turn_id: "turn:one".to_owned(),
            model_context_window: Some(4096),
        })
        .unwrap_or_else(|error| panic!("prepare: {error}"));
    assert!(exact.is_some());

    let wrong_thread = owner
        .prepare(PromptRuntimePrepareRequest {
            thread_id: "thread:two".to_owned(),
            turn_id: "turn:one".to_owned(),
            model_context_window: Some(4096),
        })
        .unwrap_or_else(|error| panic!("prepare: {error}"));
    assert!(wrong_thread.is_none());
}

#[test]
fn non_dispatch_terminal_is_idempotent_and_retains_stage_for_retry() {
    let owner = AgentdPromptRuntimeOwner::new();
    let value = attachment();
    stage_raw(&owner, "thread:one", "turn:one", value.clone());
    let record = PromptRuntimeTerminalRecordV1 {
        compilation_id: value.compilation_id.clone(),
        context_attachment_digest: value.context_attachment_digest,
        context_payload_digest: value.context_payload_digest,
        source_binding_digest: value.source_binding_digest,
        thread_id: "thread:one".to_owned(),
        turn_id: "turn:one".to_owned(),
        attempt_id: "attempt:one".to_owned(),
        request_binding_id: "request:one".to_owned(),
        provider_request_digest: digest("provider-request"),
        outcome: PromptRuntimeTerminalOutcomeV1::NotDispatched,
        end_turn: None,
        terminal_reason_code: Some("cancelled_before_send".to_owned()),
        delivery_observation: None,
        observed_unix_ms: 10,
    };
    owner
        .record(record.clone())
        .unwrap_or_else(|error| panic!("record: {error}"));
    owner
        .record(record.clone())
        .unwrap_or_else(|error| panic!("idempotent record: {error}"));
    assert_eq!(
        owner
            .terminal_record("attempt:one")
            .unwrap_or_else(|error| panic!("terminal lookup: {error}")),
        Some(record)
    );
    assert_eq!(
        owner
            .staged_count()
            .unwrap_or_else(|error| panic!("staged count: {error}")),
        1
    );
}

#[test]
fn final_delivered_terminal_releases_staged_turn() {
    let owner = AgentdPromptRuntimeOwner::new();
    let value = attachment();
    stage_raw(&owner, "thread:one", "turn:one", value.clone());
    let provider_request_digest = digest("provider-request-final");
    let observation = PromptDeliveryObservationV1 {
        compilation_id: value.compilation_id.clone(),
        provider_request_digest,
        delivered: true,
        rejected_reason: None,
        observed_token_positions: None,
        truncation_observed: false,
    };
    observation
        .validate()
        .unwrap_or_else(|error| panic!("observation: {error}"));
    let record = PromptRuntimeTerminalRecordV1 {
        compilation_id: value.compilation_id,
        context_attachment_digest: value.context_attachment_digest,
        context_payload_digest: value.context_payload_digest,
        source_binding_digest: value.source_binding_digest,
        thread_id: "thread:one".to_owned(),
        turn_id: "turn:one".to_owned(),
        attempt_id: "attempt:final".to_owned(),
        request_binding_id: "request:final".to_owned(),
        provider_request_digest,
        outcome: PromptRuntimeTerminalOutcomeV1::Delivered,
        end_turn: Some(true),
        terminal_reason_code: None,
        delivery_observation: Some(observation),
        observed_unix_ms: 11,
    };
    owner
        .record(record)
        .unwrap_or_else(|error| panic!("record: {error}"));
    assert_eq!(
        owner
            .staged_count()
            .unwrap_or_else(|error| panic!("staged count: {error}")),
        0
    );
}
