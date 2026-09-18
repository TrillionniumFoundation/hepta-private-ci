use super::*;
use codex_app_server_protocol::AgentMessageDeltaNotification;
use codex_app_server_protocol::Turn;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnItemsView;
use codex_app_server_client::ObservedAppServerEvent;

fn test_intent() -> CodexOperationIntent {
    let payload = Digest32::of_bytes(b"native-request");
    CodexOperationIntent {
        operation_id: stable_id("request-1").unwrap(),
        thread_id: stable_id("thread-a").unwrap(),
        turn_id: Some(stable_id("turn-a").unwrap()),
        method_id: stable_id("turn:start").unwrap(),
        protocol_version: stable_id(APP_SERVER_V2_PROTOCOL_ID).unwrap(),
        session_generation: 1,
        payload_digest: payload,
        lease_payload_digest: payload,
        deadline_ms: u64::MAX,
    }
}

fn observe(
    output: &mut NativeRunOutput,
    notification: ServerNotification,
) -> std::result::Result<bool, String> {
    let witnessed = ObservedAppServerEvent::from_event_for_test(
        1,
        AppServerEvent::ServerNotification(Box::new(notification)),
    );
    observe_notification(output, &test_intent(), &witnessed)
}

fn output() -> NativeRunOutput {
    NativeRunOutput {
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        model: "provider-model".to_string(),
        model_provider: "provider".to_string(),
        status: NativeRunStatus::Indeterminate,
        output: String::new(),
        observed_output_tokens: None,
        terminal_observed: false,
        stop_reason: None,
        owner_authority: NativeOwnerAuthority::Unverified,
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

#[test]
fn only_the_bound_turn_can_complete_the_native_request() {
    let mut output = output();
    assert!(
        !observe(
            &mut output,
            terminal("thread-b", "turn-a", TurnStatus::Completed)
        )
        .unwrap()
    );
    assert!(
        !observe(
            &mut output,
            terminal("thread-a", "turn-b", TurnStatus::Completed)
        )
        .unwrap()
    );
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(
        observe(
            &mut output,
            terminal("thread-a", "turn-a", TurnStatus::Interrupted)
        )
        .unwrap()
    );
    assert_eq!(output.status, NativeRunStatus::Interrupted);
    assert!(output.terminal_observed);
}

#[test]
fn output_is_observed_bounded_and_never_predeclares_success() {
    let mut output = output();
    let delta = |thread: &str, text: String| {
        ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
            thread_id: thread.to_string(),
            turn_id: "turn-a".to_string(),
            item_id: "item".to_string(),
            delta: text,
        })
    };
    observe(&mut output, delta("unrelated", "discard".to_string())).unwrap();
    observe(&mut output, delta("thread-a", "model output".to_string())).unwrap();
    assert_eq!(output.output, "model output");
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(
        observe(&mut output, delta("thread-a", "x".repeat(MAX_OUTPUT_BYTES))).is_err()
    );
    assert_eq!(output.output, "model output");
    assert!(!output.terminal_observed);
}

#[test]
fn in_progress_is_not_a_terminal_observation() {
    let mut output = output();
    assert!(
        observe(
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
    observe(&mut output, usage("unrelated", 99)).unwrap();
    assert_eq!(output.observed_output_tokens, None);
    observe(&mut output, usage("thread-a", 42)).unwrap();
    assert!(observe(&mut output, usage("thread-a", -1)).is_err());
    assert!(observe(&mut output, usage("thread-a", 41)).is_err());
    assert_eq!(output.observed_output_tokens, Some(42));
    let mut failed = terminal("thread-a", "turn-a", TurnStatus::Failed);
    if let ServerNotification::TurnCompleted(ref mut notification) = failed {
        notification.turn.error = Some(TurnError {
            message: "provider error".to_string(),
            codex_error_info: None,
            additional_details: None,
        });
    }
    assert!(observe(&mut output, failed).unwrap());
    assert_eq!(output.status, NativeRunStatus::Failed);
    assert_eq!(output.observed_output_tokens, Some(42));
    assert_eq!(output.stop_reason.as_deref(), Some("provider error"));
    assert!(output.terminal_observed);
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
        verify_owner_health(
            &mut output,
            async { Ok(ready_owner()) },
            Instant::now() + RPC_TIMEOUT,
        )
        .await
        .unwrap();
        output.observed_output_tokens = Some(42);
        assert!(
            verify_owner_health(&mut output, async { health }, Instant::now() + RPC_TIMEOUT)
                .await
                .is_err()
        );
        let lost = output.owner_authority.clone();
        // Grace has no owner parameter: it can still establish provider facts.
        assert!(
            observe(
                &mut output,
                terminal("thread-a", "turn-a", TurnStatus::Completed)
            )
            .unwrap()
        );
        assert_eq!(output.status, NativeRunStatus::Completed);
        assert_eq!(output.observed_output_tokens, Some(42));
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
    observe(
        &mut timed_out,
        terminal("thread-a", "turn-a", TurnStatus::Completed),
    )
    .unwrap();
    assert_eq!(timed_out.status, NativeRunStatus::Completed);
    assert_eq!(timed_out.observed_output_tokens, None);
    assert!(!timed_out.succeeded());

    let mut terminal_first = output();
    verify_owner_health(
        &mut terminal_first,
        async { Ok(ready_owner()) },
        Instant::now() + RPC_TIMEOUT,
    )
    .await
    .unwrap();
    // select! can consume Completed before a simultaneously ready health tick.
    observe(
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
    observe(
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
    assert!(output.succeeded());
    output.status = NativeRunStatus::Interrupted;
    assert!(!output.succeeded());
}

#[test]
fn observed_terminal_flows_through_adapter_and_durable_reopen() {
    use codex_hepta_infer_core::durable_control::native::NativeDispatch;
    use codex_hepta_infer_core::durable_control::native::NativeRequest;
    use codex_hepta_infer_core::durable_control::native::NativeReservationState;

    for (status, expected) in [
        (TurnStatus::Completed, NativeRunStatus::Completed),
        (TurnStatus::Failed, NativeRunStatus::Failed),
        (TurnStatus::Interrupted, NativeRunStatus::Interrupted),
    ] {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "hepta-runtime-codex-terminal-{status:?}-{nonce}.journal"
        ));
        let intent = test_intent();
        let mut control = DurableInferenceControl::open(&path, 8).unwrap();
        control
            .reserve_native(
                NativeRequest {
                    request_id: intent.operation_id.to_string(),
                    principal_id: "agent-1".to_string(),
                    worker_generation: intent.session_generation,
                    model: "provider-model".to_string(),
                    payload_digest: intent.payload_digest.to_string(),
                },
                1,
            )
            .unwrap();
        control
            .dispatch_native(
                intent.operation_id.as_str(),
                NativeDispatch {
                    thread_id: "thread-a".to_string(),
                    model_provider: "provider".to_string(),
                    context_digest: Digest32::of_bytes(b"context").to_string(),
                },
            )
            .unwrap();
        control
            .native_started(intent.operation_id.as_str(), "turn-a".to_string())
            .unwrap();

        let mut output = output();
        assert!(
            observe(
                &mut output,
                terminal("thread-a", "turn-a", status),
            )
            .unwrap()
        );
        assert_eq!(output.status, expected);
        assert!(output.terminal_observed);
        let settled = control
            .settle_native(intent.operation_id.as_str(), output.clone())
            .unwrap();
        assert_eq!(settled.state, NativeReservationState::Released);
        assert_eq!(settled.observation, Some(output));
        drop(control);

        let reopened = DurableInferenceControl::open(&path, 8).unwrap();
        assert_eq!(reopened.native_record(intent.operation_id.as_str()), Some(&settled));
        drop(reopened);
        std::fs::remove_file(path).unwrap();
    }
}

#[test]
fn overload_backoff_is_bounded_deterministic_and_nonzero() {
    for attempt in 0..=MAX_OVERLOAD_RETRIES {
        let first = overload_backoff("request-1", attempt);
        let second = overload_backoff("request-1", attempt);
        assert_eq!(first, second);
        assert!(!first.is_zero());
        assert!(first <= MAX_OVERLOAD_BACKOFF);
    }
}
