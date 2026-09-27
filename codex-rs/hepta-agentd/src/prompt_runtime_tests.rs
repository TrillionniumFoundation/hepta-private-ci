use super::*;
use codex_hepta_prompt_optimizer::canonical::*;
use codex_hepta_context_compiler::ContextModelProfileV2;
use crate::{AgentdPromptOptimizerV1, AgentdPromptOptimizationRequestV1, AgentdPromptOptimizationOutcomeV1};

#[path = "prompt_optimizer_evidence_fixture.rs"]
mod evidence_fixture;

fn id(value: &str) -> StableId { StableId::new(value).unwrap_or_else(|e| panic!("id: {e}")) }
fn digest(value: &str) -> Digest32 { Digest32::of_bytes(value.as_bytes()) }
fn attachment() -> PromptRuntimeAttachmentV1 {
    PromptRuntimeAttachmentV1::new(id("compilation:agentd-prompt"), digest("attachment"), digest("payload"), "gpt-test", 10_000,
        vec![PromptRuntimeDeveloperFragmentV1::new("Verify before mutation.").unwrap_or_else(|e| panic!("fragment: {e}"))])
        .unwrap_or_else(|e| panic!("attachment: {e}"))
}
fn prepare_request() -> PromptRuntimePrepareRequest {
    PromptRuntimePrepareRequest { thread_id: "thread:one".to_owned(), turn_id: "turn:one".to_owned(), model_context_window: Some(4096) }
}
fn stage_raw(owner: &AgentdPromptRuntimeOwner, value: PromptRuntimeAttachmentV1) {
    owner.commit_state(|state| {
        state.staged.insert(PromptRuntimeKey { thread_id: "thread:one".to_owned(), turn_id: "turn:one".to_owned() }, value);
        Ok(())
    }).unwrap_or_else(|e| panic!("stage: {e}"));
}
fn dispatch(value: &PromptRuntimeAttachmentV1, attempt: &str, request: &str, provider: Digest32) -> PromptRuntimeDispatchRecordV1 {
    PromptRuntimeDispatchRecordV1 {
        compilation_id: value.compilation_id.clone(), context_attachment_digest: value.context_attachment_digest,
        context_payload_digest: value.context_payload_digest, source_binding_digest: value.source_binding_digest,
        thread_id: "thread:one".to_owned(), turn_id: "turn:one".to_owned(), attempt_id: attempt.to_owned(),
        request_binding_id: request.to_owned(), provider_request_digest: provider, dispatched_unix_ms: 5,
    }
}
fn terminal(value: &PromptRuntimeAttachmentV1, attempt: &str, request: &str, provider: Digest32,
    outcome: PromptRuntimeTerminalOutcomeV1) -> PromptRuntimeTerminalRecordV1 {
    let delivered = outcome == PromptRuntimeTerminalOutcomeV1::Delivered;
    PromptRuntimeTerminalRecordV1 {
        compilation_id: value.compilation_id.clone(), context_attachment_digest: value.context_attachment_digest,
        context_payload_digest: value.context_payload_digest, source_binding_digest: value.source_binding_digest,
        thread_id: "thread:one".to_owned(), turn_id: "turn:one".to_owned(), attempt_id: attempt.to_owned(),
        request_binding_id: request.to_owned(), provider_request_digest: provider, outcome,
        end_turn: delivered.then_some(true), terminal_reason_code: (!delivered).then(|| "fixture_terminal_reason".to_owned()),
        delivery_observation: delivered.then(|| PromptDeliveryObservationV1 {
            compilation_id: value.compilation_id.clone(), provider_request_digest: provider, delivered: true,
            rejected_reason: None, observed_token_positions: None, truncation_observed: false,
        }),
        observed_unix_ms: if delivered { 11 } else { 10 },
    }
}

#[test]
fn staged_attachment_is_bound_to_exact_thread_and_turn() {
    let owner = AgentdPromptRuntimeOwner::new();
    stage_raw(&owner, attachment());
    assert!(owner.prepare(prepare_request()).unwrap_or_else(|e| panic!("prepare: {e}")).is_some());
    let mut wrong = prepare_request();
    wrong.thread_id = "thread:two".to_owned();
    assert!(owner.prepare(wrong).unwrap_or_else(|e| panic!("prepare: {e}")).is_none());
}

#[test]
fn non_dispatch_terminal_is_idempotent_and_retains_stage_for_retry() {
    let owner = AgentdPromptRuntimeOwner::new();
    let value = attachment();
    stage_raw(&owner, value.clone());
    let provider = digest("provider-request");
    owner.record_dispatch(dispatch(&value, "attempt:one", "request:one", provider)).unwrap_or_else(|e| panic!("dispatch: {e}"));
    let record = terminal(&value, "attempt:one", "request:one", provider, PromptRuntimeTerminalOutcomeV1::NotDispatched);
    owner.record(record.clone()).unwrap_or_else(|e| panic!("record: {e}"));
    owner.record(record.clone()).unwrap_or_else(|e| panic!("idempotent record: {e}"));
    assert_eq!(owner.terminal_record("attempt:one").unwrap_or_else(|e| panic!("terminal: {e}")), Some(record));
    assert_eq!(owner.staged_count().unwrap_or_else(|e| panic!("count: {e}")), 1);
    assert!(owner.prepare(prepare_request()).unwrap_or_else(|e| panic!("retry: {e}")).is_some());
}

#[test]
fn final_delivered_terminal_releases_staged_turn() {
    let owner = AgentdPromptRuntimeOwner::new();
    let value = attachment();
    stage_raw(&owner, value.clone());
    let provider = digest("provider-request-final");
    owner.record_dispatch(dispatch(&value, "attempt:final", "request:final", provider)).unwrap_or_else(|e| panic!("dispatch: {e}"));
    owner.record(terminal(&value, "attempt:final", "request:final", provider, PromptRuntimeTerminalOutcomeV1::Delivered))
        .unwrap_or_else(|e| panic!("record: {e}"));
    assert_eq!(owner.staged_count().unwrap_or_else(|e| panic!("count: {e}")), 0);
}

#[test]
fn not_dispatched_retry_then_final_delivery_reopens_without_stale_stage_requirement() {
    let temp = tempfile::tempdir().unwrap_or_else(|e| panic!("temp: {e}"));
    let root = temp.path().join("prompt-runtime");
    let value = attachment();
    let first = digest("first-request");
    let second = digest("second-request");
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).unwrap_or_else(|e| panic!("open: {e}"));
        stage_raw(&owner, value.clone());
        owner.record_dispatch(dispatch(&value, "attempt:first", "request:first", first)).unwrap_or_else(|e| panic!("dispatch: {e}"));
        owner.record(terminal(&value, "attempt:first", "request:first", first, PromptRuntimeTerminalOutcomeV1::NotDispatched))
            .unwrap_or_else(|e| panic!("record: {e}"));
        owner.record_dispatch(dispatch(&value, "attempt:second", "request:second", second)).unwrap_or_else(|e| panic!("dispatch: {e}"));
        owner.record(terminal(&value, "attempt:second", "request:second", second, PromptRuntimeTerminalOutcomeV1::Delivered))
            .unwrap_or_else(|e| panic!("record: {e}"));
        assert_eq!(owner.staged_count().unwrap_or_else(|e| panic!("count: {e}")), 0);
    }
    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root).unwrap_or_else(|e| panic!("reopen: {e}"));
    assert_eq!(reopened.staged_count().unwrap_or_else(|e| panic!("count: {e}")), 0);
    assert_eq!(reopened.terminal_record("attempt:first").unwrap_or_else(|e| panic!("terminal: {e}")).map(|r| r.outcome),
        Some(PromptRuntimeTerminalOutcomeV1::NotDispatched));
    assert_eq!(reopened.terminal_record("attempt:second").unwrap_or_else(|e| panic!("terminal: {e}")).map(|r| r.outcome),
        Some(PromptRuntimeTerminalOutcomeV1::Delivered));
}

#[test]
fn dispatch_without_terminal_reopens_as_unknown_and_blocks_blind_retry() {
    let temp = tempfile::tempdir().unwrap_or_else(|e| panic!("temp: {e}"));
    let root = temp.path().join("prompt-runtime");
    let value = attachment();
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).unwrap_or_else(|e| panic!("open: {e}"));
        stage_raw(&owner, value.clone());
        owner.record_dispatch(dispatch(&value, "attempt:unknown", "request:unknown", digest("unknown-request")))
            .unwrap_or_else(|e| panic!("dispatch: {e}"));
    }
    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root).unwrap_or_else(|e| panic!("reopen: {e}"));
    assert!(reopened.prepare(prepare_request()).is_err());
    assert!(reopened.dispatch_record("attempt:unknown").unwrap_or_else(|e| panic!("dispatch: {e}")).is_some());
    assert!(reopened.terminal_record("attempt:unknown").unwrap_or_else(|e| panic!("terminal: {e}")).is_none());
}

#[test]
fn indeterminate_terminal_reopens_blocked_and_reconciles_monotonically() {
    let temp = tempfile::tempdir().unwrap_or_else(|e| panic!("temp: {e}"));
    let root = temp.path().join("prompt-runtime");
    let value = attachment();
    let provider = digest("indeterminate-request");
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).unwrap_or_else(|e| panic!("open: {e}"));
        stage_raw(&owner, value.clone());
        owner.record_dispatch(dispatch(&value, "attempt:indeterminate", "request:indeterminate", provider)).unwrap_or_else(|e| panic!("dispatch: {e}"));
        owner.record(terminal(&value, "attempt:indeterminate", "request:indeterminate", provider, PromptRuntimeTerminalOutcomeV1::Indeterminate))
            .unwrap_or_else(|e| panic!("record: {e}"));
    }
    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root).unwrap_or_else(|e| panic!("reopen: {e}"));
    assert!(reopened.prepare(prepare_request()).is_err());
    reopened.record(terminal(&value, "attempt:indeterminate", "request:indeterminate", provider, PromptRuntimeTerminalOutcomeV1::Delivered))
        .unwrap_or_else(|e| panic!("reconcile: {e}"));
    assert_eq!(reopened.staged_count().unwrap_or_else(|e| panic!("count: {e}")), 0);
    assert_eq!(reopened.terminal_record("attempt:indeterminate").unwrap_or_else(|e| panic!("terminal: {e}")).map(|r| r.outcome),
        Some(PromptRuntimeTerminalOutcomeV1::Delivered));
}

#[test]
fn post_rename_ack_loss_poison_reopens_to_dispatch_claim_not_absent() {
    let temp = tempfile::tempdir().unwrap_or_else(|e| panic!("temp: {e}"));
    let root = temp.path().join("prompt-runtime");
    let value = attachment();
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).unwrap_or_else(|e| panic!("open: {e}"));
        stage_raw(&owner, value.clone());
        owner.fail_directory_sync_after_rename_once();
        assert!(owner.record_dispatch(dispatch(&value, "attempt:ack-loss", "request:ack-loss", digest("ack-loss-request"))).is_err());
        assert!(owner.requires_reopen());
    }
    let reopened = AgentdPromptRuntimeOwner::open_state_dir(&root).unwrap_or_else(|e| panic!("reopen: {e}"));
    assert!(reopened.dispatch_record("attempt:ack-loss").unwrap_or_else(|e| panic!("dispatch: {e}")).is_some());
    assert!(reopened.prepare(prepare_request()).is_err());
}

#[test]
fn named_agentd_pipeline_stages_exact_registry_bytes_for_app_server_host() {
    let temp = tempfile::tempdir().unwrap_or_else(|e| panic!("temp: {e}"));
    let registry_root = temp.path().join("prompt-registry");
    let payload = b"Inspect evidence before mutation.";
    let (registry, tuple, _authority, _key, _wall_now) = evidence_fixture::admitted_registry(&registry_root, payload);
    drop(registry);
    let pipeline = Arc::new(AgentdPromptPipelineOwner::open_state_dirs(&registry_root, &temp.path().join("prompt-runtime"), 64)
        .unwrap_or_else(|e| panic!("pipeline: {e}")));
    let enumeration = PromptEnumerationRequestV1 {
        set_id: id("set:agentd-product"), objective_digest: digest("objective:agentd-product"), state_digest: digest("state:agentd-product"),
        generation_vector_digest: digest("generation:agentd-product"), model_tuple: tuple.clone(), now_unix_ms: 100,
        required_factor_ids: vec![id("factor:verify")], maximum_candidates: 8, selection_grammar_digest: digest("grammar:agentd-product"),
    };
    let candidates = pipeline.enumerate_candidates(enumeration.clone()).unwrap_or_else(|e| panic!("enumerate: {e}"));
    let source = evidence_fixture::FixtureSource::for_candidates(&candidates);
    let optimizer = AgentdPromptOptimizerV1::new(Arc::clone(&pipeline), source);
    let outcome = optimizer.optimize_and_stage(AgentdPromptOptimizationRequestV1 {
        thread_id: "thread:product".to_owned(), turn_id: "turn:product".to_owned(), model: "gpt-test".to_owned(), requested_deadline_ms: 10_000,
        enumeration,
        selection: PromptPortfolioRequestV1 { portfolio_id: id("portfolio:product"), graph_query_id: id("query:product"),
            token_budget: 128, maximum_selected_factors: 16, requested_valid_until_unix_ms: 10_000 },
        compilation: codex_hepta_intelligence::PromptRegistryCompilationRequestV2 {
            compilation_id: id("compilation:agentd-product"), serialization_id: id("serialization:agentd-product"), attachment_id: id("attachment:agentd-product"),
            registry_model_tuple: tuple.clone(), context_model_profile: ContextModelProfileV2 {
                model_digest: tuple.model_digest, provider_id_digest: digest("provider:agentd-product"), provider_model_digest: tuple.model_digest,
                tokenizer_digest: tuple.tokenizer_digest, serializer_digest: digest("serializer:agentd-product"), template_digest: tuple.template_digest,
                tool_schema_digest: tuple.tool_schema_digest, maximum_context_tokens: 128,
            },
            now_unix_ms: 100, token_budget: 128, truncation_policy_digest: digest("truncation:agentd-product"),
        },
    }).unwrap_or_else(|e| panic!("optimize and stage: {e}"));
    match outcome {
        AgentdPromptOptimizationOutcomeV1::Staged { portfolio, disposition } => {
            assert_eq!(disposition, PromptRuntimeStageDisposition::Inserted);
            assert_eq!(portfolio.receipt.factor_ids, vec![id("factor:verify")]);
            assert_eq!(portfolio.receipt.valid_until_unix_ms, 9_000);
        }
        AgentdPromptOptimizationOutcomeV1::NoIntervention(_) => panic!("positive fixture must stage"),
    }
    let runtime = pipeline.runtime_owner();
    let staged = runtime.prepare(PromptRuntimePrepareRequest {
        thread_id: "thread:product".to_owned(), turn_id: "turn:product".to_owned(), model_context_window: Some(128),
    }).unwrap_or_else(|e| panic!("prepare: {e}")).unwrap_or_else(|| panic!("missing attachment"));
    assert_eq!(staged.developer_fragments.len(), 1);
    assert_eq!(staged.developer_fragments[0].text.as_bytes(), payload);
}

#[test]
fn owner_remains_send_sync_with_fault_injection() {
    fn assert_send_sync<T: Send + Sync>() {}
    assert_send_sync::<super::AgentdPromptRuntimeOwner>();
}
