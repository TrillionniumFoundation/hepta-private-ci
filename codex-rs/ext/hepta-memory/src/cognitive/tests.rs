use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS;
use codex_extension_api::EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION;
use codex_extension_api::EphemeralModelInputContext;
use codex_extension_api::EphemeralModelInputContributor;
use codex_extension_api::EphemeralModelInputProposal;
use codex_extension_api::ExtensionData;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTransport;
use codex_extension_api::ToolContributor;
use codex_extension_api::TurnInputContext;
use codex_extension_api::TurnInputContributor;
use codex_extension_api::TurnInputEnvironment;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::KgEntityFactDraft;
use codex_hepta_memory::KgFactSetDraft;
use codex_hepta_memory::KgRelationFactDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use codex_protocol::user_input::UserInput;
use codex_utils_path_uri::PathUri;
use tempfile::TempDir;

use super::*;

const THREAD_ID: &str = "00000000-0000-4000-8000-000000000301";

struct CognitiveFixture {
    _temp: TempDir,
    store: Arc<CognitiveStore>,
    workspace: PathBuf,
    access: CognitiveAccess,
    scope: CognitiveScope,
    memory: MemoryRevisionRecord,
}

struct CountingRecallBackend {
    store: Arc<CognitiveStore>,
    retrieve_calls: AtomicUsize,
    revalidate_calls: AtomicUsize,
}

struct GenerationDriftRecallBackend {
    store: Arc<CognitiveStore>,
}

struct PartialBatchDriftRecallBackend {
    store: Arc<CognitiveStore>,
    batch_calls: AtomicUsize,
}

impl CountingRecallBackend {
    fn new(store: Arc<CognitiveStore>) -> Self {
        Self {
            store,
            retrieve_calls: AtomicUsize::new(0),
            revalidate_calls: AtomicUsize::new(0),
        }
    }
}

impl CognitiveRecallBackend for CountingRecallBackend {
    fn retrieve<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        request: &'a RetrievalRequest,
    ) -> RetrievalFuture<'a> {
        self.retrieve_calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(self.store.retrieve_memory_candidates(access, request))
    }

    fn revalidate_batch<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        bindings: &'a [MemoryRevalidationBinding],
        now_unix_seconds: i64,
    ) -> RevalidationFuture<'a> {
        self.revalidate_calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(
            self.store
                .revalidate_memory_candidates(access, bindings, now_unix_seconds),
        )
    }
}

impl CognitiveRecallBackend for GenerationDriftRecallBackend {
    fn retrieve<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        request: &'a RetrievalRequest,
    ) -> RetrievalFuture<'a> {
        Box::pin(self.store.retrieve_memory_candidates(access, request))
    }

    fn revalidate_batch<'a>(
        &'a self,
        _access: &'a CognitiveAccess,
        bindings: &'a [MemoryRevalidationBinding],
        _now_unix_seconds: i64,
    ) -> RevalidationFuture<'a> {
        Box::pin(async move {
            Ok(bindings
                .iter()
                .map(|_| {
                    RevalidationStatus::Stale(
                        codex_hepta_memory::RevalidationDrift::KgProjectionGeneration,
                    )
                })
                .collect())
        })
    }
}

impl CognitiveRecallBackend for PartialBatchDriftRecallBackend {
    fn retrieve<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        request: &'a RetrievalRequest,
    ) -> RetrievalFuture<'a> {
        Box::pin(self.store.retrieve_memory_candidates(access, request))
    }

    fn revalidate_batch<'a>(
        &'a self,
        access: &'a CognitiveAccess,
        bindings: &'a [MemoryRevalidationBinding],
        now_unix_seconds: i64,
    ) -> RevalidationFuture<'a> {
        self.batch_calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(async move {
            let mut statuses = self
                .store
                .revalidate_memory_candidates(access, bindings, now_unix_seconds)
                .await?;
            if statuses.len() > 1 {
                statuses[1] = RevalidationStatus::Stale(
                    codex_hepta_memory::RevalidationDrift::KgProjectionGeneration,
                );
            }
            Ok(statuses)
        })
    }
}

fn text_input(text: &str) -> Vec<UserInput> {
    vec![UserInput::Text {
        text: text.to_string(),
        text_elements: Vec::new(),
    }]
}

async fn cognitive_fixture() -> CognitiveFixture {
    let temp = tempfile::tempdir().expect("tempdir");
    let fleet_root = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet_root).expect("fleet root");
    let agent_id = AgentId::parse("00000000-0000-4000-8000-000000000311").expect("agent id");
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
    let workspace_sha256 = workspace_digest(&workspace);
    let access = CognitiveAccess::workspace_private(agent_id, workspace_sha256.clone());
    let scope = CognitiveScope::WorkspacePrivate { workspace_sha256 };
    let now = now_unix_seconds().expect("time");
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "seed-rust-durability".to_string(),
                content: b"rust durability is required".to_vec(),
                observed_at_unix_seconds: now,
            },
        )
        .await
        .expect("source");
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "rust-durability".to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "rust durability is required".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: now,
                    valid_to_unix_seconds: None,
                    citations: vec![citation],
                },
            },
        )
        .await
        .expect("memory");
    CognitiveFixture {
        _temp: temp,
        store,
        workspace,
        access,
        scope,
        memory,
    }
}

fn cognitive_thread_store() -> ExtensionData {
    let store = ExtensionData::new(THREAD_ID);
    store.insert(HeptaMemoryThreadState::for_cognitive_test(true));
    store
}

fn tool_names(
    extension: &CognitiveExtension,
    thread_store: &ExtensionData,
) -> Vec<(Option<String>, String)> {
    let session_store = ExtensionData::new("session-tool-gating");
    let step_store = ExtensionData::new("turn-tool-gating");
    ToolContributor::tools_for_step(extension, &session_store, thread_store, &step_store)
        .into_iter()
        .map(|tool| {
            let name = tool.tool_name();
            (name.namespace, name.name)
        })
        .collect()
}

async fn prepare(
    extension: &CognitiveExtension,
    thread_store: &ExtensionData,
    turn_store: &ExtensionData,
    workspace: &Path,
    query: &str,
) {
    let session_store = ExtensionData::new("session-cognitive");
    let step_store = ExtensionData::new(turn_store.level_id());
    let fragments = TurnInputContributor::contribute(
        extension,
        TurnInputContext {
            turn_id: turn_store.level_id().to_string(),
            user_input: text_input(query),
            environments: vec![TurnInputEnvironment {
                environment_id: "primary".to_string(),
                cwd: PathUri::from_host_native_path(workspace).expect("absolute workspace"),
                is_primary: true,
            }],
        },
        None,
        &session_store,
        thread_store,
        turn_store,
        &step_store,
    )
    .await;
    assert!(fragments.is_empty());
    assert!(EphemeralModelInputContributor::is_active(
        extension,
        thread_store,
        turn_store,
    ));
}

async fn propose(
    extension: &CognitiveExtension,
    thread_store: &ExtensionData,
    turn_store: &ExtensionData,
    workspace: &Path,
    attempt_id: &str,
) -> Option<EphemeralModelInputProposal> {
    let session_store = ExtensionData::new("session-cognitive");
    let base = ModelProviderSha256Digest::parse("1".repeat(64)).expect("digest");
    EphemeralModelInputContributor::contribute(
        extension,
        EphemeralModelInputContext {
            schema_version: EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION,
            session_store: &session_store,
            thread_store,
            turn_store,
            attempt_id,
            base_logical_request_sha256: &base,
            thread_id: THREAD_ID,
            turn_id: turn_store.level_id(),
            cwd: workspace,
            request_kind: ModelProviderRequestKind::Turn,
            provider_id: "provider-cognitive",
            model: "model-cognitive",
            transport: ModelProviderTransport::Http,
            generate: true,
            model_context_window: Some(128_000),
            max_content_bytes: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES,
            max_content_tokens: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS,
        },
    )
    .await
    .expect("fail-open cognitive contributor")
}

#[test]
fn exact_directive_capture_is_digest_only_and_byte_exact() {
    let capture = capture_directive(&text_input("remember this exactly"));
    assert_eq!(capture.content_bytes, 21);
    assert_eq!(capture.query.as_deref(), Some("remember this exactly"));
    assert!(capture.byte_exact_verification_allowed);
    assert_eq!(
        capture.content_sha256,
        Sha256Digest::for_bytes(b"remember this exactly")
    );
}

#[test]
fn secret_detector_covers_common_key_shapes() {
    for secret in [
        "api_key=secret-value",
        "AKIAIOSFODNN7EXAMPLE",
        "sk-abcdefghijklmnopqrstuvwxyz0123456789",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "github_pat_abcdefghijklmnopqrstuvwxyz0123456789",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature",
        "-----BEGIN PRIVATE KEY----- payload",
    ] {
        assert!(secret_like(secret.as_bytes()), "missed {secret}");
    }
    assert!(!secret_like(b"remember that API keys must never be stored"));
}

#[tokio::test]
async fn mutation_tools_require_both_explicit_write_and_available_runtime() {
    let fixture = cognitive_fixture().await;
    let available = CognitiveExtension::new(CognitiveRuntime::Available(fixture.store));

    let read_only = ExtensionData::new(THREAD_ID);
    read_only.insert(HeptaMemoryThreadState::for_cognitive_test_with_write(
        true, false,
    ));
    assert_eq!(
        tool_names(&available, &read_only),
        vec![
            (Some("hepta_cognitive".to_string()), "recall".to_string()),
            (Some("hepta_cognitive".to_string()), "explain".to_string()),
        ]
    );

    let writable = ExtensionData::new(THREAD_ID);
    writable.insert(HeptaMemoryThreadState::for_cognitive_test_with_write(
        true, true,
    ));
    assert_eq!(tool_names(&available, &writable).len(), 5);

    let unavailable = CognitiveExtension::new(CognitiveRuntime::Unavailable(
        codex_hepta_memory::CognitiveUnavailableReason::StorageUnavailable,
    ));
    assert_eq!(
        tool_names(&unavailable, &writable),
        vec![
            (Some("hepta_cognitive".to_string()), "recall".to_string()),
            (Some("hepta_cognitive".to_string()), "explain".to_string()),
        ]
    );
}

#[test]
fn query_larger_than_two_kib_is_not_prepared_but_witness_remains() {
    let text = "x".repeat(MAX_RETRIEVAL_QUERY_BYTES + 1);
    let capture = capture_directive(&text_input(&text));
    assert!(capture.query.is_none());
    assert_eq!(capture.content_bytes, text.len());
    assert!(capture.byte_exact_verification_allowed);
}

#[tokio::test]
async fn every_physical_attempt_revalidates_with_stable_source_content_and_binding() {
    let fixture = cognitive_fixture().await;
    let backend = Arc::new(CountingRecallBackend::new(fixture.store.clone()));
    let extension = CognitiveExtension::with_recall(fixture.store, backend.clone());
    let thread_store = cognitive_thread_store();
    let turn_store = ExtensionData::new("turn-retry-revalidation");
    prepare(
        &extension,
        &thread_store,
        &turn_store,
        &fixture.workspace,
        "rust durability",
    )
    .await;
    assert_eq!(backend.retrieve_calls.load(Ordering::SeqCst), 1);

    let first = propose(
        &extension,
        &thread_store,
        &turn_store,
        &fixture.workspace,
        "model-provider-attempt:v1:first",
    )
    .await
    .expect("first proposal");
    let first_source = first.source().as_str().to_string();
    let first_binding = first.source_binding_sha256().as_str().to_string();
    let first_content_sha = first.content_sha256().as_str().to_string();
    let first_content = first.into_content();
    let attachment: serde_json::Value =
        serde_json::from_str(&first_content).expect("structured cognitive attachment");
    assert_eq!(attachment["schema_version"], 2);
    assert_eq!(
        attachment["memories"][0]["channels"],
        serde_json::json!(["memory_fts", "recency"])
    );

    let retry = propose(
        &extension,
        &thread_store,
        &turn_store,
        &fixture.workspace,
        "model-provider-attempt:v1:retry",
    )
    .await
    .expect("retry proposal");
    assert_eq!(retry.source().as_str(), COGNITIVE_SOURCE);
    assert_eq!(retry.source().as_str(), first_source);
    assert_eq!(
        retry.source_binding_sha256().as_str(),
        first_binding.as_str()
    );
    assert_eq!(retry.content_sha256().as_str(), first_content_sha.as_str());
    assert_eq!(retry.into_content(), first_content);
    assert_eq!(backend.retrieve_calls.load(Ordering::SeqCst), 1);
    assert_eq!(backend.revalidate_calls.load(Ordering::SeqCst), 2);
}

/// A retrying transport may invoke the same physical attempt more than once
/// after a timeout or callback race.  Read-only memory context must remain a
/// deterministic replay: the exact source, revision-bound attachment, and
/// content digests cannot drift, and retries must not trigger a fresh search.
#[tokio::test]
async fn duplicate_read_only_replay_soak_preserves_exact_memory_binding() {
    const REPLAY_COUNT: usize = 32;

    let fixture = cognitive_fixture().await;
    let backend = Arc::new(CountingRecallBackend::new(fixture.store.clone()));
    let extension = CognitiveExtension::with_recall(fixture.store, backend.clone());
    let thread_store = cognitive_thread_store();
    let turn_store = ExtensionData::new("turn-duplicate-replay-soak");
    prepare(
        &extension,
        &thread_store,
        &turn_store,
        &fixture.workspace,
        "rust durability",
    )
    .await;

    let first = propose(
        &extension,
        &thread_store,
        &turn_store,
        &fixture.workspace,
        "model-provider-attempt:v1:duplicate",
    )
    .await
    .expect("initial read-only proposal");
    let expected_source = first.source().as_str().to_string();
    let expected_binding = first.source_binding_sha256().as_str().to_string();
    let expected_content_sha = first.content_sha256().as_str().to_string();
    let expected_content = first.into_content();
    let expected_attachment: serde_json::Value =
        serde_json::from_str(&expected_content).expect("structured cognitive attachment");
    assert_eq!(
        expected_attachment["memories"][0]["revision"],
        fixture.memory.id.revision
    );
    assert_eq!(
        expected_attachment["memories"][0]["citations"][0]["revision"],
        fixture.memory.citations[0].revision
    );

    for replay in 0..REPLAY_COUNT {
        let proposal = propose(
            &extension,
            &thread_store,
            &turn_store,
            &fixture.workspace,
            "model-provider-attempt:v1:duplicate",
        )
        .await
        .unwrap_or_else(|| panic!("duplicate replay {replay} lost read-only context"));
        assert_eq!(proposal.attempt_id(), "model-provider-attempt:v1:duplicate");
        assert_eq!(proposal.source().as_str(), expected_source);
        assert_eq!(proposal.source_binding_sha256().as_str(), expected_binding);
        assert_eq!(proposal.content_sha256().as_str(), expected_content_sha);
        assert_eq!(proposal.into_content(), expected_content);
    }

    assert_eq!(
        backend.retrieve_calls.load(Ordering::SeqCst),
        1,
        "duplicate physical replay must not rescan memory"
    );
    assert_eq!(
        backend.revalidate_calls.load(Ordering::SeqCst),
        REPLAY_COUNT + 1,
        "each physical replay must revalidate the immutable binding"
    );
}

#[tokio::test]
async fn entity_and_graph_channels_survive_initial_compile_and_physical_revalidation() {
    let fixture = cognitive_fixture().await;
    let mut batch = fixture
        .store
        .retrieve_memory_candidates(
            &fixture.access,
            &RetrievalRequest::new("rust durability", now_unix_seconds().expect("time")),
        )
        .await
        .expect("retrieval batch");
    assert_eq!(batch.candidates.len(), 1);
    batch.candidates[0].channels = vec![
        RetrievalChannel::GraphOneHop,
        RetrievalChannel::EntityFts,
        RetrievalChannel::EntityFts,
    ];

    let (prepared, initial) =
        compile_retrieval_batch(&batch, 16 * 1024, 8 * 1024).expect("prepared attachment");
    assert_eq!(prepared.len(), 1);
    assert_eq!(
        prepared[0].channels,
        vec![RetrievalChannel::EntityFts, RetrievalChannel::GraphOneHop]
    );
    let initial: serde_json::Value = serde_json::from_str(&initial).expect("initial attachment");
    assert_eq!(
        initial["memories"][0]["channels"],
        serde_json::json!(["entity_fts", "graph_one_hop"])
    );

    let explanation = fixture
        .store
        .explain_memory_head(&fixture.access, &fixture.memory.id.memory_id)
        .await
        .expect("current explanation");
    let physical = compile_explanations(&[RevalidatedAttachmentMemory {
        explanation,
        channels: prepared[0].channels.clone(),
    }])
    .expect("physical attachment");
    let physical: serde_json::Value =
        serde_json::from_str(&physical).expect("physical attachment json");
    assert_eq!(physical["schema_version"], 2);
    assert_eq!(
        physical["memories"][0]["channels"],
        initial["memories"][0]["channels"]
    );
}

#[tokio::test]
async fn structured_kg_retrieval_channels_reach_the_physical_attachment() {
    let fixture = cognitive_fixture().await;
    let now = now_unix_seconds().expect("time");
    let content = "The project launch is scheduled for Friday.";
    let written = fixture
        .store
        .remember_with_kg(
            &fixture.access,
            &SourceDraft {
                scope: fixture.scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "luminous-project".to_string(),
                content: content.as_bytes().to_vec(),
                observed_at_unix_seconds: now,
            },
            &MemoryDraft {
                stable_key: "luminous-project".to_string(),
                revision: MemoryRevisionDraft {
                    scope: fixture.scope.clone(),
                    content: content.to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: now,
                    valid_to_unix_seconds: None,
                    citations: Vec::new(),
                },
            },
            &KgFactSetDraft {
                entities: vec![
                    KgEntityFactDraft {
                        key: "luminous-initiative".to_string(),
                        entity_type: "project".to_string(),
                        label: "Luminous Initiative".to_string(),
                    },
                    KgEntityFactDraft {
                        key: "friday".to_string(),
                        entity_type: "weekday".to_string(),
                        label: "Friday".to_string(),
                    },
                ],
                relations: vec![KgRelationFactDraft {
                    key: "launch-day".to_string(),
                    from_entity_key: "luminous-initiative".to_string(),
                    to_entity_key: "friday".to_string(),
                    relation: "launches_on".to_string(),
                }],
            },
        )
        .await
        .expect("structured KG write");
    let extension = CognitiveExtension::new(CognitiveRuntime::Available(fixture.store));
    let thread_store = cognitive_thread_store();
    let turn_store = ExtensionData::new("turn-structured-kg-physical-channels");
    prepare(
        &extension,
        &thread_store,
        &turn_store,
        &fixture.workspace,
        "Luminous Initiative",
    )
    .await;
    let proposal = propose(
        &extension,
        &thread_store,
        &turn_store,
        &fixture.workspace,
        "model-provider-attempt:v1:structured-kg-channels",
    )
    .await
    .expect("physical attachment");
    let attachment: serde_json::Value =
        serde_json::from_str(&proposal.into_content()).expect("attachment JSON");
    let memory = attachment["memories"]
        .as_array()
        .expect("memories")
        .iter()
        .find(|memory| {
            memory["memory_id"] == written.memory.id.memory_id.as_str()
                && memory["revision"] == written.memory.id.revision
        })
        .expect("KG memory in physical attachment");
    assert_eq!(
        memory["channels"],
        serde_json::json!(["entity_fts", "graph_one_hop", "recency"])
    );
}

#[tokio::test]
async fn kg_generation_drift_fails_open_without_a_physical_attachment() {
    let fixture = cognitive_fixture().await;
    let recall = Arc::new(GenerationDriftRecallBackend {
        store: fixture.store.clone(),
    });
    let extension = CognitiveExtension::with_recall(fixture.store, recall);
    let thread_store = cognitive_thread_store();
    let turn_store = ExtensionData::new("turn-generation-drift");
    prepare(
        &extension,
        &thread_store,
        &turn_store,
        &fixture.workspace,
        "rust durability",
    )
    .await;

    assert!(
        propose(
            &extension,
            &thread_store,
            &turn_store,
            &fixture.workspace,
            "model-provider-attempt:v1:generation-drift",
        )
        .await
        .is_none()
    );
}

#[tokio::test]
async fn one_stale_memory_drops_the_entire_two_memory_physical_attachment() {
    let fixture = cognitive_fixture().await;
    let now = now_unix_seconds().expect("time");
    let second_citation = fixture
        .store
        .append_source(
            &fixture.access,
            &SourceDraft {
                scope: fixture.scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "seed-rust-second".to_string(),
                content: b"rust".to_vec(),
                observed_at_unix_seconds: now,
            },
        )
        .await
        .expect("second source");
    fixture
        .store
        .remember_memory(
            &fixture.access,
            &MemoryDraft {
                stable_key: "rust-durability-snapshot".to_string(),
                revision: MemoryRevisionDraft {
                    scope: fixture.scope.clone(),
                    content: "rust".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: now,
                    valid_to_unix_seconds: None,
                    citations: vec![second_citation],
                },
            },
        )
        .await
        .expect("second memory");
    let backend = Arc::new(PartialBatchDriftRecallBackend {
        store: Arc::clone(&fixture.store),
        batch_calls: AtomicUsize::new(0),
    });
    let extension = CognitiveExtension::with_recall(fixture.store, backend.clone());
    let thread_store = cognitive_thread_store();
    let turn_store = ExtensionData::new("turn-partial-batch-drift");
    prepare(
        &extension,
        &thread_store,
        &turn_store,
        &fixture.workspace,
        "rust durability",
    )
    .await;
    assert_eq!(
        turn_store
            .get::<PreparedCognitiveAttachment>()
            .expect("prepared attachment")
            .bindings
            .len(),
        2
    );

    assert!(
        propose(
            &extension,
            &thread_store,
            &turn_store,
            &fixture.workspace,
            "model-provider-attempt:v1:partial-batch-drift",
        )
        .await
        .is_none()
    );

    let session_store = ExtensionData::new("session-combined-cognitive");
    let base = ModelProviderSha256Digest::parse("2".repeat(64)).expect("digest");
    let input = EphemeralModelInputContext {
        schema_version: EPHEMERAL_MODEL_INPUT_SCHEMA_VERSION,
        session_store: &session_store,
        thread_store: &thread_store,
        turn_store: &turn_store,
        attempt_id: "model-provider-attempt:v1:combined-partial-batch-drift",
        base_logical_request_sha256: &base,
        thread_id: THREAD_ID,
        turn_id: turn_store.level_id(),
        cwd: &fixture.workspace,
        request_kind: ModelProviderRequestKind::Turn,
        provider_id: "provider-cognitive",
        model: "model-cognitive",
        transport: ModelProviderTransport::Http,
        generate: true,
        model_context_window: Some(128_000),
        max_content_bytes: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_BYTES,
        max_content_tokens: EPHEMERAL_MODEL_INPUT_MAX_CONTENT_TOKENS,
    };
    assert!(
        extension
            .revalidate_prepared_attachment(&input)
            .await
            .is_none()
    );
    assert_eq!(backend.batch_calls.load(Ordering::SeqCst), 2);
}

#[tokio::test]
async fn prepared_revision_is_dropped_after_correction_and_after_tombstone() {
    let fixture = cognitive_fixture().await;
    let backend = Arc::new(CountingRecallBackend::new(fixture.store.clone()));
    let extension = CognitiveExtension::with_recall(fixture.store.clone(), backend.clone());
    let thread_store = cognitive_thread_store();
    let correction_turn = ExtensionData::new("turn-before-correction");
    prepare(
        &extension,
        &thread_store,
        &correction_turn,
        &fixture.workspace,
        "rust durability",
    )
    .await;

    let now = now_unix_seconds().expect("time");
    let correction_citation = fixture
        .store
        .append_source(
            &fixture.access,
            &SourceDraft {
                scope: fixture.scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "correct-rust-durability".to_string(),
                content: b"rust durability is still required".to_vec(),
                observed_at_unix_seconds: now,
            },
        )
        .await
        .expect("correction source");
    fixture
        .store
        .correct_memory(
            &fixture.access,
            &fixture.memory.id.memory_id,
            1,
            &MemoryRevisionDraft {
                scope: fixture.scope.clone(),
                content: "rust durability is still required".to_string(),
                verification: MemoryVerification::Verified,
                lifecycle: MemoryLifecycleState::Active,
                valid_from_unix_seconds: now,
                valid_to_unix_seconds: None,
                citations: vec![correction_citation],
            },
        )
        .await
        .expect("correction");
    assert!(
        propose(
            &extension,
            &thread_store,
            &correction_turn,
            &fixture.workspace,
            "model-provider-attempt:v1:after-correction",
        )
        .await
        .is_none()
    );

    let tombstone_turn = ExtensionData::new("turn-before-tombstone");
    prepare(
        &extension,
        &thread_store,
        &tombstone_turn,
        &fixture.workspace,
        "rust durability",
    )
    .await;
    let tombstone_citation = fixture
        .store
        .append_source(
            &fixture.access,
            &SourceDraft {
                scope: fixture.scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "forget-rust-durability".to_string(),
                content: b"forget rust durability".to_vec(),
                observed_at_unix_seconds: now,
            },
        )
        .await
        .expect("tombstone source");
    fixture
        .store
        .forget_memory(
            &fixture.access,
            &fixture.memory.id.memory_id,
            2,
            &ForgetMemoryDraft {
                scope: fixture.scope,
                reason: "explicitly withdrawn".to_string(),
                valid_from_unix_seconds: now,
                citations: vec![tombstone_citation],
            },
        )
        .await
        .expect("tombstone");
    assert!(
        propose(
            &extension,
            &thread_store,
            &tombstone_turn,
            &fixture.workspace,
            "model-provider-attempt:v1:after-tombstone",
        )
        .await
        .is_none()
    );
    assert_eq!(backend.retrieve_calls.load(Ordering::SeqCst), 2);
    assert_eq!(backend.revalidate_calls.load(Ordering::SeqCst), 2);
}
