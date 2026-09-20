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
    owner
        .commit_state(|state| {
            state.staged.insert(
                PromptRuntimeKey {
                    thread_id: thread_id.to_owned(),
                    turn_id: turn_id.to_owned(),
                },
                value,
            );
            Ok(())
        })
        .unwrap_or_else(|error| panic!("stage raw: {error}"));
}

fn dispatch(
    value: &PromptRuntimeAttachmentV1,
    thread_id: &str,
    turn_id: &str,
    attempt_id: &str,
    request_binding_id: &str,
    provider_request_digest: Digest32,
) -> PromptRuntimeDispatchRecordV1 {
    PromptRuntimeDispatchRecordV1 {
        compilation_id: value.compilation_id.clone(),
        context_attachment_digest: value.context_attachment_digest,
        context_payload_digest: value.context_payload_digest,
        source_binding_digest: value.source_binding_digest,
        thread_id: thread_id.to_owned(),
        turn_id: turn_id.to_owned(),
        attempt_id: attempt_id.to_owned(),
        request_binding_id: request_binding_id.to_owned(),
        provider_request_digest,
        dispatched_unix_ms: 5,
    }
}

fn delivered_terminal(
    value: &PromptRuntimeAttachmentV1,
    attempt_id: &str,
    request_binding_id: &str,
    provider_request_digest: Digest32,
    observed_unix_ms: u64,
) -> PromptRuntimeTerminalRecordV1 {
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
    PromptRuntimeTerminalRecordV1 {
        compilation_id: value.compilation_id.clone(),
        context_attachment_digest: value.context_attachment_digest,
        context_payload_digest: value.context_payload_digest,
        source_binding_digest: value.source_binding_digest,
        thread_id: "thread:one".to_owned(),
        turn_id: "turn:one".to_owned(),
        attempt_id: attempt_id.to_owned(),
        request_binding_id: request_binding_id.to_owned(),
        provider_request_digest,
        outcome: PromptRuntimeTerminalOutcomeV1::Delivered,
        end_turn: Some(true),
        terminal_reason_code: None,
        delivery_observation: Some(observation),
        observed_unix_ms,
    }
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
    let provider_request_digest = digest("provider-request");
    owner
        .record_dispatch(dispatch(
            &value,
            "thread:one",
            "turn:one",
            "attempt:one",
            "request:one",
            provider_request_digest,
        ))
        .unwrap_or_else(|error| panic!("dispatch: {error}"));
    let record = PromptRuntimeTerminalRecordV1 {
        compilation_id: value.compilation_id.clone(),
        context_attachment_digest: value.context_attachment_digest,
        context_payload_digest: value.context_payload_digest,
        source_binding_digest: value.source_binding_digest,
        thread_id: "thread:one".to_owned(),
        turn_id: "turn:one".to_owned(),
        attempt_id: "attempt:one".to_owned(),
        request_binding_id: "request:one".to_owned(),
        provider_request_digest,
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
    assert!(
        owner
            .prepare(PromptRuntimePrepareRequest {
                thread_id: "thread:one".to_owned(),
                turn_id: "turn:one".to_owned(),
                model_context_window: Some(4096),
            })
            .unwrap_or_else(|error| panic!("retry prepare: {error}"))
            .is_some()
    );
}

#[test]
fn final_delivered_terminal_releases_staged_turn() {
    let owner = AgentdPromptRuntimeOwner::new();
    let value = attachment();
    stage_raw(&owner, "thread:one", "turn:one", value.clone());
    let provider_request_digest = digest("provider-request-final");
    owner
        .record_dispatch(dispatch(
            &value,
            "thread:one",
            "turn:one",
            "attempt:final",
            "request:final",
            provider_request_digest,
        ))
        .unwrap_or_else(|error| panic!("dispatch: {error}"));
    owner
        .record(delivered_terminal(
            &value,
            "attempt:final",
            "request:final",
            provider_request_digest,
            11,
        ))
        .unwrap_or_else(|error| panic!("record: {error}"));
    assert_eq!(
        owner
            .staged_count()
            .unwrap_or_else(|error| panic!("staged count: {error}")),
        0
    );
}

#[test]
fn not_dispatched_retry_then_final_delivery_reopens_without_stale_stage_requirement() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("prompt-runtime");
    let value = attachment();
    let first_digest = digest("provider-request-not-dispatched");
    let second_digest = digest("provider-request-retry-final");
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("open owner");
        stage_raw(&owner, "thread:one", "turn:one", value.clone());
        owner
            .record_dispatch(dispatch(
                &value,
                "thread:one",
                "turn:one",
                "attempt:first",
                "request:first",
                first_digest,
            ))
            .unwrap_or_else(|error| panic!("first dispatch: {error}"));
        owner
            .record(PromptRuntimeTerminalRecordV1 {
                compilation_id: value.compilation_id.clone(),
                context_attachment_digest: value.context_attachment_digest,
                context_payload_digest: value.context_payload_digest,
                source_binding_digest: value.source_binding_digest,
                thread_id: "thread:one".to_owned(),
                turn_id: "turn:one".to_owned(),
                attempt_id: "attempt:first".to_owned(),
                request_binding_id: "request:first".to_owned(),
                provider_request_digest: first_digest,
                outcome: PromptRuntimeTerminalOutcomeV1::NotDispatched,
                end_turn: None,
                terminal_reason_code: Some("pre_send_cancel".to_owned()),
                delivery_observation: None,
                observed_unix_ms: 10,
            })
            .unwrap_or_else(|error| panic!("not-dispatched record: {error}"));
        owner
            .record_dispatch(dispatch(
                &value,
                "thread:one",
                "turn:one",
                "attempt:second",
                "request:second",
                second_digest,
            ))
            .unwrap_or_else(|error| panic!("second dispatch: {error}"));
        owner
            .record(delivered_terminal(
                &value,
                "attempt:second",
                "request:second",
                second_digest,
                11,
            ))
            .unwrap_or_else(|error| panic!("delivered record: {error}"));
        assert_eq!(owner.staged_count().expect("staged count"), 0);
    }

    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("reopen owner");
    assert_eq!(reopened.staged_count().expect("staged count"), 0);
    assert_eq!(
        reopened
            .terminal_record("attempt:first")
            .expect("first terminal")
            .map(|record| record.outcome),
        Some(PromptRuntimeTerminalOutcomeV1::NotDispatched)
    );
    assert_eq!(
        reopened
            .terminal_record("attempt:second")
            .expect("second terminal")
            .map(|record| record.outcome),
        Some(PromptRuntimeTerminalOutcomeV1::Delivered)
    );
}

#[test]
fn dispatch_without_terminal_reopens_as_unknown_and_blocks_blind_retry() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("prompt-runtime");
    let value = attachment();
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("open owner");
        stage_raw(&owner, "thread:one", "turn:one", value.clone());
        owner
            .record_dispatch(dispatch(
                &value,
                "thread:one",
                "turn:one",
                "attempt:unknown",
                "request:unknown",
                digest("provider-request-unknown"),
            ))
            .unwrap_or_else(|error| panic!("dispatch: {error}"));
    }

    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("reopen owner");
    assert!(
        reopened
            .prepare(PromptRuntimePrepareRequest {
                thread_id: "thread:one".to_owned(),
                turn_id: "turn:one".to_owned(),
                model_context_window: Some(4096),
            })
            .is_err()
    );
    assert!(
        reopened
            .dispatch_record("attempt:unknown")
            .expect("dispatch lookup")
            .is_some()
    );
    assert!(
        reopened
            .terminal_record("attempt:unknown")
            .expect("terminal lookup")
            .is_none()
    );
}

#[test]
fn indeterminate_terminal_reopens_blocked_and_reconciles_monotonically() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("prompt-runtime");
    let value = attachment();
    let provider_request_digest = digest("provider-request-indeterminate");
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("open owner");
        stage_raw(&owner, "thread:one", "turn:one", value.clone());
        owner
            .record_dispatch(dispatch(
                &value,
                "thread:one",
                "turn:one",
                "attempt:indeterminate",
                "request:indeterminate",
                provider_request_digest,
            ))
            .unwrap_or_else(|error| panic!("dispatch: {error}"));
        owner
            .record(PromptRuntimeTerminalRecordV1 {
                compilation_id: value.compilation_id.clone(),
                context_attachment_digest: value.context_attachment_digest,
                context_payload_digest: value.context_payload_digest,
                source_binding_digest: value.source_binding_digest,
                thread_id: "thread:one".to_owned(),
                turn_id: "turn:one".to_owned(),
                attempt_id: "attempt:indeterminate".to_owned(),
                request_binding_id: "request:indeterminate".to_owned(),
                provider_request_digest,
                outcome: PromptRuntimeTerminalOutcomeV1::Indeterminate,
                end_turn: None,
                terminal_reason_code: Some("ack_lost".to_owned()),
                delivery_observation: None,
                observed_unix_ms: 10,
            })
            .unwrap_or_else(|error| panic!("indeterminate record: {error}"));
    }

    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("reopen owner");
    assert!(
        reopened
            .prepare(PromptRuntimePrepareRequest {
                thread_id: "thread:one".to_owned(),
                turn_id: "turn:one".to_owned(),
                model_context_window: Some(4096),
            })
            .is_err()
    );
    reopened
        .record(delivered_terminal(
            &value,
            "attempt:indeterminate",
            "request:indeterminate",
            provider_request_digest,
            11,
        ))
        .unwrap_or_else(|error| panic!("reconcile delivered: {error}"));
    assert_eq!(reopened.staged_count().expect("staged count"), 0);
    assert_eq!(
        reopened
            .terminal_record("attempt:indeterminate")
            .expect("terminal")
            .map(|record| record.outcome),
        Some(PromptRuntimeTerminalOutcomeV1::Delivered)
    );
}

#[test]
fn post_rename_ack_loss_poison_reopens_to_dispatch_claim_not_absent() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("prompt-runtime");
    let value = attachment();
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("open owner");
        stage_raw(&owner, "thread:one", "turn:one", value.clone());
        owner.fail_directory_sync_after_rename_once();
        assert!(
            owner
                .record_dispatch(dispatch(
                    &value,
                    "thread:one",
                    "turn:one",
                    "attempt:ack-loss",
                    "request:ack-loss",
                    digest("provider-request-ack-loss"),
                ))
                .is_err()
        );
        assert!(owner.requires_reopen());
    }

    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root).expect("reopen owner");
    assert!(
        reopened
            .dispatch_record("attempt:ack-loss")
            .expect("dispatch lookup")
            .is_some()
    );
    assert!(
        reopened
            .prepare(PromptRuntimePrepareRequest {
                thread_id: "thread:one".to_owned(),
                turn_id: "turn:one".to_owned(),
                model_context_window: Some(4096),
            })
            .is_err()
    );
}
