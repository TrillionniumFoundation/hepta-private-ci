use codex_protocol::ThreadId;
use pretty_assertions::assert_eq;
use serde_json::json;

use super::*;

fn fixture() -> Result<(NativeTurnAnchorV1, TurnState)> {
    let anchor: NativeTurnAnchorV1 = serde_json::from_value(json!({
        "checkpoint": {"thread_id": ThreadId::new(), "turn_id":"turn:original",
            "operation_id":"operation:original", "generation":7, "lease_id":"lease:original"},
        "recovery": {"turn_id":"turn:original", "generation":3,
            "fingerprint_sha256":Digest32::of_bytes(b"semantic request").to_string(),
            "history_boundary":{"item_count":1,"prefix_sha256":Digest32::of_bytes(b"model history").to_string()},
            "replay":{"history_boundary":{"item_count":1,"prefix_sha256":Digest32::of_bytes(b"model history").to_string()},
                "turn_context_sha256":Digest32::of_bytes(b"turn context").to_string(),
                "start":{},"environments":[]}},
        "queue":null
    })).context("original fixture anchor")?;
    let state = TurnState::new(anchor.turn_binding().context("binding")?, "original input".to_owned());
    Ok((anchor, state))
}

fn tool(binding: &TurnBinding) -> Result<PendingTool> {
    let call = ToolCall { call_id: "call:original".to_owned(), name: "probe".to_owned(), arguments: br#"{"task":"lines"}"#.to_vec() };
    let arguments = br#"{"host":"host:original","executable":"/bin/probe","idempotency_key":"tool:original"}"#.to_vec();
    let digest = Digest32::of_bytes(&arguments);
    Ok(PendingTool {
        call: call.clone(),
        intent: RuntimeToolIntentV1 {
            cell: CellExecutionIntentV1 {
                operation_id: StableId::new("tool:original").context("operation")?,
                cell_id: StableId::new("cell:original").context("cell")?,
                organ_id: StableId::new("organ:original").context("organ")?,
                generation: binding.generation,
                kind: ExecutionIntentKindV1::RuntimeTool,
                codex_binding: None,
                input_digest: Digest32::of_bytes(&call.arguments),
                final_payload: FinalPayloadDigestV1 {
                    scope_id: StableId::new("organ:original").context("scope")?, generation: binding.generation,
                    payload_kind: StableId::new("hepta.process.start.json.v1").context("kind")?, digest,
                },
                deadline_ms: 1234567,
            },
            tool_id: StableId::new("process_start").context("tool")?, arguments_digest: digest,
            idempotency_key: StableId::new("tool:original").context("key")?,
            host_scope: StableId::new("host:original").context("host")?,
        },
        arguments, submission_attempted: true, cancel_requested: true,
    })
}

#[test]
fn uncertain_model_roundtrip_keeps_exact_original_bytes_and_response() {
    let (anchor, mut state) = fixture().expect("original checkpoint fixture");
    let body = b"{ \"input\" : [\"original\\nrequest\"], \"stream\":true }".to_vec();
    state.model_calls = 2;
    state.pending_model = Some(ModelRequest { operation_id: "model:original".to_owned(), body: body.clone() });
    state.provider_response_id = Some("resp_original".to_owned());
    state.cancelled = true;
    state.last_error = Some("observation interrupted".to_owned());
    state.model_usage = vec![json!({"input_tokens":17,"output_tokens":5})];
    let bytes = encode(&anchor, &state).expect("encode pending model");
    let (restored_anchor, restored) = decode(&bytes, &anchor.checkpoint).expect("restore original model");
    assert_eq!(restored_anchor, anchor);
    assert_eq!(encode(&restored_anchor, &restored).expect("re-encode"), bytes);
    let request = restored.pending_model.expect("pending retained");
    assert_eq!((request.operation_id, request.body, restored.provider_response_id), ("model:original".to_owned(), body, Some("resp_original".to_owned())));
    assert!(restored.cancelled);
}

#[test]
fn pending_runtime_roundtrip_keeps_full_intent_and_cancellation() {
    let (anchor, mut state) = fixture().expect("original checkpoint fixture");
    let pending = tool(&state.binding).expect("original tool fixture");
    state.model_calls = 2;
    state.tool_calls = 2;
    state.completed_call_ids = vec!["call:finished".to_owned()];
    state.pending_tool = Some(pending.clone());
    state.queued_tools = vec![ToolCall { call_id: "call:next".to_owned(), name: "probe".to_owned(), arguments: b"{}".to_vec() }];
    let bytes = encode(&anchor, &state).expect("encode tool");
    let (_, restored) = decode(&bytes, &anchor.checkpoint).expect("restore original tool");
    assert_eq!(encode(&anchor, &restored).expect("re-encode"), bytes);
    let actual = restored.pending_tool.expect("pending retained");
    assert_eq!((actual.call, actual.intent, actual.arguments, actual.submission_attempted, actual.cancel_requested),
        (pending.call, pending.intent, pending.arguments, true, true));
}

#[test]
fn changed_original_binding_and_incomplete_replay_are_rejected() {
    let (anchor, state) = fixture().expect("original checkpoint fixture");
    let bytes = encode(&anchor, &state).expect("encode");
    let mut other = anchor.checkpoint.clone();
    other.lease_id = "lease:successor".to_owned();
    assert!(decode(&bytes, &other).is_err());
    let mut incomplete = anchor;
    incomplete.recovery.replay = None;
    assert!(encode(&incomplete, &state).is_err());
}

#[test]
fn codec_rejects_unknown_authority_fields_in_imported_history() {
    let (anchor, state) = fixture().expect("original checkpoint fixture");
    let mut value: Value = serde_json::from_slice(&encode(&anchor, &state).expect("encode")).expect("JSON");
    value["anchor"]["recovery"]["allow_dispatch"] = json!(true);
    assert!(decode(&serde_json::to_vec(&value).expect("JSON"), &anchor.checkpoint).is_err());
}

#[test]
fn altered_tool_target_or_native_context_cannot_restore() {
    let (anchor, mut state) = fixture().expect("original checkpoint fixture");
    state.tool_calls = 1;
    state.pending_tool = Some(tool(&state.binding).expect("original tool fixture"));
    let value: Value = serde_json::from_slice(&encode(&anchor, &state).expect("encode")).expect("JSON");
    let mut changed_target = value.clone();
    changed_target["state"]["pending_tool"]["intent"]["host_scope"] = json!("host:other");
    assert!(decode(&serde_json::to_vec(&changed_target).expect("JSON"), &anchor.checkpoint).is_err());
    let mut changed_context = value;
    changed_context["state"]["context"][0]["content"] = json!("replaced input");
    assert!(decode(&serde_json::to_vec(&changed_context).expect("JSON"), &anchor.checkpoint).is_err());
}

#[test]
fn reused_tool_identity_and_overlapping_admissions_are_rejected() {
    let (anchor, mut state) = fixture().expect("original checkpoint fixture");
    state.tool_calls = 2;
    state.pending_tool = Some(tool(&state.binding).expect("original tool fixture"));
    state.completed_call_ids = vec!["call:original".to_owned()];
    assert!(encode(&anchor, &state).is_err());
    state.completed_call_ids.clear();
    state.model_calls = 1;
    state.pending_model = Some(ModelRequest { operation_id:"model:other".to_owned(), body:b"{}".to_vec() });
    assert!(encode(&anchor, &state).is_err());
}

#[test]
fn oversized_snapshot_is_rejected_before_storage() {
    let (anchor, mut state) = fixture().expect("original checkpoint fixture");
    state.context = vec![json!("x".repeat(MAX_CHECKPOINT_BYTES))];
    assert!(encode(&anchor, &state).is_err());
    assert!(decode(&vec![b' '; MAX_CHECKPOINT_BYTES + 1], &anchor.checkpoint).is_err());
}

#[test]
fn unresolved_operations_and_submission_flags_cannot_be_replaced() {
    let (_, mut model) = fixture().expect("original checkpoint fixture");
    model.model_calls = 1;
    model.pending_model = Some(ModelRequest { operation_id:"model:original".to_owned(), body:b"{}".to_vec() });
    let mut replaced = model.clone();
    replaced.pending_model.as_mut().expect("pending").operation_id = "model:replacement".to_owned();
    assert!(validate_transition(&model, &replaced).is_err());
    let (_, mut original) = fixture().expect("original checkpoint fixture");
    original.tool_calls = 1;
    original.pending_tool = Some(tool(&original.binding).expect("original tool fixture"));
    let mut reset = original.clone();
    reset.pending_tool.as_mut().expect("pending").submission_attempted = false;
    assert!(validate_transition(&original, &reset).is_err());
}

#[test]
fn admitted_model_can_record_response_then_settle_without_replacing_context() {
    let (_, initial) = fixture().expect("original checkpoint fixture");
    let mut admitted = initial.clone();
    admitted.model_calls = 1;
    admitted.pending_model = Some(ModelRequest { operation_id:"model:original".to_owned(), body:b"{}".to_vec() });
    validate_transition(&initial, &admitted).expect("durable admission");
    let mut observed = admitted.clone();
    observed.provider_response_id = Some("resp_original".to_owned());
    validate_transition(&admitted, &observed).expect("same provider operation");
    let mut settled = observed.clone();
    settled.pending_model = None;
    settled.context.push(json!({"type":"message","role":"assistant","content":[{"type":"output_text","text":"done"}]}));
    settled.final_answer = Some("done".to_owned());
    validate_transition(&observed, &settled).expect("terminal observation");
    assert!(validate_transition(&settled, &initial).is_err());
}

#[test]
fn original_coordinator_and_execution_correlation_roundtrip_together() {
    let (mut anchor, state) = fixture().expect("original checkpoint fixture");
    let digest = Digest32::of_bytes(b"original frozen owner input").to_string();
    anchor.run = Some(crate::RunRecovery {
        snapshot: crate::RunSnapshot {
            run_id: anchor.checkpoint.operation_id.clone(),
            request_digest: digest.clone(),
            objective_digest: digest.clone(),
            body_digest: digest.clone(),
            artifact_set_digest: digest.clone(),
            authority_epoch: 13,
            generation: anchor.checkpoint.generation,
            fence_digest: Digest32::of_bytes(b"original fence").to_string(),
            deadline_ms: 123456789,
        },
        revision: 3,
        context_digest: Digest32::of_bytes(b"original compiled context").to_string(),
        compilation_receipt_digest: digest,
        cancel_reason: Some("original observation interrupted".to_owned()),
    });
    anchor.execution = Some(NativeExecutionBindingV1 {
        cell_id: "cell:original".to_owned(),
        organ_id: "organ:original".to_owned(),
        final_scope_id: "scope:original".to_owned(),
        // Policy generation is independent of execution/coordinator generation.
        policy_generation: 19,
    });
    let bytes = encode(&anchor, &state).expect("original correlation");
    let (actual, restored) = decode(&bytes, &anchor.checkpoint).expect("preserve original owner fields");
    assert_eq!(actual, anchor);
    assert_eq!(encode(&actual, &restored).expect("re-encode"), bytes);

    let mut wrong = anchor.clone();
    wrong.run.as_mut().expect("run").snapshot.run_id = "operation:replacement".to_owned();
    assert!(encode(&wrong, &state).is_err());
    wrong = anchor.clone();
    wrong.run.as_mut().expect("run").snapshot.generation += 1;
    assert!(encode(&wrong, &state).is_err());
    wrong = anchor.clone();
    wrong.execution.as_mut().expect("execution").policy_generation = 0;
    assert!(encode(&wrong, &state).is_err());
    wrong = anchor.clone();
    wrong.execution = None;
    assert!(encode(&wrong, &state).is_err());
    wrong = anchor;
    wrong.run = None;
    assert!(encode(&wrong, &state).is_err());
}

#[test]
fn old_storage_only_snapshot_remains_readable_without_synthesized_run() {
    let (anchor, state) = fixture().expect("original checkpoint fixture");
    let bytes = encode(&anchor, &state).expect("legacy storage snapshot");
    let wire: Value = serde_json::from_slice(&bytes).expect("wire");
    assert!(wire["anchor"].get("run").is_none());
    assert!(wire["anchor"].get("execution").is_none());
    let (restored, _) = decode(&bytes, &anchor.checkpoint).expect("old storage remains readable");
    assert_eq!((restored.run, restored.execution), (None, None));
}
