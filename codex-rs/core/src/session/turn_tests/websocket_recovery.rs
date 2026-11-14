use super::super::SessionTurnRecoveryRequestCheckpoint;
use super::super::turn_recovery_environment_selections;
use crate::client::TurnRecoveryRequestCheckpoint;
use crate::model_provider_policy::ModelProviderPolicyContext;
use crate::model_provider_policy::canonical_sha256;
use crate::model_provider_policy::prepare_model_provider_policy;
use crate::responses_metadata::CodexResponsesMetadata;
use crate::responses_metadata::CodexResponsesRequestKind;
use crate::session::SessionSettingsUpdate;
use crate::state::TurnRecoveryAuthority;
use crate::tasks::RecoveryDispatchArm;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderTransport;
use codex_protocol::error::CodexErrorDetails;
use core_test_support::test_codex::local_selections;
use std::sync::Arc;

#[tokio::test]
async fn websocket_recovery_rejects_changed_request_metadata_before_sampling() {
    let (session, _) = crate::session::tests::make_session_and_context().await;
    let session = Arc::new(session);
    let config = session.get_config().await;
    session
        .update_settings(SessionSettingsUpdate {
            environments: Some(local_selections(config.cwd.clone())),
            ..Default::default()
        })
        .await
        .expect("explicit thread-derived environment");
    let turn_context = session
        .new_default_turn_with_sub_id("recovery-turn".to_string())
        .await;
    let registry = ExtensionRegistryBuilder::<crate::config::Config>::new().build();
    let session_store = ExtensionData::new("session");
    let thread_store = ExtensionData::new(session.thread_id.to_string());
    let turn_store = ExtensionData::new(turn_context.sub_id.clone());
    let context = ModelProviderPolicyContext {
        registry: &registry,
        session_store: &session_store,
        thread_store: &thread_store,
        turn_store: &turn_store,
        thread_id: session.thread_id.to_string(),
        turn_id: turn_context.sub_id.clone(),
        request_kind: ModelProviderRequestKind::Turn,
        ephemeral_input_cwd: None,
    };
    let request = serde_json::json!({"model": "model-a", "input": ["hello"]});
    let prepared = prepare_model_provider_policy(
        &context,
        "provider-a",
        "model-a",
        ModelProviderTransport::WebSocket,
        "wss://deployment.example.test/v1/responses",
        &request,
        &request,
        None,
        true,
    )
    .expect("prepared request");
    let mut metadata = CodexResponsesMetadata::new(
        "installation-a".to_string(),
        "session-a".to_string(),
        session.thread_id.to_string(),
        "window-a".to_string(),
    );
    metadata.request_kind = Some(CodexResponsesRequestKind::Turn);
    let fingerprint = |metadata: &CodexResponsesMetadata| {
        prepared
            .turn_recovery_fingerprint(
                &http::HeaderMap::new(),
                None,
                &metadata.turn_recovery_compatibility_projection(),
                None,
                false,
            )
            .expect("request recovery fingerprint")
            .as_str()
            .to_string()
    };
    let expected = fingerprint(&metadata);
    let replay = codex_history::TurnRecoveryReplayV1 {
        history_boundary: session
            .current_recovery_history_boundary()
            .await
            .expect("history boundary"),
        turn_context_sha256: canonical_sha256(&turn_context.to_turn_context_item())
            .expect("context digest")
            .as_str()
            .to_string(),
        start: metadata.turn_recovery_start_state(None),
        environments: turn_recovery_environment_selections(&turn_context.environments)
            .expect("thread-derived environments"),
    };
    assert!(!replay.environments.is_empty());
    type MetadataChange = fn(&mut CodexResponsesMetadata);
    let changes: [(&str, MetadataChange); 7] = [
        ("sandbox mode", |value| {
            value.sandbox_mode = Some("workspace-write".to_string())
        }),
        ("parent turn", |value| {
            value.parent_turn_id = Some("different-parent".to_string())
        }),
        ("root turn", |value| {
            value.root_turn_id = Some("different-root".to_string())
        }),
        ("request kind", |value| {
            value.request_kind = Some(CodexResponsesRequestKind::Prewarm)
        }),
        ("node review", |value| {
            value.node_repl_auto_review_required = Some(true)
        }),
        ("node disabled", |value| {
            value.node_repl_disabled = Some(true)
        }),
        ("extra", |value| {
            value
                .extra
                .insert("request_tag".to_string(), "changed".to_string());
        }),
    ];
    for (name, change) in changes {
        let mut changed = metadata.clone();
        change(&mut changed);
        let arm = Arc::new(RecoveryDispatchArm::new(Some(expected.clone())));
        let checkpoint = SessionTurnRecoveryRequestCheckpoint {
            session: Arc::clone(&session),
            turn_id: turn_context.sub_id.clone(),
            authority: Arc::new(TurnRecoveryAuthority::resumed_at_unready_generation(1)),
            persistence_failure_baseline: session.rollout_persistence_failure_generation(),
            replay: Some(replay.clone()),
            arm: Arc::clone(&arm),
        };
        let error = checkpoint
            .authorize(&fingerprint(&changed))
            .await
            .expect_err("incompatible recovery must reject before authorizing sampling");
        assert!(
            matches!(error.details(), CodexErrorDetails::Fatal(message) if message == "turn recovery request fingerprint changed after restart"),
            "{name}: {error:?}"
        );
        assert!(
            !arm.is_open(),
            "{name} must close the physical dispatch arm"
        );
        let repeated = checkpoint
            .authorize(&expected)
            .await
            .expect_err("rejected arm stays closed");
        assert!(
            matches!(repeated.details(), CodexErrorDetails::TurnAborted),
            "{name}: returning to the old fingerprint must not reopen the rejected arm"
        );
    }
}
