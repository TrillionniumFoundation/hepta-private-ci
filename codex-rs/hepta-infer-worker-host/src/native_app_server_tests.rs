use super::*;
use codex_app_server_client::RemoteAppServerObservedEvent;
use codex_app_server_protocol::AgentMessageDeltaNotification;
use codex_app_server_protocol::ItemCompletedNotification;
use codex_app_server_protocol::ItemStartedNotification;
use codex_app_server_protocol::Turn;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnItemsView;
use codex_app_server_protocol::TurnStartedNotification;

fn binding() -> CodexTurnBinding {
    let payload_digest = Digest32::of_bytes(b"test-turn-payload");
    CodexTurnBinding {
        intent: CodexOperationIntent {
            operation_id: StableId::new("operation:test").unwrap(),
            thread_id: StableId::new("thread-a").unwrap(),
            method_id: StableId::new("turn.start").unwrap(),
            payload_digest,
            lease_payload_digest: payload_digest,
            deadline_ms: 10_000,
            app_server_binding: Some(AppServerRequestBinding {
                source_admission_digest: Digest32::of_bytes(b"test-durable-admission"),
                agent_generation: Generation::new(1).unwrap(),
                session_id: StableId::new("session-a").unwrap(),
                client_user_message_id: StableId::new("message-a").unwrap(),
                user_input_digest: Digest32::of_bytes(b"test-user-input"),
                protocol_id: StableId::new(APP_SERVER_V2_PROTOCOL_ID).unwrap(),
                app_server_version: "test-app-server".to_string(),
                codex_home_digest: Digest32::of_bytes(b"/home/agent"),
                connection_id: 7,
            }),
        },
        turn_id: StableId::new("turn-a").unwrap(),
    }
}

fn observed(notification: ServerNotification) -> RemoteAppServerObservedEvent {
    RemoteAppServerObservedEvent::from_test_event(
        AppServerEvent::ServerNotification(Box::new(notification)),
        7,
        Some("test-app-server".to_string()),
        Some("/home/agent".to_string()),
    )
}

fn observe_for_test(
    messages: &mut NativeMessageOutput,
    output: &mut NativeRunOutput,
    notification: ServerNotification,
) -> std::result::Result<bool, String> {
    let binding = binding();
    observe_event(output, messages, &observed(notification), &binding)
}

fn output() -> NativeRunOutput {
    NativeRunOutput {
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        model: "provider-model".to_string(),
        model_provider: "provider".to_string(),
        status: NativeRunStatus::Indeterminate,
        boundary_status: NativeBoundaryStatus::Indeterminate,
        output: String::new(),
        observed_output_tokens: None,
        terminal_observed: false,
        stop_reason: None,
        owner_authority: NativeOwnerAuthority::Unverified,
        codex_terminal_correlation_digest: None,
    }
}

fn terminal(thread: &str, turn: &str, status: TurnStatus) -> ServerNotification {
    ServerNotification::TurnCompleted(TurnCompletedNotification {
        thread_id: thread.to_string(),
        turn: Turn {
            id: turn.to_string(),
            items: Vec::new(),
            items_view: TurnItemsView::Full,
            status,
            error: None,
            started_at: None,
            completed_at: None,
            duration_ms: None,
        },
    })
}

fn message_delta(thread: &str, turn: &str, item: &str, text: &str) -> ServerNotification {
    ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
        thread_id: thread.to_string(),
        turn_id: turn.to_string(),
        item_id: item.to_string(),
        delta: text.to_string(),
    })
}

fn message_item(item: &str, text: &str) -> ThreadItem {
    ThreadItem::AgentMessage {
        id: item.to_string(),
        text: text.to_string(),
        phase: None,
        memory_citation: None,
        delivery: None,
    }
}

fn message_completed(thread: &str, turn: &str, item: &str, text: &str) -> ServerNotification {
    ServerNotification::ItemCompleted(ItemCompletedNotification {
        thread_id: thread.to_string(),
        turn_id: turn.to_string(),
        item: message_item(item, text),
        completed_at_ms: 0,
    })
}

fn message_started(item: &str) -> ServerNotification {
    ServerNotification::ItemStarted(ItemStartedNotification {
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        item: message_item(item, ""),
        started_at_ms: 0,
    })
}

#[test]
fn completed_agent_message_preserves_output_without_any_delta() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    assert!(
        !observe_for_test(
            &mut messages,
            &mut output,
            message_completed("thread-a", "turn-a", "message", "fresh context accepted"),
        )
        .unwrap()
    );
    assert_eq!(output.output, "fresh context accepted");
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(!output.terminal_observed);
    assert!(!output.succeeded());
}

#[test]
fn completed_agent_message_corrects_streamed_text_without_duplication() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    observe_for_test(
        &mut messages,
        &mut output,
        message_delta("thread-a", "turn-a", "message", "partial text"),
    )
    .unwrap();
    for text in ["final text", "final text", "corrected final text"] {
        observe_for_test(
            &mut messages,
            &mut output,
            message_completed("thread-a", "turn-a", "message", text),
        )
        .unwrap();
        assert_eq!(output.output, text);
    }
    observe_for_test(
        &mut messages,
        &mut output,
        message_delta("thread-a", "turn-a", "message", " late delta"),
    )
    .unwrap();
    assert_eq!(output.output, "corrected final text late delta");
    observe_for_test(
        &mut messages,
        &mut output,
        message_completed("thread-a", "turn-a", "message", "corrected final text"),
    )
    .unwrap();
    assert_eq!(output.output, "corrected final text");
}

#[test]
fn multiple_agent_messages_keep_item_order_across_snapshots_and_deltas() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    for notification in [
        message_started("first"),
        message_started("second"),
        message_completed("thread-a", "turn-a", "second", "second"),
        message_delta("thread-a", "turn-a", "first", "partial"),
        message_completed("thread-a", "turn-a", "first", "first"),
        message_completed("thread-a", "turn-a", "third", "third"),
        message_completed("thread-a", "turn-a", "first", "first"),
    ] {
        observe_for_test(&mut messages, &mut output, notification).unwrap();
    }
    assert_eq!(output.output, "firstsecondthird");
}

#[test]
fn completed_agent_messages_require_exact_thread_turn_and_preserve_opaque_item_identity() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    for notification in [
        message_completed("unrelated", "turn-a", "message", "discard"),
        message_completed("thread-a", "unrelated", "message", "discard"),
        message_delta("thread-a", "unrelated", "message", "discard"),
    ] {
        observe_for_test(&mut messages, &mut output, notification).unwrap();
    }
    assert!(output.output.is_empty());
    assert!(messages.items.is_empty());
    for notification in [
        message_started(""),
        message_delta("thread-a", "turn-a", "", "partial"),
        message_completed("thread-a", "turn-a", "", "complete"),
    ] {
        observe_for_test(&mut messages, &mut output, notification).unwrap();
    }
    assert_eq!(output.output, "complete");
    assert_eq!(messages.items.len(), 1);
}

#[test]
fn agent_message_item_identity_budget_bounds_empty_messages_without_mutating_on_rejection() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    let exact_limit_id = "x".repeat(MAX_OUTPUT_BYTES);
    for notification in [
        message_started(&exact_limit_id),
        message_delta("thread-a", "turn-a", &exact_limit_id, "accepted"),
        message_completed("thread-a", "turn-a", &exact_limit_id, "accepted"),
        message_started(&exact_limit_id),
    ] {
        observe_for_test(&mut messages, &mut output, notification).unwrap();
    }
    assert_eq!(output.output, "accepted");
    assert_eq!(messages.tracked_item_id_bytes, MAX_OUTPUT_BYTES);
    assert_eq!(messages.items.len(), 1);
    for notification in [
        message_started("another"),
        message_delta("thread-a", "turn-a", "another", ""),
        message_completed("thread-a", "turn-a", "another", ""),
    ] {
        assert_eq!(
            observe_for_test(&mut messages, &mut output, notification),
            Err("assistant message item id byte limit exceeded".to_string())
        );
        assert_eq!(output.output, "accepted");
        assert_eq!(messages.tracked_item_id_bytes, MAX_OUTPUT_BYTES);
        assert_eq!(messages.items.len(), 1);
        assert_eq!(messages.items[0].id, exact_limit_id);
        assert_eq!(messages.items[0].text, "accepted");
    }
}

#[test]
fn completed_agent_message_replacement_checks_total_bytes_before_mutating() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    observe_for_test(
        &mut messages,
        &mut output,
        message_completed("thread-a", "turn-a", "first", "first"),
    )
    .unwrap();
    observe_for_test(
        &mut messages,
        &mut output,
        message_delta("thread-a", "turn-a", "second", "b"),
    )
    .unwrap();
    assert!(
        observe_for_test(
            &mut messages,
            &mut output,
            message_completed(
                "thread-a",
                "turn-a",
                "second",
                &"x".repeat(MAX_OUTPUT_BYTES - 4)
            ),
        )
        .is_err()
    );
    assert_eq!(output.output, "firstb");
    observe_for_test(
        &mut messages,
        &mut output,
        message_completed(
            "thread-a",
            "turn-a",
            "second",
            &"x".repeat(MAX_OUTPUT_BYTES - 5),
        ),
    )
    .unwrap();
    assert_eq!(output.output.len(), MAX_OUTPUT_BYTES);
    assert!(
        observe_for_test(
            &mut messages,
            &mut output,
            message_completed("thread-a", "turn-a", "third", "x"),
        )
        .is_err()
    );
    assert_eq!(messages.items.len(), 2);
    assert_eq!(output.output.len(), MAX_OUTPUT_BYTES);
    observe_for_test(
        &mut messages,
        &mut output,
        message_completed("thread-a", "turn-a", "first", ""),
    )
    .unwrap();
    observe_for_test(
        &mut messages,
        &mut output,
        message_completed("thread-a", "turn-a", "third", "中"),
    )
    .unwrap();
    assert_eq!(output.output.len(), MAX_OUTPUT_BYTES - 2);
}

#[test]
fn completed_agent_message_limit_counts_utf8_bytes() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    let exact_limit = "é".repeat(MAX_OUTPUT_BYTES / 2);
    observe_for_test(
        &mut messages,
        &mut output,
        message_completed("thread-a", "turn-a", "message", &exact_limit),
    )
    .unwrap();
    assert_eq!(output.output.len(), MAX_OUTPUT_BYTES);
    assert!(
        observe_for_test(
            &mut messages,
            &mut output,
            message_completed(
                "thread-a",
                "turn-a",
                "message",
                &(exact_limit.clone() + "é")
            ),
        )
        .is_err()
    );
    assert_eq!(output.output, exact_limit);
}

#[test]
fn lost_turn_start_ack_reconciles_only_the_exact_in_progress_thread() {
    let started = |thread: &str, turn: &str, status: TurnStatus| {
        ServerNotification::TurnStarted(TurnStartedNotification {
            thread_id: thread.to_string(),
            turn: Turn {
                id: turn.to_string(),
                items: Vec::new(),
                items_view: TurnItemsView::NotLoaded,
                status,
                error: None,
                started_at: None,
                completed_at: None,
                duration_ms: None,
            },
        })
    };

    assert_eq!(
        exact_reconciled_turn(
            "thread-a",
            &observed(started("thread-b", "turn-a", TurnStatus::InProgress)),
        )
        .unwrap(),
        None
    );
    let recovered = exact_reconciled_turn(
        "thread-a",
        &observed(started(
            "thread-a",
            "turn-recovered",
            TurnStatus::InProgress,
        )),
    )
    .unwrap()
    .expect("exact turn/started must reconcile");
    assert_eq!(recovered.id, "turn-recovered");

    assert!(
        exact_reconciled_turn(
            "thread-a",
            &observed(started("thread-a", "turn-a", TurnStatus::Completed)),
        )
        .is_err()
    );
}

#[test]
fn only_the_bound_turn_can_complete_the_native_request() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    assert!(
        !observe_for_test(
            &mut messages,
            &mut output,
            terminal("thread-b", "turn-a", TurnStatus::Completed)
        )
        .unwrap()
    );
    assert!(
        !observe_for_test(
            &mut messages,
            &mut output,
            terminal("thread-a", "turn-b", TurnStatus::Completed)
        )
        .unwrap()
    );
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(
        observe_for_test(
            &mut messages,
            &mut output,
            terminal("thread-a", "turn-a", TurnStatus::Interrupted)
        )
        .unwrap()
    );
    assert_eq!(output.status, NativeRunStatus::Interrupted);
    assert_eq!(output.boundary_status, NativeBoundaryStatus::Interrupted);
    assert!(output.terminal_observed);
    assert!(output.codex_terminal_correlation_digest.is_some());
}

#[test]
fn output_is_observed_bounded_and_never_predeclares_success() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    let delta = |thread: &str, text: String| {
        ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
            thread_id: thread.to_string(),
            turn_id: "turn-a".to_string(),
            item_id: "item".to_string(),
            delta: text,
        })
    };
    observe_for_test(
        &mut messages,
        &mut output,
        delta("unrelated", "discard".to_string()),
    )
    .unwrap();
    observe_for_test(
        &mut messages,
        &mut output,
        delta("thread-a", "model output".to_string()),
    )
    .unwrap();
    assert_eq!(output.output, "model output");
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(
        observe_for_test(
            &mut messages,
            &mut output,
            delta("thread-a", "x".repeat(MAX_OUTPUT_BYTES))
        )
        .is_err()
    );
    assert_eq!(output.output, "model output");
    assert!(!output.terminal_observed);
}

#[test]
fn in_progress_is_not_a_terminal_observation() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    assert!(
        observe_for_test(
            &mut messages,
            &mut output,
            terminal("thread-a", "turn-a", TurnStatus::InProgress)
        )
        .is_err()
    );
    assert!(!output.terminal_observed);
}

#[test]
fn actual_usage_is_bound_monotonic_and_survives_terminal_failure() {
    use codex_app_server_protocol::ThreadTokenUsage;
    use codex_app_server_protocol::ThreadTokenUsageUpdatedNotification;
    use codex_app_server_protocol::TokenUsageBreakdown;
    use codex_app_server_protocol::TurnError;
    let usage = |thread: &str, tokens| {
        let counts = TokenUsageBreakdown {
            total_tokens: tokens,
            input_tokens: 0,
            cached_input_tokens: 0,
            cache_write_input_tokens: 0,
            output_tokens: tokens,
            reasoning_output_tokens: 0,
        };
        ServerNotification::ThreadTokenUsageUpdated(ThreadTokenUsageUpdatedNotification {
            thread_id: thread.to_string(),
            turn_id: "turn-a".to_string(),
            token_usage: ThreadTokenUsage {
                total: counts.clone(),
                last: counts,
                model_context_window: None,
            },
        })
    };
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    observe_for_test(&mut messages, &mut output, usage("unrelated", 99)).unwrap();
    assert_eq!(output.observed_output_tokens, None);
    observe_for_test(&mut messages, &mut output, usage("thread-a", 42)).unwrap();
    assert!(observe_for_test(&mut messages, &mut output, usage("thread-a", -1)).is_err());
    assert!(observe_for_test(&mut messages, &mut output, usage("thread-a", 41)).is_err());
    assert_eq!(output.observed_output_tokens, Some(42));
    let mut failed = terminal("thread-a", "turn-a", TurnStatus::Failed);
    if let ServerNotification::TurnCompleted(ref mut notification) = failed {
        notification.turn.error = Some(TurnError {
            message: "provider error".to_string(),
            codex_error_info: None,
            additional_details: None,
        });
    }
    assert!(observe_for_test(&mut messages, &mut output, failed).unwrap());
    assert_eq!(output.status, NativeRunStatus::Failed);
    assert_eq!(output.boundary_status, NativeBoundaryStatus::Failed);
    assert_eq!(output.observed_output_tokens, Some(42));
    assert_eq!(output.stop_reason.as_deref(), Some("provider error"));
    assert!(output.terminal_observed);
    assert!(output.codex_terminal_correlation_digest.is_some());
}

fn ready_owner() -> HealthSnapshot {
    HealthSnapshot {
        promotion_ready: true,
        ready: true,
        fenced: false,
        lifecycle: serde_json::from_value(serde_json::json!("running")).unwrap(),
        process_id: 1,
        workspace: PathBuf::from("/workspace"),
        home_root: PathBuf::from("/home/agent"),
        run_root: PathBuf::from("/run/agent"),
    }
}

#[tokio::test]
async fn owner_loss_stays_denied_after_interrupt_grace_observes_completed() {
    let mut not_ready = ready_owner();
    not_ready.ready = false;
    let mut fenced = ready_owner();
    fenced.fenced = true;
    for health in [
        Ok(not_ready),
        Ok(fenced),
        Err(AgentdError::GenerationFenced(
            "generation replaced".to_string(),
        )),
        Err(AgentdError::Protocol(
            "response generation mismatch".to_string(),
        )),
        Err(AgentdError::Io(std::io::Error::from(
            std::io::ErrorKind::ConnectionReset,
        ))),
    ] {
        // This output is bound to the started thread/turn. The same health
        // reducer runs in observe(), before its error triggers TurnInterrupt.
        let mut output = output();
        let mut messages = NativeMessageOutput::default();
        verify_owner_health(
            &mut output,
            async { Ok(ready_owner()) },
            Instant::now() + RPC_TIMEOUT,
        )
        .await
        .unwrap();
        output.observed_output_tokens = Some(42);
        observe_for_test(
            &mut messages,
            &mut output,
            message_delta("thread-a", "turn-a", "grace-message", "partial"),
        )
        .unwrap();
        assert!(
            verify_owner_health(&mut output, async { health }, Instant::now() + RPC_TIMEOUT)
                .await
                .is_err()
        );
        let lost = output.owner_authority.clone();
        assert_eq!(output.boundary_status, NativeBoundaryStatus::Quarantined);
        // Grace has no owner parameter: it can still establish provider facts.
        observe_for_test(
            &mut messages,
            &mut output,
            message_completed("thread-a", "turn-a", "grace-message", "complete text"),
        )
        .unwrap();
        assert!(
            observe_for_test(
                &mut messages,
                &mut output,
                terminal("thread-a", "turn-a", TurnStatus::Completed)
            )
            .unwrap()
        );
        assert_eq!(output.status, NativeRunStatus::Completed);
        assert_eq!(output.boundary_status, NativeBoundaryStatus::Quarantined);
        assert_eq!(output.observed_output_tokens, Some(42));
        assert_eq!(output.output, "complete text");
        assert!(output.terminal_observed);
        assert!(!output.succeeded());
        // A later ready response cannot restore authority for this attempt.
        assert!(
            verify_owner_health(
                &mut output,
                async { Ok(ready_owner()) },
                Instant::now() + RPC_TIMEOUT
            )
            .await
            .is_err()
        );
        assert_eq!(output.owner_authority, lost);
    }
}

#[tokio::test]
async fn owner_timeout_and_terminal_first_selection_cannot_authorize_success() {
    let mut timed_out = output();
    let mut messages = NativeMessageOutput::default();
    verify_owner_health(
        &mut timed_out,
        async { Ok(ready_owner()) },
        Instant::now() + RPC_TIMEOUT,
    )
    .await
    .unwrap();
    assert!(
        verify_owner_health(&mut timed_out, std::future::pending(), Instant::now())
            .await
            .is_err()
    );
    observe_for_test(
        &mut messages,
        &mut timed_out,
        terminal("thread-a", "turn-a", TurnStatus::Completed),
    )
    .unwrap();
    assert_eq!(timed_out.status, NativeRunStatus::Completed);
    assert_eq!(timed_out.observed_output_tokens, None);
    assert!(!timed_out.succeeded());

    let mut terminal_first = output();
    let mut messages = NativeMessageOutput::default();
    verify_owner_health(
        &mut terminal_first,
        async { Ok(ready_owner()) },
        Instant::now() + RPC_TIMEOUT,
    )
    .await
    .unwrap();
    // select! can consume Completed before a simultaneously ready health tick.
    observe_for_test(
        &mut messages,
        &mut terminal_first,
        terminal("thread-a", "turn-a", TurnStatus::Completed),
    )
    .unwrap();
    let mut fenced = ready_owner();
    fenced.fenced = true;
    // run_once always executes this final check after provider cleanup.
    assert!(
        verify_owner_health(
            &mut terminal_first,
            async { Ok(fenced) },
            Instant::now() + RPC_TIMEOUT
        )
        .await
        .is_err()
    );
    assert!(!terminal_first.succeeded());
    assert!(terminal_first.terminal_observed);
}

#[tokio::test]
async fn success_requires_both_matching_completion_and_final_ready_owner() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    observe_for_test(
        &mut messages,
        &mut output,
        terminal("thread-a", "turn-a", TurnStatus::Completed),
    )
    .unwrap();
    assert!(!output.succeeded());
    verify_owner_health(
        &mut output,
        async { Ok(ready_owner()) },
        Instant::now() + RPC_TIMEOUT,
    )
    .await
    .unwrap();
    assert_eq!(output.boundary_status, NativeBoundaryStatus::Succeeded);
    assert!(output.succeeded());
    output.status = NativeRunStatus::Interrupted;
    assert!(!output.succeeded());
}

#[test]
fn cognitive_final_use_revalidation_follows_durable_dispatch_and_precedes_turn_start() {
    let source = include_str!("native_app_server.rs");
    let durable_dispatch = source
        .find("control.dispatch_native_with_pre_effect_abort(")
        .expect("durable native dispatch");
    let revalidation = source
        .find("owner.revalidate_cognitive_context(snapshot).await")
        .expect("final-use cognitive revalidation");
    let turn_start = source
        .find("send_authorized_turn_start(&mut client, entered_use, turn_params)")
        .expect("token-bound physical turn start");
    let authority_entry = source
        .find("let entered_use = match verified_use.enter(&authority_binding)")
        .expect("final-use authority entry");
    let durable_stop = source
        .find("control.abort_native_before_effect(")
        .expect("durable pre-turn stop");
    assert!(durable_dispatch < revalidation);
    assert!(revalidation < turn_start);
    assert!(durable_stop < turn_start);
    assert!(revalidation < authority_entry);
    assert!(authority_entry < turn_start);

    let (_, send_helper) = source
        .split_once("async fn send_authorized_turn_start(")
        .expect("authorized send helper");
    let (send_helper, _) = send_helper
        .split_once("\n}")
        .expect("complete authorized send helper");
    assert!(send_helper.contains("_entered: EnteredUseToken"));
    assert!(send_helper.contains(".request_typed_observed(ClientRequest::TurnStart {"));
    assert_eq!(source.matches("ClientRequest::TurnStart {").count(), 1);
}

#[cfg(unix)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn real_agentd_worker_accepts_fresh_context_and_rejects_final_use_tombstone() -> Result<()> {
    use std::sync::Arc;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_agentd::test_support::CognitiveTestHost;
    use codex_hepta_infer_core::durable_control::DurableInferenceControl;
    use codex_hepta_infer_core::durable_control::native::NativeReservationState;
    use core_test_support::responses;

    const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
    const MODEL: &str = "mock-model";
    const ACCEPT_REQUEST_ID: &str = "cognitive-final-use-accept";
    const RACE_REQUEST_ID: &str = "cognitive-final-use-race";
    const CORRECTION_REQUEST_ID: &str = "cognitive-final-use-correction-race";
    const ACCEPT_MEMORY: &str = "verified lemon orchard worker positive marker";
    const RACE_MEMORY: &str = "verified nectarine orchard final-use marker";
    const CORRECTION_MEMORY: &str = "verified kumquat orchard final-use marker";
    const CORRECTED_MEMORY: &str = "corrected kumquat orchard final-use marker";

    let server = responses::start_mock_server().await;
    let response = responses::sse(vec![
        responses::ev_response_created("resp-cognitive-worker"),
        responses::ev_assistant_message("msg-cognitive-worker", "fresh context accepted"),
        responses::ev_completed("resp-cognitive-worker"),
    ]);
    let response_mock = responses::mount_sse_once(&server, response).await;

    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let root = std::env::temp_dir().join(format!("hepta-cognitive-worker-e2e-{nonce}"));
    let agent_id = codex_hepta_contracts::AgentId::parse(AGENT_ID)?;
    let host = CognitiveTestHost::start(
        root,
        agent_id,
        MODEL,
        &format!("{}/v1", server.uri()),
        core_test_support::cargo_bin("codex")?,
    )
    .await?;
    let _accepted_memory = host
        .seed_verified_memory("worker-final-use-accept", ACCEPT_MEMORY)
        .await?;

    let authority_directory = tempfile::tempdir()?;
    let (authorizer, issuer) = crate::final_use_authorizer::tests::independent_test_authorizer(
        authority_directory.path(),
        3,
    )
    .await?;
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: host.control_socket().to_path_buf(),
        agent_id: host.agent_id().clone(),
        generation: 1,
        model: MODEL.to_string(),
        timeout: Duration::from_secs(20),
    })?
    .with_turn_start_authorizer(Arc::new(authorizer));
    let journal = std::env::temp_dir().join(format!("hepta-cognitive-worker-e2e-{nonce}.journal"));
    let mut durable = DurableInferenceControl::open(&journal, 8)?;

    let accepted = driver
        .run(
            &mut durable,
            NativeAdmission {
                request_id: ACCEPT_REQUEST_ID.to_string(),
                maximum_in_flight: 1,
            },
            "answer from the verified memory".to_string(),
            Some("lemon".to_string()),
            &CancellationToken::new(),
        )
        .await?;
    assert!(
        accepted.succeeded(),
        "fresh context must reach a successful real TurnStart"
    );
    assert!(accepted.output.contains("fresh context accepted"));
    let accepted_record = durable
        .native_record(ACCEPT_REQUEST_ID)
        .cloned()
        .ok_or("missing durable accepted native record")?;
    assert_eq!(accepted_record.state, NativeReservationState::Released);
    assert!(accepted_record.dispatch.is_some());
    assert!(accepted_record.turn_id.is_some());
    assert_eq!(accepted_record.observation.as_ref(), Some(&accepted));
    assert_eq!(accepted_record.pre_dispatch_stop, None);

    assert_eq!(
        response_mock.requests().len(),
        1,
        "only the fresh-context run may reach the physical Responses API",
    );
    let requests = server.received_requests().await.unwrap_or_default();
    assert!(
        requests.iter().any(|request| {
            request.url.path().ends_with("/responses")
                && String::from_utf8_lossy(&request.body).contains(ACCEPT_MEMORY)
        }),
        "physical model request must contain the exact verified cognitive context"
    );

    let race_memory = host
        .seed_verified_memory("worker-final-use-race", RACE_MEMORY)
        .await?;
    let hook = Arc::new(FinalRevalidationTestHook {
        reached: tokio::sync::Notify::new(),
        release: tokio::sync::Notify::new(),
    });
    install_final_revalidation_test_hook(Arc::clone(&hook));
    let cancellation = CancellationToken::new();
    let worker = driver.run(
        &mut durable,
        NativeAdmission {
            request_id: RACE_REQUEST_ID.to_string(),
            maximum_in_flight: 1,
        },
        "answer using the verified context".to_string(),
        Some("nectarine".to_string()),
        &cancellation,
    );
    let mutation = async {
        hook.reached.notified().await;
        let result = host
            .tombstone(&race_memory, "revoked during final-use race")
            .await;
        hook.release.notify_one();
        result
    };
    let coordinated = async {
        let (worker_result, mutation_result) = tokio::join!(worker, mutation);
        mutation_result?;
        Ok::<_, Box<dyn std::error::Error + Send + Sync>>(worker_result)
    };
    let worker_result = match tokio::time::timeout(Duration::from_secs(30), coordinated).await {
        Ok(result) => result?,
        Err(_) => return Err("timed out coordinating cognitive final-use race".into()),
    };
    assert!(
        worker_result.is_err(),
        "a tombstone committed after durable dispatch must stop the run before TurnStart"
    );

    let stopped = durable
        .native_record(RACE_REQUEST_ID)
        .cloned()
        .ok_or("missing durable native race record")?;
    assert_eq!(stopped.state, NativeReservationState::Released);
    assert!(stopped.dispatch.is_some());
    assert_eq!(stopped.turn_id, None);
    assert_eq!(stopped.observation, None);
    assert!(
        stopped
            .pre_dispatch_stop
            .as_deref()
            .is_some_and(|reason| reason.contains("cognitive final-use revalidation failed"))
    );

    let correction_memory = host
        .seed_verified_memory("worker-final-use-correction-race", CORRECTION_MEMORY)
        .await?;
    let correction_hook = Arc::new(FinalRevalidationTestHook {
        reached: tokio::sync::Notify::new(),
        release: tokio::sync::Notify::new(),
    });
    install_final_revalidation_test_hook(Arc::clone(&correction_hook));
    let correction_cancellation = CancellationToken::new();
    let correction_worker = driver.run(
        &mut durable,
        NativeAdmission {
            request_id: CORRECTION_REQUEST_ID.to_string(),
            maximum_in_flight: 1,
        },
        "answer using the verified corrected context".to_string(),
        Some("kumquat".to_string()),
        &correction_cancellation,
    );
    let correction = async {
        correction_hook.reached.notified().await;
        let result = host.correct(&correction_memory, CORRECTED_MEMORY).await;
        correction_hook.release.notify_one();
        result
    };
    let coordinated_correction = async {
        let (worker_result, correction_result) = tokio::join!(correction_worker, correction);
        correction_result?;
        Ok::<_, Box<dyn std::error::Error + Send + Sync>>(worker_result)
    };
    let correction_result =
        match tokio::time::timeout(Duration::from_secs(30), coordinated_correction).await {
            Ok(result) => result?,
            Err(_) => {
                return Err("timed out coordinating cognitive final-use correction race".into());
            }
        };
    assert!(
        correction_result.is_err(),
        "a correction committed after durable dispatch must stop the run before TurnStart"
    );
    let correction_stopped = durable
        .native_record(CORRECTION_REQUEST_ID)
        .cloned()
        .ok_or("missing durable native correction-race record")?;
    assert_eq!(correction_stopped.state, NativeReservationState::Released);
    assert!(correction_stopped.dispatch.is_some());
    assert_eq!(correction_stopped.turn_id, None);
    assert_eq!(correction_stopped.observation, None);
    assert!(
        correction_stopped
            .pre_dispatch_stop
            .as_deref()
            .is_some_and(|reason| reason.contains("cognitive final-use revalidation failed"))
    );
    let physical_provider_requests = server.received_requests().await.unwrap_or_default();
    assert_eq!(
        physical_provider_requests
            .iter()
            .filter(|request| request.url.path().ends_with("/responses"))
            .count(),
        1,
        "tombstone/correction races must not add a physical Responses API request",
    );

    drop(durable);
    let reopened = DurableInferenceControl::open(&journal, 8)?;
    assert_eq!(
        reopened.native_record(ACCEPT_REQUEST_ID),
        Some(&accepted_record)
    );
    assert_eq!(reopened.native_record(RACE_REQUEST_ID), Some(&stopped));
    assert_eq!(
        reopened.native_record(CORRECTION_REQUEST_ID),
        Some(&correction_stopped)
    );
    drop(reopened);
    let _ = std::fs::remove_file(&journal);
    issuer.await??;
    host.shutdown().await;
    Ok(())
}

#[test]
fn late_completed_cannot_upgrade_cancelled_or_timed_out_boundary() {
    for boundary_status in [
        NativeBoundaryStatus::Cancelled,
        NativeBoundaryStatus::TimedOut,
    ] {
        let mut value = output();
        let mut messages = NativeMessageOutput::default();
        value.boundary_status = boundary_status;
        value.stop_reason = Some(match boundary_status {
            NativeBoundaryStatus::Cancelled => LOCAL_CANCELLED.to_string(),
            NativeBoundaryStatus::TimedOut => LOCAL_DEADLINE_ELAPSED.to_string(),
            _ => unreachable!(),
        });
        assert!(
            observe_for_test(
                &mut messages,
                &mut value,
                terminal("thread-a", "turn-a", TurnStatus::Completed),
            )
            .unwrap()
        );
        assert_eq!(value.status, NativeRunStatus::Completed);
        assert_eq!(value.boundary_status, boundary_status);
        assert!(value.terminal_observed);
        assert!(!value.succeeded());
    }
}

#[test]
fn disconnect_event_lag_cancel_and_deadline_have_explicit_boundary_statuses() {
    assert_eq!(
        classify_observation_failure("provider events lost"),
        NativeBoundaryStatus::Quarantined
    );
    assert_eq!(
        classify_observation_failure("App Server socket disconnected"),
        NativeBoundaryStatus::Quarantined
    );
    assert_eq!(
        classify_observation_failure(LOCAL_CANCELLED),
        NativeBoundaryStatus::Cancelled
    );
    assert_eq!(
        classify_observation_failure(LOCAL_DEADLINE_ELAPSED),
        NativeBoundaryStatus::TimedOut
    );
}

#[test]
fn final_use_fence_rejects_owner_ingress_cancel_and_deadline_drift() {
    use std::path::Path;

    let ready = ready_owner();
    assert!(
        validate_post_authority_fence(
            &ready,
            Path::new("/tmp/hepta-app.sock"),
            Path::new("/tmp/hepta-app.sock"),
            false,
            99,
            100,
        )
        .is_ok()
    );

    let mut fenced = ready.clone();
    fenced.fenced = true;
    assert!(
        validate_post_authority_fence(
            &fenced,
            Path::new("/tmp/hepta-app.sock"),
            Path::new("/tmp/hepta-app.sock"),
            false,
            99,
            100,
        )
        .is_err()
    );
    assert!(
        validate_post_authority_fence(
            &ready,
            Path::new("/tmp/hepta-app.sock"),
            Path::new("/tmp/other.sock"),
            false,
            99,
            100,
        )
        .is_err()
    );
    assert!(
        validate_post_authority_fence(
            &ready,
            Path::new("/tmp/hepta-app.sock"),
            Path::new("/tmp/hepta-app.sock"),
            true,
            99,
            100,
        )
        .is_err()
    );
    assert!(
        validate_post_authority_fence(
            &ready,
            Path::new("/tmp/hepta-app.sock"),
            Path::new("/tmp/hepta-app.sock"),
            false,
            100,
            100,
        )
        .is_err()
    );
}
