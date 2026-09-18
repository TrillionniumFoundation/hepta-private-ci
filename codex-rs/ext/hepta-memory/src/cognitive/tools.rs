use std::sync::Arc;

use codex_extension_api::FunctionCallError;
use codex_extension_api::JsonToolOutput;
use codex_extension_api::ResponsesApiTool;
use codex_extension_api::ToolCall;
use codex_extension_api::ToolExecutor;
use codex_extension_api::ToolName;
use codex_extension_api::ToolOutput;
use codex_extension_api::ToolSpec;
use codex_extension_api::parse_tool_input_schema;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveRuntime;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::CognitiveWriteReceipt;
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_memory::SourceDraft;
use codex_hepta_memory::StableMemoryId;
use codex_tools::ResponsesApiNamespace;
use codex_tools::ResponsesApiNamespaceTool;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

use super::CognitiveTurnWitnesses;
use super::ExactDirectiveWitness;
use super::kg_extractor::MAX_STRUCTURED_KG_ENTITIES;
use super::kg_extractor::MAX_STRUCTURED_KG_KEY_BYTES;
use super::kg_extractor::MAX_STRUCTURED_KG_LABEL_BYTES;
use super::kg_extractor::MAX_STRUCTURED_KG_RELATION_BYTES;
use super::kg_extractor::MAX_STRUCTURED_KG_RELATIONS;
use super::kg_extractor::MAX_STRUCTURED_KG_TYPE_BYTES;
use super::kg_extractor::StructuredCognitiveKgExtractor;
use super::kg_extractor::StructuredKgError;
use super::kg_extractor::StructuredKgInput;
use super::now_unix_seconds;
use super::secret_like;
use crate::framing::digest_many;
use crate::framing::path_identity_bytes;

const COGNITIVE_NAMESPACE: &str = "hepta_cognitive";
const TOOL_OUTPUT_SCHEMA_VERSION: u32 = 2;
const MAX_RECALL_RESULTS: usize = 4;
const MAX_RECALL_CONTENT_BYTES: usize = 2 * 1024;
const MAX_RECALL_OUTPUT_BYTES: usize = 12 * 1024;
const MAX_EXPLAIN_CITATIONS: usize = 8;
const MAX_EXPLAIN_MEMORY_BYTES: usize = 4 * 1024;
const MAX_CITATION_CONTENT_BYTES: usize = 512;
const MAX_EXPLAIN_OUTPUT_BYTES: usize = 16 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum CognitiveToolOperation {
    Remember,
    Recall,
    Correct,
    Forget,
    Explain,
}

impl CognitiveToolOperation {
    fn name(self) -> &'static str {
        match self {
            Self::Remember => "remember",
            Self::Recall => "recall",
            Self::Correct => "correct",
            Self::Forget => "forget",
            Self::Explain => "explain",
        }
    }

    fn description(self) -> &'static str {
        match self {
            Self::Remember => {
                "Create structured cognitive facts together with versioned Hepta memory. Content is verified only when it is byte-exactly the complete current user text; provisional memory cannot carry structured facts and is never auto-attached."
            }
            Self::Recall => {
                "Search eligible verified Hepta memories in the current Agent/workspace scope."
            }
            Self::Correct => {
                "Atomically replace structured cognitive facts together with a compare-and-swap versioned memory correction. The new content must be byte-exactly witnessed from the complete current user text."
            }
            Self::Forget => {
                "Append a compare-and-swap tombstone to one memory without erasing its provenance chain."
            }
            Self::Explain => {
                "Read one memory head with bounded provenance citations and projection generation."
            }
        }
    }

    fn supports_parallel(self) -> bool {
        matches!(self, Self::Recall | Self::Explain)
    }
}

#[derive(Clone)]
struct CognitiveTool {
    runtime: CognitiveRuntime,
    thread_id: String,
    witness: ExactDirectiveWitness,
    operation: CognitiveToolOperation,
}

#[derive(Clone)]
struct DeferredCognitiveTool {
    runtime: CognitiveRuntime,
    thread_id: String,
    expected_turn_id: String,
    witnesses: Arc<CognitiveTurnWitnesses>,
    operation: CognitiveToolOperation,
}

pub(super) fn deferred_cognitive_tools(
    runtime: CognitiveRuntime,
    thread_id: String,
    expected_turn_id: String,
    witnesses: Arc<CognitiveTurnWitnesses>,
    write_enabled: bool,
) -> Vec<Arc<dyn ToolExecutor<ToolCall>>> {
    [
        CognitiveToolOperation::Remember,
        CognitiveToolOperation::Recall,
        CognitiveToolOperation::Correct,
        CognitiveToolOperation::Forget,
        CognitiveToolOperation::Explain,
    ]
    .into_iter()
    .filter(|operation| {
        write_enabled
            || matches!(
                operation,
                CognitiveToolOperation::Recall | CognitiveToolOperation::Explain
            )
    })
    .map(|operation| {
        Arc::new(DeferredCognitiveTool {
            runtime: runtime.clone(),
            thread_id: thread_id.clone(),
            expected_turn_id: expected_turn_id.clone(),
            witnesses: witnesses.clone(),
            operation,
        }) as Arc<dyn ToolExecutor<ToolCall>>
    })
    .collect()
}

impl ToolExecutor<ToolCall> for DeferredCognitiveTool {
    fn tool_name(&self) -> ToolName {
        ToolName::namespaced(COGNITIVE_NAMESPACE, self.operation.name())
    }

    fn spec(&self) -> ToolSpec {
        cognitive_tool_spec(self.operation)
    }

    fn supports_parallel_tool_calls(&self) -> bool {
        self.operation.supports_parallel()
    }

    fn handle(&self, call: ToolCall) -> codex_extension_api::ToolExecutorFuture<'_> {
        let runtime = self.runtime.clone();
        let thread_id = self.thread_id.clone();
        let expected_turn_id = self.expected_turn_id.clone();
        let witnesses = self.witnesses.clone();
        let operation = self.operation;
        Box::pin(async move {
            if call.turn_id != expected_turn_id {
                return Err(typed_error(
                    "hepta_cognitive_scope_mismatch",
                    "tool call does not match the planned turn",
                ));
            }
            match &runtime {
                CognitiveRuntime::Unavailable(reason) => {
                    return Err(typed_error(
                        "hepta_cognitive_unavailable",
                        format!("cognitive runtime is unavailable ({})", reason.code()),
                    ));
                }
                CognitiveRuntime::Absent => {
                    return Err(typed_error(
                        "hepta_cognitive_absent",
                        "cognitive runtime is not configured",
                    ));
                }
                CognitiveRuntime::Available(_) | CognitiveRuntime::AvailableFederated { .. } => {}
            }
            let Some(witness) = witnesses.get(call.turn_id.as_str()) else {
                return Err(typed_error(
                    "hepta_cognitive_witness_unavailable",
                    "the exact current-turn directive witness is unavailable",
                ));
            };
            CognitiveTool {
                runtime,
                thread_id,
                witness,
                operation,
            }
            .handle_call(call)
            .await
        })
    }
}

impl ToolExecutor<ToolCall> for CognitiveTool {
    fn tool_name(&self) -> ToolName {
        ToolName::namespaced(COGNITIVE_NAMESPACE, self.operation.name())
    }

    fn spec(&self) -> ToolSpec {
        cognitive_tool_spec(self.operation)
    }

    fn supports_parallel_tool_calls(&self) -> bool {
        self.operation.supports_parallel()
    }

    fn handle(&self, call: ToolCall) -> codex_extension_api::ToolExecutorFuture<'_> {
        Box::pin(self.handle_call(call))
    }
}

impl CognitiveTool {
    async fn handle_call(&self, call: ToolCall) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
        let store = match &self.runtime {
            CognitiveRuntime::Available(store)
            | CognitiveRuntime::AvailableFederated { store, .. } => store,
            CognitiveRuntime::Unavailable(reason) => {
                return Err(typed_error(
                    "hepta_cognitive_unavailable",
                    format!("cognitive runtime is unavailable ({})", reason.code()),
                ));
            }
            CognitiveRuntime::Absent => {
                return Err(typed_error(
                    "hepta_cognitive_absent",
                    "cognitive runtime is not configured",
                ));
            }
        };
        self.validate_call_scope(&call)?;
        match self.operation {
            CognitiveToolOperation::Remember => self.remember(store, &call).await,
            CognitiveToolOperation::Recall => self.recall(store, &call).await,
            CognitiveToolOperation::Correct => self.correct(store, &call).await,
            CognitiveToolOperation::Forget => self.forget(store, &call).await,
            CognitiveToolOperation::Explain => self.explain(store, &call).await,
        }
    }

    fn validate_call_scope(&self, call: &ToolCall) -> Result<(), FunctionCallError> {
        if call.turn_id != self.witness.turn_id
            || !call.environments.iter().any(|environment| {
                path_identity_bytes(environment.cwd.as_path())
                    == path_identity_bytes(self.witness.workspace.as_path())
            })
        {
            return Err(typed_error(
                "hepta_cognitive_scope_mismatch",
                "tool call does not match the witnessed turn/workspace",
            ));
        }
        Ok(())
    }

    async fn remember(
        &self,
        store: &CognitiveStore,
        call: &ToolCall,
    ) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
        let args: RememberArgs = parse_args(call)?;
        reject_secret("stable_key", args.stable_key.as_bytes())?;
        reject_secret("content", args.content.as_bytes())?;
        let now = tool_now()?;
        let (access, scope) = self.access_and_scope(store, args.scope);
        let verification = self.verification_for(args.content.as_str());
        let facts = StructuredCognitiveKgExtractor
            .extract(args.kg, verification)
            .map_err(structured_kg_error)?;
        let source_kind = if verification == MemoryVerification::Verified {
            LedgerSourceKind::ExplicitMemoryDirective
        } else {
            LedgerSourceKind::AssistantConclusion
        };
        let source = SourceDraft {
            scope: scope.clone(),
            kind: source_kind,
            event_key: self.event_key(call, CognitiveToolOperation::Remember),
            content: args.content.as_bytes().to_vec(),
            observed_at_unix_seconds: now,
        };
        let draft = MemoryDraft {
            stable_key: args.stable_key,
            revision: MemoryRevisionDraft {
                scope,
                content: args.content,
                verification,
                lifecycle: MemoryLifecycleState::Active,
                valid_from_unix_seconds: now,
                valid_to_unix_seconds: args.valid_to_unix_seconds,
                citations: Vec::new(),
            },
        };
        let receipt = store
            .remember_with_kg(&access, &source, &draft, &facts)
            .await
            .map_err(store_error)?;
        write_receipt_output("remembered", &receipt)
    }

    async fn recall(
        &self,
        store: &CognitiveStore,
        call: &ToolCall,
    ) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
        let args: RecallArgs = parse_args(call)?;
        reject_secret("query", args.query.as_bytes())?;
        let now = tool_now()?;
        let access = CognitiveAccess::workspace_private(
            store.owner_agent_id().clone(),
            self.witness.workspace_sha256.clone(),
        );
        let batch = store
            .retrieve_memory_candidates(&access, &RetrievalRequest::new(args.query, now))
            .await
            .map_err(store_error)?;
        let memories = batch
            .candidates
            .iter()
            .filter(|candidate| {
                candidate.memory.verification == MemoryVerification::Verified
                    && candidate.memory.lifecycle == MemoryLifecycleState::Active
                    && !secret_like(candidate.memory.content.as_bytes())
            })
            .take(MAX_RECALL_RESULTS)
            .map(|candidate| {
                json!({
                    "memory_id": candidate.memory.id.memory_id.as_str(),
                    "revision": candidate.memory.id.revision,
                    "content": bounded_text(&candidate.memory.content, MAX_RECALL_CONTENT_BYTES),
                    "content_sha256": candidate.memory.content_sha256.as_str(),
                    "reciprocal_rank_score": candidate.reciprocal_rank_score,
                    "channels": candidate.channels,
                })
            })
            .collect::<Vec<_>>();
        json_output(
            json!({
                "schema_version": TOOL_OUTPUT_SCHEMA_VERSION,
                "operation": "recall",
                "query_sha256": batch.query_sha256.as_str(),
                "memories": memories,
            }),
            MAX_RECALL_OUTPUT_BYTES,
        )
    }

    async fn correct(
        &self,
        store: &CognitiveStore,
        call: &ToolCall,
    ) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
        let args: CorrectArgs = parse_args(call)?;
        reject_secret("content", args.content.as_bytes())?;
        require_exact_directive(&self.witness, args.content.as_str(), "correct")?;
        let memory_id = parse_memory_id(args.memory_id)?;
        let access = CognitiveAccess::workspace_private(
            store.owner_agent_id().clone(),
            self.witness.workspace_sha256.clone(),
        );
        let current = store
            .read_memory_head(&access, &memory_id)
            .await
            .map_err(store_error)?;
        let now = tool_now()?;
        let facts = StructuredCognitiveKgExtractor
            .extract(args.kg, MemoryVerification::Verified)
            .map_err(structured_kg_error)?;
        let source = SourceDraft {
            scope: current.scope.clone(),
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: self.event_key(call, CognitiveToolOperation::Correct),
            content: args.content.as_bytes().to_vec(),
            observed_at_unix_seconds: now,
        };
        let revision = MemoryRevisionDraft {
            scope: current.scope,
            content: args.content,
            verification: MemoryVerification::Verified,
            lifecycle: MemoryLifecycleState::Active,
            valid_from_unix_seconds: now,
            valid_to_unix_seconds: args.valid_to_unix_seconds,
            citations: Vec::new(),
        };
        let receipt = store
            .correct_with_kg(
                &access,
                &memory_id,
                args.expected_revision,
                &source,
                &revision,
                &facts,
            )
            .await
            .map_err(store_error)?;
        write_receipt_output("corrected", &receipt)
    }

    async fn forget(
        &self,
        store: &CognitiveStore,
        call: &ToolCall,
    ) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
        let args: ForgetArgs = parse_args(call)?;
        reject_secret("reason", args.reason.as_bytes())?;
        require_exact_directive(&self.witness, args.reason.as_str(), "forget")?;
        let memory_id = parse_memory_id(args.memory_id)?;
        let access = CognitiveAccess::workspace_private(
            store.owner_agent_id().clone(),
            self.witness.workspace_sha256.clone(),
        );
        let current = store
            .read_memory_head(&access, &memory_id)
            .await
            .map_err(store_error)?;
        let now = tool_now()?;
        let source = SourceDraft {
            scope: current.scope.clone(),
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: self.event_key(call, CognitiveToolOperation::Forget),
            content: args.reason.as_bytes().to_vec(),
            observed_at_unix_seconds: now,
        };
        let receipt = store
            .forget_with_kg(
                &access,
                &memory_id,
                args.expected_revision,
                &source,
                &ForgetMemoryDraft {
                    scope: current.scope,
                    reason: args.reason,
                    valid_from_unix_seconds: now,
                    citations: Vec::new(),
                },
            )
            .await
            .map_err(store_error)?;
        write_receipt_output("forgotten", &receipt)
    }

    async fn explain(
        &self,
        store: &CognitiveStore,
        call: &ToolCall,
    ) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
        let args: ExplainArgs = parse_args(call)?;
        let memory_id = parse_memory_id(args.memory_id)?;
        let access = CognitiveAccess::workspace_private(
            store.owner_agent_id().clone(),
            self.witness.workspace_sha256.clone(),
        );
        let explanation = store
            .explain_memory_head(&access, &memory_id)
            .await
            .map_err(store_error)?;
        if secret_like(explanation.memory.content.as_bytes())
            || explanation
                .citations
                .iter()
                .any(|citation| secret_like(&citation.content))
        {
            return Err(typed_error(
                "hepta_cognitive_secret_like_content",
                "memory or citation contains secret-like content",
            ));
        }
        let citations = explanation
            .citations
            .iter()
            .take(MAX_EXPLAIN_CITATIONS)
            .map(|citation| {
                json!({
                    "source_id": citation.id.source_id.as_str(),
                    "revision": citation.id.revision,
                    "kind": citation.kind,
                    "content": bounded_bytes(&citation.content, MAX_CITATION_CONTENT_BYTES),
                    "content_sha256": citation.content_sha256.as_str(),
                    "observed_at_unix_seconds": citation.observed_at_unix_seconds,
                })
            })
            .collect::<Vec<_>>();
        json_output(
            json!({
                "schema_version": TOOL_OUTPUT_SCHEMA_VERSION,
                "operation": "explain",
                "memory": {
                    "memory_id": explanation.memory.id.memory_id.as_str(),
                    "revision": explanation.memory.id.revision,
                    "scope": explanation.memory.scope,
                    "content": bounded_text(&explanation.memory.content, MAX_EXPLAIN_MEMORY_BYTES),
                    "content_sha256": explanation.memory.content_sha256.as_str(),
                    "verification": explanation.memory.verification,
                    "lifecycle": explanation.memory.lifecycle,
                    "valid_from_unix_seconds": explanation.memory.valid_from_unix_seconds,
                    "valid_to_unix_seconds": explanation.memory.valid_to_unix_seconds,
                },
                "citations": citations,
                "citation_count": explanation.citations.len(),
                "citation_items_returned": citations.len(),
                "kg_projection_generation": explanation
                    .kg_projection_generation
                    .map(codex_hepta_memory::ProjectionGeneration::get),
            }),
            MAX_EXPLAIN_OUTPUT_BYTES,
        )
    }

    fn access_and_scope(
        &self,
        store: &CognitiveStore,
        selection: ScopeSelection,
    ) -> (CognitiveAccess, CognitiveScope) {
        match selection {
            ScopeSelection::AgentPrivate => (
                CognitiveAccess::agent_private(store.owner_agent_id().clone()),
                CognitiveScope::AgentPrivate,
            ),
            ScopeSelection::WorkspacePrivate => (
                CognitiveAccess::workspace_private(
                    store.owner_agent_id().clone(),
                    self.witness.workspace_sha256.clone(),
                ),
                CognitiveScope::WorkspacePrivate {
                    workspace_sha256: self.witness.workspace_sha256.clone(),
                },
            ),
        }
    }

    fn verification_for(&self, content: &str) -> MemoryVerification {
        if self.witness.verifies_content(content) {
            MemoryVerification::Verified
        } else {
            MemoryVerification::Provisional
        }
    }

    fn event_key(&self, call: &ToolCall, operation: CognitiveToolOperation) -> String {
        let digest = digest_many(
            b"hepta:cognitive:tool-source-event:v1",
            &[
                self.thread_id.as_bytes(),
                call.turn_id.as_bytes(),
                call.call_id.as_bytes(),
                operation.name().as_bytes(),
            ],
        );
        format!("tool:{}:{}", operation.name(), digest.as_str())
    }
}

#[derive(Clone, Copy, Debug, Default, Deserialize)]
#[serde(rename_all = "snake_case")]
enum ScopeSelection {
    AgentPrivate,
    #[default]
    WorkspacePrivate,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RememberArgs {
    stable_key: String,
    content: String,
    #[serde(default)]
    scope: ScopeSelection,
    #[serde(default)]
    valid_to_unix_seconds: Option<i64>,
    #[serde(default)]
    kg: StructuredKgInput,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RecallArgs {
    query: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CorrectArgs {
    memory_id: String,
    expected_revision: u64,
    content: String,
    #[serde(default)]
    valid_to_unix_seconds: Option<i64>,
    #[serde(default)]
    kg: StructuredKgInput,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ForgetArgs {
    memory_id: String,
    expected_revision: u64,
    reason: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ExplainArgs {
    memory_id: String,
}

fn cognitive_tool_spec(operation: CognitiveToolOperation) -> ToolSpec {
    let parameters = parse_tool_input_schema(&input_schema(operation))
        .unwrap_or_else(|error| panic!("cognitive tool schema must parse: {error}"));
    ToolSpec::Namespace(ResponsesApiNamespace {
        name: COGNITIVE_NAMESPACE.to_string(),
        description: "Structured cognitive facts, versioned scoped Hepta Memory, and explainable retrieval tools.".to_string(),
        tools: vec![ResponsesApiNamespaceTool::Function(ResponsesApiTool {
            name: operation.name().to_string(),
            description: operation.description().to_string(),
            strict: false,
            parameters,
            output_schema: None,
            defer_loading: None,
        })],
    })
}

fn input_schema(operation: CognitiveToolOperation) -> Value {
    let string = || json!({ "type": "string", "minLength": 1 });
    let revision = || json!({ "type": "integer", "minimum": 1 });
    let scope = || {
        json!({
            "type": "string",
            "enum": ["workspace_private", "agent_private"],
            "default": "workspace_private"
        })
    };
    let (properties, required) = match operation {
        CognitiveToolOperation::Remember => (
            json!({
                "stable_key": { "type": "string", "minLength": 1, "maxLength": 512 },
                "content": { "type": "string", "minLength": 1, "maxLength": 65536 },
                "scope": scope(),
                "valid_to_unix_seconds": { "type": ["integer", "null"] },
                "kg": structured_kg_schema()
            }),
            json!(["stable_key", "content"]),
        ),
        CognitiveToolOperation::Recall => (
            json!({
                "query": { "type": "string", "minLength": 1, "maxLength": 2048 }
            }),
            json!(["query"]),
        ),
        CognitiveToolOperation::Correct => (
            json!({
                "memory_id": string(),
                "expected_revision": revision(),
                "content": { "type": "string", "minLength": 1, "maxLength": 65536 },
                "valid_to_unix_seconds": { "type": ["integer", "null"] },
                "kg": structured_kg_schema()
            }),
            json!(["memory_id", "expected_revision", "content"]),
        ),
        CognitiveToolOperation::Forget => (
            json!({
                "memory_id": string(),
                "expected_revision": revision(),
                "reason": { "type": "string", "minLength": 1, "maxLength": 1024 }
            }),
            json!(["memory_id", "expected_revision", "reason"]),
        ),
        CognitiveToolOperation::Explain => (json!({ "memory_id": string() }), json!(["memory_id"])),
    };
    json!({
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": false
    })
}

fn structured_kg_schema() -> Value {
    json!({
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "maxItems": MAX_STRUCTURED_KG_ENTITIES,
                "items": {
                    "type": "object",
                    "properties": {
                        "key": { "type": "string", "minLength": 1, "maxLength": MAX_STRUCTURED_KG_KEY_BYTES },
                        "entity_type": { "type": "string", "minLength": 1, "maxLength": MAX_STRUCTURED_KG_TYPE_BYTES },
                        "label": { "type": "string", "minLength": 1, "maxLength": MAX_STRUCTURED_KG_LABEL_BYTES }
                    },
                    "required": ["key", "entity_type", "label"],
                    "additionalProperties": false
                }
            },
            "relations": {
                "type": "array",
                "maxItems": MAX_STRUCTURED_KG_RELATIONS,
                "items": {
                    "type": "object",
                    "properties": {
                        "key": { "type": "string", "minLength": 1, "maxLength": MAX_STRUCTURED_KG_KEY_BYTES },
                        "from_entity_key": { "type": "string", "minLength": 1, "maxLength": MAX_STRUCTURED_KG_KEY_BYTES },
                        "to_entity_key": { "type": "string", "minLength": 1, "maxLength": MAX_STRUCTURED_KG_KEY_BYTES },
                        "relation": { "type": "string", "minLength": 1, "maxLength": MAX_STRUCTURED_KG_RELATION_BYTES }
                    },
                    "required": ["key", "from_entity_key", "to_entity_key", "relation"],
                    "additionalProperties": false
                }
            }
        },
        "additionalProperties": false,
        "default": { "entities": [], "relations": [] }
    })
}

fn parse_args<T: for<'de> Deserialize<'de>>(call: &ToolCall) -> Result<T, FunctionCallError> {
    let arguments = call.function_arguments()?;
    serde_json::from_str(arguments).map_err(|error| {
        typed_error(
            "hepta_cognitive_invalid_arguments",
            format!("invalid tool arguments: {error}"),
        )
    })
}

fn parse_memory_id(value: String) -> Result<StableMemoryId, FunctionCallError> {
    StableMemoryId::parse(value).map_err(|_| {
        typed_error(
            "hepta_cognitive_invalid_memory_id",
            "memory_id is not a canonical stable memory id",
        )
    })
}

fn reject_secret(label: &str, content: &[u8]) -> Result<(), FunctionCallError> {
    if secret_like(content) {
        return Err(typed_error(
            "hepta_cognitive_secret_like_content",
            format!("{label} contains secret-like content and was not persisted"),
        ));
    }
    Ok(())
}

fn require_exact_directive(
    witness: &ExactDirectiveWitness,
    content: &str,
    operation: &str,
) -> Result<(), FunctionCallError> {
    if !witness.verifies_content(content) {
        return Err(typed_error(
            "hepta_cognitive_explicit_directive_required",
            format!(
                "{operation} requires byte-exact content from the complete current user directive"
            ),
        ));
    }
    Ok(())
}

fn tool_now() -> Result<i64, FunctionCallError> {
    now_unix_seconds().ok_or_else(|| {
        typed_error(
            "hepta_cognitive_clock_unavailable",
            "system time is unavailable",
        )
    })
}

fn store_error(error: CognitiveStoreError) -> FunctionCallError {
    match error {
        CognitiveStoreError::Invalid(message) => typed_error("hepta_cognitive_invalid", message),
        CognitiveStoreError::AccessDenied(_) => typed_error(
            "hepta_cognitive_access_denied",
            "cognitive scope access was denied",
        ),
        CognitiveStoreError::Conflict(message) => typed_error("hepta_cognitive_conflict", message),
        CognitiveStoreError::Corrupt(_) => typed_error(
            "hepta_cognitive_corrupt",
            "cognitive data failed integrity validation",
        ),
        CognitiveStoreError::Unavailable(_) => typed_error(
            "hepta_cognitive_unavailable",
            "cognitive runtime is unavailable",
        ),
    }
}

fn structured_kg_error(error: StructuredKgError) -> FunctionCallError {
    typed_error(error.code(), error.message())
}

fn typed_error(code: &str, message: impl Into<String>) -> FunctionCallError {
    FunctionCallError::RespondToModel(
        json!({
            "error": {
                "code": code,
                "message": message.into(),
            }
        })
        .to_string(),
    )
}

fn write_receipt_output(
    operation: &str,
    receipt: &CognitiveWriteReceipt,
) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
    let memory = &receipt.memory;
    let fact_count = receipt
        .projection
        .entity_count
        .checked_add(receipt.projection.relation_count)
        .ok_or_else(|| {
            typed_error(
                "hepta_cognitive_output_error",
                "projection fact count overflowed the bounded tool output",
            )
        })?;
    json_output(
        json!({
            "schema_version": TOOL_OUTPUT_SCHEMA_VERSION,
            "operation": operation,
            "memory": {
                "memory_id": memory.id.memory_id.as_str(),
                "revision": memory.id.revision,
                "scope": memory.scope,
                "content_sha256": memory.content_sha256.as_str(),
                "verification": memory.verification,
                "lifecycle": memory.lifecycle,
                "valid_from_unix_seconds": memory.valid_from_unix_seconds,
                "valid_to_unix_seconds": memory.valid_to_unix_seconds,
            },
            "source": {
                "source_id": receipt.source.source_id.as_str(),
                "revision": receipt.source.revision,
            },
            "projection": {
                "generation": receipt.projection.generation.get(),
                "fact_set_sha256": receipt.projection.fact_set_sha256.as_str(),
                "input_heads_sha256": receipt.projection.input_heads_sha256.as_str(),
                "output_sha256": receipt.projection.output_sha256.as_str(),
                "entity_count": receipt.projection.entity_count,
                "relation_count": receipt.projection.relation_count,
                "fact_count": fact_count,
                "node_count": receipt.projection.node_count,
                "edge_count": receipt.projection.edge_count,
            },
        }),
        MAX_RECALL_OUTPUT_BYTES,
    )
}

fn json_output(value: Value, max_bytes: usize) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
    let size = serde_json::to_vec(&value)
        .map_err(|_| {
            typed_error(
                "hepta_cognitive_output_error",
                "tool output failed to encode",
            )
        })?
        .len();
    if size > max_bytes {
        return Err(typed_error(
            "hepta_cognitive_output_limit",
            "bounded cognitive tool output exceeded its hard byte limit",
        ));
    }
    Ok(Box::new(JsonToolOutput::new(value)))
}

fn bounded_text(value: &str, max_bytes: usize) -> String {
    if value.len() <= max_bytes {
        return value.to_string();
    }
    let mut boundary = max_bytes.min(value.len());
    while boundary > 0 && !value.is_char_boundary(boundary) {
        boundary -= 1;
    }
    value[..boundary].to_string()
}

fn bounded_bytes(value: &[u8], max_bytes: usize) -> String {
    bounded_text(String::from_utf8_lossy(value).as_ref(), max_bytes)
}

#[cfg(test)]
#[path = "tools_tests.rs"]
mod tests;
