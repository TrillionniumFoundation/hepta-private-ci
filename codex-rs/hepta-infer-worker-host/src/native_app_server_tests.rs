use super::*;
use codex_app_server_protocol::AgentMessageDeltaNotification;
use codex_app_server_protocol::Turn;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnItemsView;

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
        !observe_notification(
            &mut output,
            terminal("thread-b", "turn-a", TurnStatus::Completed)
        )
        .unwrap()
    );
    assert!(
        !observe_notification(
            &mut output,
            terminal("thread-a", "turn-b", TurnStatus::Completed)
        )
        .unwrap()
    );
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(
        observe_notification(
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
    observe_notification(&mut output, delta("unrelated", "discard".to_string())).unwrap();
    observe_notification(&mut output, delta("thread-a", "model output".to_string())).unwrap();
    assert_eq!(output.output, "model output");
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(
        observe_notification(&mut output, delta("thread-a", "x".repeat(MAX_OUTPUT_BYTES))).is_err()
    );
    assert_eq!(output.output, "model output");
    assert!(!output.terminal_observed);
}

#[test]
fn in_progress_is_not_a_terminal_observation() {
    let mut output = output();
    assert!(
        observe_notification(
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
    observe_notification(&mut output, usage("unrelated", 99)).unwrap();
    assert_eq!(output.observed_output_tokens, None);
    observe_notification(&mut output, usage("thread-a", 42)).unwrap();
    assert!(observe_notification(&mut output, usage("thread-a", -1)).is_err());
    assert!(observe_notification(&mut output, usage("thread-a", 41)).is_err());
    assert_eq!(output.observed_output_tokens, Some(42));
    let mut failed = terminal("thread-a", "turn-a", TurnStatus::Failed);
    if let ServerNotification::TurnCompleted(ref mut notification) = failed {
        notification.turn.error = Some(TurnError {
            message: "provider error".to_string(),
            codex_error_info: None,
            additional_details: None,
        });
    }
    assert!(observe_notification(&mut output, failed).unwrap());
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
            observe_notification(
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
    observe_notification(
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
    observe_notification(
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
    observe_notification(
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
