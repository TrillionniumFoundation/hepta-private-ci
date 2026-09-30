use super::*;

use std::sync::Arc;
use std::sync::Mutex as StdMutex;

use codex_extension_api::ContextContributor;
use codex_extension_api::ExtensionData;
use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyContributor;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTerminal;
use codex_extension_api::ModelProviderTransport;
use codex_extension_api::TurnContextContributionInput;
use codex_protocol::ThreadId;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn provider_digest(value: &str) -> ModelProviderSha256Digest {
    ModelProviderSha256Digest::parse(digest(value).to_string())
        .unwrap_or_else(|error| panic!("valid provider digest: {}", error.detail()))
}

fn attachment() -> PromptRuntimeAttachmentV1 {
    PromptRuntimeAttachmentV1::new(
        id("compilation:prompt-runtime"),
        digest("context-attachment"),
        digest("context-payload"),
        "gpt-test",
        current_unix_ms()
            .unwrap_or_else(|error| panic!("clock: {error}"))
            .saturating_add(60_000),
        vec![
            PromptRuntimeDeveloperFragmentV1::new("Inspect evidence before mutation.")
                .unwrap_or_else(|error| panic!("fragment: {error}")),
        ],
    )
    .unwrap_or_else(|error| panic!("attachment: {error}"))
}

fn host(
    dispatch_records: Arc<StdMutex<Vec<PromptRuntimeDispatchRecordV1>>>,
    terminal_records: Arc<StdMutex<Vec<PromptRuntimeTerminalRecordV1>>>,
) -> PromptRuntimeHost {
    let prepared_attachment = attachment();
    PromptRuntimeHost::new(
        "prompt-runtime-test",
        move |_request| {
            let attachment = prepared_attachment.clone();
            Box::pin(async move { Ok(Some(attachment)) })
        },
        move |record| {
            let dispatch_records = Arc::clone(&dispatch_records);
            Box::pin(async move {
                dispatch_records
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .push(record);
                Ok(())
            })
        },
        move |record| {
            let terminal_records = Arc::clone(&terminal_records);
            Box::pin(async move {
                terminal_records
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .push(record);
                Ok(())
            })
        },
    )
    .unwrap_or_else(|error| panic!("host: {error}"))
}

fn stores() -> (ExtensionData, ExtensionData, ExtensionData) {
    (
        ExtensionData::new("session:prompt-runtime"),
        ExtensionData::new("00000000-0000-4000-8000-000000000001"),
        ExtensionData::new("turn:prompt-runtime"),
    )
}

#[tokio::test]
async fn developer_attachment_reaches_physical_provider_terminal_observation() {
    let dispatches = Arc::new(StdMutex::new(Vec::new()));
    let records = Arc::new(StdMutex::new(Vec::new()));
    let extension = PromptRuntimeExtension {
        host: host(Arc::clone(&dispatches), Arc::clone(&records)),
    };
    let (session_store, thread_store, turn_store) = stores();
    let thread_id =
        ThreadId::from_string(thread_store.level_id()).unwrap_or_else(|error| panic!("{error}"));

    let fragments = extension
        .contribute_turn_context(TurnContextContributionInput {
            thread_id,
            turn_id: turn_store.level_id(),
            session_store: &session_store,
            thread_store: &thread_store,
            turn_store: &turn_store,
            model_context_window: Some(128_000),
        })
        .await;
    assert_eq!(fragments.len(), 1);
    assert_eq!(fragments[0].text(), "Inspect evidence before mutation.");

    let provider_config = provider_digest("provider-config");
    let endpoint = provider_digest("endpoint");
    let logical = provider_digest("logical-request");
    let wire = provider_digest("wire-request");
    let decision = extension
        .begin(ModelProviderInvocationInput {
            schema_version: codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION,
            session_store: &session_store,
            thread_store: &thread_store,
            turn_store: &turn_store,
            attempt_id: "provider-attempt:1",
            request_binding_id: "provider-request:1",
            thread_id: thread_store.level_id(),
            turn_id: turn_store.level_id(),
            request_kind: ModelProviderRequestKind::Turn,
            provider_id: "test-provider",
            provider_config_sha256: &provider_config,
            model: "gpt-test",
            transport: ModelProviderTransport::Http,
            endpoint_sha256: &endpoint,
            logical_request_sha256: &logical,
            wire_semantic_sha256: &wire,
            ephemeral_input_sha256: None,
            ephemeral_input_witness_sha256: None,
            previous_response_id_sha256: None,
            generate: true,
        })
        .await
        .unwrap_or_else(|error| panic!("provider begin: {}", error.detail()));
    let ModelProviderPolicyDecision::Allow { lease } = decision else {
        panic!("exercise-bound prompt must admit the physical provider send");
    };
    {
        let dispatches = dispatches
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        assert_eq!(dispatches.len(), 1);
        assert_eq!(dispatches[0].attempt_id, "provider-attempt:1");
        assert_eq!(
            dispatches[0].provider_request_digest,
            Digest32::from_str(wire.as_str()).unwrap_or_else(|error| panic!("{error}"))
        );
    }
    lease
        .finish(ModelProviderTerminal::Completed {
            response_id_sha256: provider_digest("response-id"),
            response_items_sha256: provider_digest("response-items"),
            token_usage_sha256: provider_digest("token-usage"),
            end_turn: Some(true),
        })
        .await
        .unwrap_or_else(|error| panic!("provider terminal: {}", error.detail()));

    let records = records
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    assert_eq!(records.len(), 1);
    let record = &records[0];
    assert_eq!(record.outcome, PromptRuntimeTerminalOutcomeV1::Delivered);
    assert_eq!(
        record.provider_request_digest,
        Digest32::from_str(wire.as_str()).unwrap_or_else(|error| panic!("{error}"))
    );
    let observation = record.delivery_observation.as_ref().unwrap_or_else(|| {
        panic!("completed provider send must yield canonical delivery evidence")
    });
    assert!(observation.delivered);
    assert_eq!(observation.compilation_id, id("compilation:prompt-runtime"));
    record
        .validate()
        .unwrap_or_else(|error| panic!("record: {error}"));
}

#[tokio::test]
async fn not_dispatched_never_fabricates_delivery_credit() {
    let dispatches = Arc::new(StdMutex::new(Vec::new()));
    let records = Arc::new(StdMutex::new(Vec::new()));
    let extension = PromptRuntimeExtension {
        host: host(Arc::clone(&dispatches), Arc::clone(&records)),
    };
    let (session_store, thread_store, turn_store) = stores();
    let thread_id =
        ThreadId::from_string(thread_store.level_id()).unwrap_or_else(|error| panic!("{error}"));
    let _ = extension
        .contribute_turn_context(TurnContextContributionInput {
            thread_id,
            turn_id: turn_store.level_id(),
            session_store: &session_store,
            thread_store: &thread_store,
            turn_store: &turn_store,
            model_context_window: None,
        })
        .await;

    let provider_config = provider_digest("provider-config:2");
    let endpoint = provider_digest("endpoint:2");
    let logical = provider_digest("logical-request:2");
    let wire = provider_digest("wire-request:2");
    let decision = extension
        .begin(ModelProviderInvocationInput {
            schema_version: codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION,
            session_store: &session_store,
            thread_store: &thread_store,
            turn_store: &turn_store,
            attempt_id: "provider-attempt:2",
            request_binding_id: "provider-request:2",
            thread_id: thread_store.level_id(),
            turn_id: turn_store.level_id(),
            request_kind: ModelProviderRequestKind::Turn,
            provider_id: "test-provider",
            provider_config_sha256: &provider_config,
            model: "gpt-test",
            transport: ModelProviderTransport::Http,
            endpoint_sha256: &endpoint,
            logical_request_sha256: &logical,
            wire_semantic_sha256: &wire,
            ephemeral_input_sha256: None,
            ephemeral_input_witness_sha256: None,
            previous_response_id_sha256: None,
            generate: true,
        })
        .await
        .unwrap_or_else(|error| panic!("provider begin: {}", error.detail()));
    let ModelProviderPolicyDecision::Allow { lease } = decision else {
        panic!("provider send should reach the real terminal owner");
    };
    assert_eq!(
        dispatches
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .len(),
        1
    );
    lease
        .finish(ModelProviderTerminal::NotDispatched {
            reason_code: "cancelled_before_send".to_owned(),
        })
        .await
        .unwrap_or_else(|error| panic!("terminal: {}", error.detail()));

    let records = records
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    assert_eq!(records.len(), 1);
    assert_eq!(
        records[0].outcome,
        PromptRuntimeTerminalOutcomeV1::NotDispatched
    );
    assert!(records[0].delivery_observation.is_none());
    records[0]
        .validate()
        .unwrap_or_else(|error| panic!("record: {error}"));
}

#[tokio::test]
async fn cached_prompt_revalidates_owner_withdrawal_before_provider_begin() {
    let withdrawn = Arc::new(AtomicBool::new(false));
    let dispatch_count = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let prepared = attachment();
    let flag = Arc::clone(&withdrawn);
    let counter = Arc::clone(&dispatch_count);
    let host = PromptRuntimeHost::new(
        "prompt-runtime-cache-withdrawal",
        move |_| {
            let result = if flag.load(Ordering::Acquire) {
                Err(PromptRuntimeHostError::new(
                    "prompt_final_use_revoked",
                    "selection revoked",
                ))
            } else {
                Ok(Some(prepared.clone()))
            };
            Box::pin(std::future::ready(result))
        },
        move |_| {
            counter.fetch_add(1, Ordering::Relaxed);
            Box::pin(std::future::ready(Ok(())))
        },
        |_| Box::pin(std::future::ready(Ok(()))),
    )
    .unwrap_or_else(|error| panic!("host: {error}"));
    let extension = PromptRuntimeExtension { host };
    let (session_store, thread_store, turn_store) = stores();
    let thread_id = ThreadId::from_string(thread_store.level_id())
        .unwrap_or_else(|error| panic!("thread: {error}"));
    assert_eq!(
        extension
            .contribute_turn_context(TurnContextContributionInput {
                thread_id,
                turn_id: turn_store.level_id(),
                session_store: &session_store,
                thread_store: &thread_store,
                turn_store: &turn_store,
                model_context_window: Some(128_000),
            })
            .await
            .len(),
        1
    );
    withdrawn.store(true, Ordering::Release);
    let provider_config = provider_digest("config");
    let endpoint = provider_digest("endpoint");
    let logical = provider_digest("logical");
    let wire = provider_digest("wire");
    let result = extension
        .begin(ModelProviderInvocationInput {
            schema_version: codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION,
            session_store: &session_store,
            thread_store: &thread_store,
            turn_store: &turn_store,
            attempt_id: "provider-attempt:cache",
            request_binding_id: "provider-request:cache",
            thread_id: thread_store.level_id(),
            turn_id: turn_store.level_id(),
            request_kind: ModelProviderRequestKind::Turn,
            provider_id: "test-provider",
            provider_config_sha256: &provider_config,
            model: "gpt-test",
            transport: ModelProviderTransport::Http,
            endpoint_sha256: &endpoint,
            logical_request_sha256: &logical,
            wire_semantic_sha256: &wire,
            ephemeral_input_sha256: None,
            ephemeral_input_witness_sha256: None,
            previous_response_id_sha256: None,
            generate: true,
        })
        .await;
    let error = match result {
        Err(error) => error,
        Ok(_) => panic!("withdrawn cached context must block provider begin"),
    };
    assert_eq!(error.reason_code(), "prompt_final_use_revoked");
    assert_eq!(dispatch_count.load(Ordering::Relaxed), 0);
}

#[tokio::test]
async fn cached_prompt_never_silently_switches_injected_payload() {
    let changed = Arc::new(AtomicBool::new(false));
    let initial = attachment();
    let mut replacement = initial.clone();
    replacement.developer_fragments = vec![
        PromptRuntimeDeveloperFragmentV1::new("different reviewed material")
            .unwrap_or_else(|error| panic!("fragment: {error}")),
    ];
    replacement.source_binding_digest = replacement.compute_binding_digest();
    let flag = Arc::clone(&changed);
    let host = PromptRuntimeHost::new(
        "prompt-runtime-cache-drift",
        move |_| {
            let value = if flag.load(Ordering::Acquire) {
                replacement.clone()
            } else {
                initial.clone()
            };
            Box::pin(std::future::ready(Ok(Some(value))))
        },
        |_| Box::pin(std::future::ready(Ok(()))),
        |_| Box::pin(std::future::ready(Ok(()))),
    )
    .unwrap_or_else(|error| panic!("host: {error}"));
    let extension = PromptRuntimeExtension { host };
    let (_, thread_store, turn_store) = stores();
    assert!(matches!(
        extension
            .resolve(
                thread_store.level_id().to_owned(),
                turn_store.level_id().to_owned(),
                None,
                &turn_store
            )
            .await,
        ResolvedAttachment::Ready(_)
    ));
    changed.store(true, Ordering::Release);
    let result = extension
        .resolve(
            thread_store.level_id().to_owned(),
            turn_store.level_id().to_owned(),
            None,
            &turn_store,
        )
        .await;
    match result {
        ResolvedAttachment::Failed(error) => {
            assert_eq!(error.reason_code(), "prompt_runtime_cached_binding_changed")
        }
        _ => panic!("cached identity drift must fail closed"),
    }
}

#[tokio::test]
async fn concurrent_initial_resolution_is_single_flight() {
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let counter = Arc::clone(&calls);
    let prepared = attachment();
    let host = PromptRuntimeHost::new(
        "prompt-runtime-single-flight",
        move |_| {
            counter.fetch_add(1, Ordering::AcqRel);
            let prepared = prepared.clone();
            Box::pin(async move {
                tokio::task::yield_now().await;
                Ok(Some(prepared))
            })
        },
        |_| Box::pin(std::future::ready(Ok(()))),
        |_| Box::pin(std::future::ready(Ok(()))),
    )
    .unwrap_or_else(|error| panic!("host: {error}"));
    let extension = PromptRuntimeExtension { host };
    let (_, thread_store, turn_store) = stores();
    let first = extension.resolve(
        thread_store.level_id().to_owned(),
        turn_store.level_id().to_owned(),
        None,
        &turn_store,
    );
    let second = extension.resolve(
        thread_store.level_id().to_owned(),
        turn_store.level_id().to_owned(),
        None,
        &turn_store,
    );
    let (first, second) = tokio::join!(first, second);
    assert!(matches!(first, ResolvedAttachment::Ready(_)));
    assert!(matches!(second, ResolvedAttachment::Ready(_)));
    assert_eq!(calls.load(Ordering::Acquire), 1);
}
