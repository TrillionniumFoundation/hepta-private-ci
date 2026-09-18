use std::sync::Arc;

use codex_extension_api::ConversationHistory;
use codex_extension_api::NoopTurnItemEmitter;
use codex_extension_api::ToolCallSource;
use codex_extension_api::ToolPayload;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveUnavailableReason;
use codex_hepta_memory::MemoryRevisionRecord;
use codex_hepta_paths::HeptaFleetRoot;
use codex_utils_output_truncation::TruncationPolicy;
use tempfile::TempDir;

use super::*;

const THREAD_ID: &str = "00000000-0000-4000-8000-000000000201";
const TURN_ID: &str = "turn-cognitive-1";

async fn test_runtime(directive: &str) -> (TempDir, Arc<CognitiveStore>, ExactDirectiveWitness) {
    let temp = tempfile::tempdir().expect("tempdir");
    let fleet_root = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet_root).expect("fleet root");
    let agent_id = AgentId::parse("00000000-0000-4000-8000-000000000211").expect("agent id");
    let layout = HeptaFleetRoot::parse(fleet_root)
        .expect("fleet")
        .layout()
        .agent(&agent_id);
    let workspace = temp.path().join("workspace");
    std::fs::create_dir_all(&workspace).expect("workspace");
    let store = Arc::new(
        CognitiveStore::open(&layout)
            .await
            .expect("cognitive store"),
    );
    let witness = ExactDirectiveWitness {
        turn_id: TURN_ID.to_string(),
        workspace_sha256: crate::framing::workspace_digest(&workspace),
        workspace,
        content_sha256: codex_hepta_contracts::Sha256Digest::for_bytes(directive.as_bytes()),
        content_bytes: directive.len(),
        byte_exact_verification_allowed: true,
    };
    (temp, store, witness)
}

fn tool(
    store: Arc<CognitiveStore>,
    witness: ExactDirectiveWitness,
    operation: CognitiveToolOperation,
) -> CognitiveTool {
    CognitiveTool {
        runtime: CognitiveRuntime::Available(store),
        thread_id: THREAD_ID.to_string(),
        witness,
        operation,
    }
}

fn call(operation: CognitiveToolOperation, call_id: &str, arguments: Value) -> ToolCall {
    ToolCall {
        turn_id: TURN_ID.to_string(),
        call_id: call_id.to_string(),
        tool_name: ToolName::namespaced(COGNITIVE_NAMESPACE, operation.name()),
        model: "gpt-test".to_string(),
        codex_turn_metadata: None,
        truncation_policy: TruncationPolicy::Bytes(16 * 1024),
        source: ToolCallSource::Direct,
        conversation_history: ConversationHistory::default(),
        turn_item_emitter: Arc::new(NoopTurnItemEmitter),
        environments: Vec::new(),
        payload: ToolPayload::Function {
            arguments: arguments.to_string(),
        },
    }
}

fn workspace_access(store: &CognitiveStore, witness: &ExactDirectiveWitness) -> CognitiveAccess {
    CognitiveAccess::workspace_private(
        store.owner_agent_id().clone(),
        witness.workspace_sha256.clone(),
    )
}

fn workspace_scope(witness: &ExactDirectiveWitness) -> CognitiveScope {
    CognitiveScope::WorkspacePrivate {
        workspace_sha256: witness.workspace_sha256.clone(),
    }
}

async fn seed_verified_memory(
    store: &CognitiveStore,
    witness: &ExactDirectiveWitness,
    stable_key: &str,
    content: &str,
) -> MemoryRevisionRecord {
    let now = tool_now().expect("time");
    let access = workspace_access(store, witness);
    let scope = workspace_scope(witness);
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: format!("seed-{stable_key}"),
                content: content.as_bytes().to_vec(),
                observed_at_unix_seconds: now,
            },
        )
        .await
        .expect("source");
    store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: stable_key.to_string(),
                revision: MemoryRevisionDraft {
                    scope,
                    content: content.to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: now,
                    valid_to_unix_seconds: None,
                    citations: vec![citation],
                },
            },
        )
        .await
        .expect("memory")
}

async fn assert_source_event_was_not_written(
    store: &CognitiveStore,
    witness: &ExactDirectiveWitness,
    cognitive_tool: &CognitiveTool,
    rejected_call: &ToolCall,
    operation: CognitiveToolOperation,
    source_kind: LedgerSourceKind,
) {
    let access = workspace_access(store, witness);
    store
        .append_source(
            &access,
            &SourceDraft {
                scope: workspace_scope(witness),
                kind: source_kind,
                event_key: cognitive_tool.event_key(rejected_call, operation),
                content: b"probe proves the rejected call wrote no source".to_vec(),
                observed_at_unix_seconds: tool_now().expect("time"),
            },
        )
        .await
        .expect("same event key remains unused after rejection");
}

fn assert_explicit_directive_error(error: FunctionCallError) {
    let FunctionCallError::RespondToModel(error) = error else {
        panic!("expected model-visible typed error");
    };
    assert!(error.contains("hepta_cognitive_explicit_directive_required"));
}

fn tool_error(
    result: Result<Box<dyn ToolOutput>, FunctionCallError>,
    context: &str,
) -> FunctionCallError {
    match result {
        Ok(_) => panic!("{context}"),
        Err(error) => error,
    }
}

#[tokio::test]
async fn non_exact_correct_and_forget_do_not_write_source_or_advance_verified_head() {
    let (_temp, store, witness) = test_runtime("exact user directive").await;
    let original = seed_verified_memory(&store, &witness, "durable-fact", "original fact").await;
    let access = workspace_access(&store, &witness);

    let correct_tool = tool(
        store.clone(),
        witness.clone(),
        CognitiveToolOperation::Correct,
    );
    let correct_call = call(
        CognitiveToolOperation::Correct,
        "call-non-exact-correct",
        json!({
            "memory_id": original.id.memory_id.as_str(),
            "expected_revision": 1,
            "content": "model-generated correction"
        }),
    );
    assert_explicit_directive_error(tool_error(
        correct_tool.correct(&store, &correct_call).await,
        "non-exact correction must be rejected",
    ));
    assert_source_event_was_not_written(
        &store,
        &witness,
        &correct_tool,
        &correct_call,
        CognitiveToolOperation::Correct,
        LedgerSourceKind::ExplicitMemoryDirective,
    )
    .await;

    let forget_tool = tool(
        store.clone(),
        witness.clone(),
        CognitiveToolOperation::Forget,
    );
    let forget_call = call(
        CognitiveToolOperation::Forget,
        "call-non-exact-forget",
        json!({
            "memory_id": original.id.memory_id.as_str(),
            "expected_revision": 1,
            "reason": "model-generated forget"
        }),
    );
    assert_explicit_directive_error(tool_error(
        forget_tool.forget(&store, &forget_call).await,
        "non-exact forget must be rejected",
    ));
    assert_source_event_was_not_written(
        &store,
        &witness,
        &forget_tool,
        &forget_call,
        CognitiveToolOperation::Forget,
        LedgerSourceKind::ExplicitMemoryDirective,
    )
    .await;

    let head = store
        .read_memory_head(&access, &original.id.memory_id)
        .await
        .expect("head");
    assert_eq!(head.id.revision, 1);
    assert_eq!(head.content, "original fact");
    assert_eq!(head.verification, MemoryVerification::Verified);
    assert_eq!(head.lifecycle, MemoryLifecycleState::Active);
}

#[tokio::test]
async fn non_exact_remember_is_provisional_uses_honest_source_and_never_retrieves() {
    let (_temp, store, witness) = test_runtime("remember the exact user directive").await;
    let remember_tool = tool(
        store.clone(),
        witness.clone(),
        CognitiveToolOperation::Remember,
    );
    let remember_call = call(
        CognitiveToolOperation::Remember,
        "call-provisional-remember",
        json!({
            "stable_key": "inferred-preference",
            "content": "model inferred preference"
        }),
    );
    let output = remember_tool
        .remember(&store, &remember_call)
        .await
        .expect("provisional remember");
    let value = output.code_mode_result(&remember_call.payload);
    assert_eq!(value["schema_version"], 2);
    assert_eq!(value["memory"]["verification"], "provisional");
    let memory_id = StableMemoryId::parse(
        value["memory"]["memory_id"]
            .as_str()
            .expect("memory id")
            .to_string(),
    )
    .expect("stable memory id");
    let access = workspace_access(&store, &witness);
    let explanation = store
        .explain_memory_head(&access, &memory_id)
        .await
        .expect("explanation");
    assert_eq!(
        explanation.memory.verification,
        MemoryVerification::Provisional
    );
    assert_eq!(explanation.citations.len(), 1);
    assert_eq!(
        explanation.citations[0].kind,
        LedgerSourceKind::AssistantConclusion
    );
    let batch = store
        .retrieve_memory_candidates(
            &access,
            &RetrievalRequest::new("model inferred preference", tool_now().expect("time")),
        )
        .await
        .expect("retrieval");
    assert!(batch.candidates.is_empty());
}

#[tokio::test]
async fn exact_remember_and_correct_are_verified_and_forget_is_cas_tombstone() {
    let (_temp, store, remember_witness) = test_runtime("exact remembered fact").await;
    let remember_tool = tool(
        store.clone(),
        remember_witness.clone(),
        CognitiveToolOperation::Remember,
    );
    let remember_call = call(
        CognitiveToolOperation::Remember,
        "call-exact-remember",
        json!({
            "stable_key": "exact-fact",
            "content": "exact remembered fact",
            "kg": {
                "entities": [
                    { "key": "Hepta", "entity_type": "project", "label": "Hepta Project" },
                    { "key": "Rust", "entity_type": "language", "label": "Rust" }
                ],
                "relations": [
                    {
                        "key": "uses-rust",
                        "from_entity_key": "Hepta",
                        "to_entity_key": "Rust",
                        "relation": "uses"
                    }
                ]
            }
        }),
    );
    let output = remember_tool
        .remember(&store, &remember_call)
        .await
        .expect("verified remember");
    let value = output.code_mode_result(&remember_call.payload);
    assert_eq!(value["schema_version"], 2);
    assert_eq!(value["memory"]["verification"], "verified");
    assert_eq!(value["projection"]["entity_count"], 2);
    assert_eq!(value["projection"]["relation_count"], 1);
    assert_eq!(value["projection"]["fact_count"], 3);
    assert!(!value.to_string().contains("Hepta Project"));
    assert!(value["projection"]["generation"].as_u64().is_some());
    for digest in ["fact_set_sha256", "input_heads_sha256", "output_sha256"] {
        assert_eq!(
            value["projection"][digest]
                .as_str()
                .expect("projection digest")
                .len(),
            64
        );
    }
    let memory_id = StableMemoryId::parse(value["memory"]["memory_id"].as_str().expect("id"))
        .expect("memory id");

    let correction = "exact corrected fact";
    let correct_witness = ExactDirectiveWitness {
        content_sha256: codex_hepta_contracts::Sha256Digest::for_bytes(correction.as_bytes()),
        content_bytes: correction.len(),
        ..remember_witness.clone()
    };
    let correct_tool = tool(
        store.clone(),
        correct_witness,
        CognitiveToolOperation::Correct,
    );
    let correct_call = call(
        CognitiveToolOperation::Correct,
        "call-exact-correct",
        json!({
            "memory_id": memory_id.as_str(),
            "expected_revision": 1,
            "content": correction
        }),
    );
    let output = correct_tool
        .correct(&store, &correct_call)
        .await
        .expect("verified correction");
    let value = output.code_mode_result(&correct_call.payload);
    assert_eq!(value["memory"]["revision"], 2);
    assert_eq!(value["memory"]["verification"], "verified");

    let reason = "exact user-directed forget";
    let forget_witness = ExactDirectiveWitness {
        content_sha256: codex_hepta_contracts::Sha256Digest::for_bytes(reason.as_bytes()),
        content_bytes: reason.len(),
        ..remember_witness.clone()
    };
    let forget_tool = tool(
        store.clone(),
        forget_witness,
        CognitiveToolOperation::Forget,
    );
    let forget_call = call(
        CognitiveToolOperation::Forget,
        "call-exact-forget",
        json!({
            "memory_id": memory_id.as_str(),
            "expected_revision": 2,
            "reason": reason
        }),
    );
    let output = forget_tool
        .forget(&store, &forget_call)
        .await
        .expect("tombstone");
    let value = output.code_mode_result(&forget_call.payload);
    assert_eq!(value["memory"]["revision"], 3);
    assert_eq!(value["memory"]["lifecycle"]["state"], "tombstoned");
    assert_eq!(value["projection"]["entity_count"], 0);
    assert_eq!(value["projection"]["relation_count"], 0);
    assert_eq!(value["projection"]["fact_count"], 0);
}

#[tokio::test]
async fn secret_like_remember_is_rejected_before_source_persistence() {
    let (_temp, store, witness) = test_runtime("unrelated directive").await;
    let remember_tool = tool(
        store.clone(),
        witness.clone(),
        CognitiveToolOperation::Remember,
    );
    let remember_call = call(
        CognitiveToolOperation::Remember,
        "call-secret-remember",
        json!({
            "stable_key": "credential",
            "content": "AKIAIOSFODNN7EXAMPLE"
        }),
    );
    let FunctionCallError::RespondToModel(error) = tool_error(
        remember_tool.remember(&store, &remember_call).await,
        "secret must be rejected",
    ) else {
        panic!("typed model error");
    };
    assert!(error.contains("hepta_cognitive_secret_like_content"));
    assert!(!error.contains("AKIAIOSFODNN7EXAMPLE"));
    assert_source_event_was_not_written(
        &store,
        &witness,
        &remember_tool,
        &remember_call,
        CognitiveToolOperation::Remember,
        LedgerSourceKind::AssistantConclusion,
    )
    .await;
}

#[tokio::test]
async fn provisional_structured_facts_fail_closed_before_source_persistence() {
    let (_temp, store, witness) = test_runtime("different exact user directive").await;
    let remember_tool = tool(
        store.clone(),
        witness.clone(),
        CognitiveToolOperation::Remember,
    );
    let remember_call = call(
        CognitiveToolOperation::Remember,
        "call-provisional-kg",
        json!({
            "stable_key": "inferred-project",
            "content": "model inferred project",
            "kg": {
                "entities": [
                    { "key": "hepta", "entity_type": "project", "label": "Hepta" }
                ]
            }
        }),
    );
    let FunctionCallError::RespondToModel(error) = tool_error(
        remember_tool.remember(&store, &remember_call).await,
        "provisional structured facts must be rejected",
    ) else {
        panic!("typed model error");
    };
    assert!(error.contains("hepta_cognitive_kg_provisional_facts"));
    assert_source_event_was_not_written(
        &store,
        &witness,
        &remember_tool,
        &remember_call,
        CognitiveToolOperation::Remember,
        LedgerSourceKind::AssistantConclusion,
    )
    .await;
}

#[tokio::test]
async fn stale_correction_cas_leaves_no_source_event() {
    let directive = "exact corrected fact";
    let (_temp, store, witness) = test_runtime(directive).await;
    let original = seed_verified_memory(&store, &witness, "cas-fact", "original fact").await;
    let correct_tool = tool(
        store.clone(),
        witness.clone(),
        CognitiveToolOperation::Correct,
    );
    let correct_call = call(
        CognitiveToolOperation::Correct,
        "call-stale-correct",
        json!({
            "memory_id": original.id.memory_id.as_str(),
            "expected_revision": 99,
            "content": directive
        }),
    );

    let FunctionCallError::RespondToModel(error) = tool_error(
        correct_tool.correct(&store, &correct_call).await,
        "stale correction must fail",
    ) else {
        panic!("typed model error");
    };
    assert!(error.contains("hepta_cognitive_conflict"));
    assert_source_event_was_not_written(
        &store,
        &witness,
        &correct_tool,
        &correct_call,
        CognitiveToolOperation::Correct,
        LedgerSourceKind::ExplicitMemoryDirective,
    )
    .await;

    let forget_tool = tool(
        store.clone(),
        witness.clone(),
        CognitiveToolOperation::Forget,
    );
    let forget_call = call(
        CognitiveToolOperation::Forget,
        "call-stale-forget",
        json!({
            "memory_id": original.id.memory_id.as_str(),
            "expected_revision": 99,
            "reason": directive
        }),
    );
    let FunctionCallError::RespondToModel(error) = tool_error(
        forget_tool.forget(&store, &forget_call).await,
        "stale forget must fail",
    ) else {
        panic!("typed model error");
    };
    assert!(error.contains("hepta_cognitive_conflict"));
    assert_source_event_was_not_written(
        &store,
        &witness,
        &forget_tool,
        &forget_call,
        CognitiveToolOperation::Forget,
        LedgerSourceKind::ExplicitMemoryDirective,
    )
    .await;
}

#[tokio::test]
async fn deferred_tools_are_visible_before_turn_input_and_fail_closed_without_exact_witness() {
    let (_temp, store, witness) = test_runtime("directive").await;
    let witnesses = Arc::new(CognitiveTurnWitnesses::default());
    let tools = deferred_cognitive_tools(
        CognitiveRuntime::Available(store),
        THREAD_ID.to_string(),
        TURN_ID.to_string(),
        witnesses.clone(),
        true,
    );
    assert_eq!(tools.len(), 5);

    let missing = tool_error(
        tools[1]
            .handle(call(
                CognitiveToolOperation::Recall,
                "call-missing-witness",
                json!({ "query": "directive" }),
            ))
            .await,
        "missing witness must fail closed",
    );
    let FunctionCallError::RespondToModel(missing) = missing else {
        panic!("missing witness must be model visible");
    };
    assert!(missing.contains("hepta_cognitive_witness_unavailable"));

    let mut other_turn = witness.clone();
    other_turn.turn_id = "turn-cognitive-other".to_string();
    witnesses.insert(other_turn);
    let still_missing = tool_error(
        tools[1]
            .handle(call(
                CognitiveToolOperation::Recall,
                "call-wrong-witness",
                json!({ "query": "directive" }),
            ))
            .await,
        "a different turn witness must not authorize this executor",
    );
    let FunctionCallError::RespondToModel(still_missing) = still_missing else {
        panic!("wrong witness must be model visible");
    };
    assert!(still_missing.contains("hepta_cognitive_witness_unavailable"));

    witnesses.insert(witness);
    let mut wrong_turn_call = call(
        CognitiveToolOperation::Recall,
        "call-wrong-turn",
        json!({ "query": "directive" }),
    );
    wrong_turn_call.turn_id = "turn-cognitive-other".to_string();
    let wrong_turn = tool_error(
        tools[1].handle(wrong_turn_call).await,
        "a different turn must not use the planned executor",
    );
    let FunctionCallError::RespondToModel(wrong_turn) = wrong_turn else {
        panic!("wrong turn must be model visible");
    };
    assert!(wrong_turn.contains("hepta_cognitive_scope_mismatch"));
}

#[tokio::test]
async fn conflicting_same_turn_witness_replay_is_permanently_poisoned() {
    let (_temp, _store, witness) = test_runtime("directive").await;
    let witnesses = CognitiveTurnWitnesses::default();
    witnesses.insert(witness.clone());
    assert_eq!(witnesses.get(TURN_ID), Some(witness.clone()));
    witnesses.insert(witness.clone());
    assert_eq!(witnesses.get(TURN_ID), Some(witness.clone()));

    let mut conflicting = witness.clone();
    conflicting.content_sha256 = codex_hepta_contracts::Sha256Digest::for_bytes(b"drift");
    witnesses.insert(conflicting);
    assert!(witnesses.get(TURN_ID).is_none());

    witnesses.insert(witness);
    assert!(witnesses.get(TURN_ID).is_none());
}

#[tokio::test]
async fn unavailable_deferred_runtime_keeps_only_read_tools_visible_without_a_witness() {
    let (_temp, _store, _witness) = test_runtime("directive").await;
    let tools = deferred_cognitive_tools(
        CognitiveRuntime::Unavailable(CognitiveUnavailableReason::StorageUnavailable),
        THREAD_ID.to_string(),
        TURN_ID.to_string(),
        Arc::new(CognitiveTurnWitnesses::default()),
        false,
    );
    assert_eq!(tools.len(), 2);
    assert_eq!(
        tools
            .iter()
            .map(|tool| {
                let name = tool.tool_name();
                (name.namespace, name.name)
            })
            .collect::<Vec<_>>(),
        vec![
            (Some("hepta_cognitive".to_string()), "recall".to_string()),
            (Some("hepta_cognitive".to_string()), "explain".to_string()),
        ]
    );
    let error = tool_error(
        tools[0]
            .handle(call(
                CognitiveToolOperation::Recall,
                "call-unavailable",
                json!({}),
            ))
            .await,
        "unavailable runtime must return an error",
    );
    let FunctionCallError::RespondToModel(error) = error else {
        panic!("unavailable must be model visible");
    };
    assert!(error.contains("hepta_cognitive_unavailable"));
    assert!(error.contains("storage_unavailable"));
    assert!(!error.contains('/') && !error.contains("sqlite"));
}

#[test]
fn all_tool_specs_share_the_namespace_and_have_strict_object_shapes() {
    for operation in [
        CognitiveToolOperation::Remember,
        CognitiveToolOperation::Recall,
        CognitiveToolOperation::Correct,
        CognitiveToolOperation::Forget,
        CognitiveToolOperation::Explain,
    ] {
        let ToolSpec::Namespace(namespace) = cognitive_tool_spec(operation) else {
            panic!("cognitive tools must use one namespace");
        };
        assert_eq!(namespace.name, COGNITIVE_NAMESPACE);
        assert_eq!(namespace.tools.len(), 1);
        let serialized = serde_json::to_value(namespace).expect("serialize namespace");
        assert_eq!(
            serialized["tools"][0]["parameters"]["additionalProperties"],
            false
        );
    }
}

#[test]
fn structured_kg_tool_schema_is_bounded_and_denies_unknown_nested_fields() {
    for operation in [
        CognitiveToolOperation::Remember,
        CognitiveToolOperation::Correct,
    ] {
        let schema = input_schema(operation);
        let kg = &schema["properties"]["kg"];
        assert_eq!(kg["additionalProperties"], false);
        assert_eq!(
            kg["properties"]["entities"]["maxItems"],
            MAX_STRUCTURED_KG_ENTITIES
        );
        assert_eq!(
            kg["properties"]["relations"]["maxItems"],
            MAX_STRUCTURED_KG_RELATIONS
        );
        assert_eq!(
            kg["properties"]["entities"]["items"]["additionalProperties"],
            false
        );
        assert_eq!(
            kg["properties"]["relations"]["items"]["additionalProperties"],
            false
        );
    }
}

#[test]
fn bounded_explain_shape_never_exceeds_the_hard_output_limit() {
    let citations = (0..MAX_EXPLAIN_CITATIONS)
        .map(|index| {
            json!({
                "source_id": format!("source:v1:{:064x}", index),
                "content": "x".repeat(MAX_CITATION_CONTENT_BYTES),
            })
        })
        .collect::<Vec<_>>();
    let value = json!({
        "schema_version": TOOL_OUTPUT_SCHEMA_VERSION,
        "memory": { "content": "x".repeat(MAX_EXPLAIN_MEMORY_BYTES) },
        "citations": citations,
    });
    assert!(serde_json::to_vec(&value).expect("encode").len() < MAX_EXPLAIN_OUTPUT_BYTES);
    assert!(json_output(value, MAX_EXPLAIN_OUTPUT_BYTES).is_ok());
}

#[test]
fn bounded_utf8_never_splits_a_scalar() {
    assert_eq!(bounded_text("abc🦀", 5), "abc");
    assert_eq!(bounded_bytes("🦀abc".as_bytes(), 4), "🦀");
}

#[test]
fn secret_rejection_is_typed_and_stable() {
    let FunctionCallError::RespondToModel(error) =
        reject_secret("content", b"api_key=do-not-store").expect_err("secret rejected")
    else {
        panic!("secret rejection must be model-visible");
    };
    assert!(error.contains("hepta_cognitive_secret_like_content"));
    assert!(!error.contains("do-not-store"));
}
