use super::*;
use codex_app_server_client::RemoteAppServerObservedEvent;
use codex_app_server_protocol::AgentMessageDeltaNotification;
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
    output: &mut NativeRunOutput,
    notification: ServerNotification,
) -> std::result::Result<bool, String> {
    let binding = binding();
    observe_event(
        output,
        &observed(notification),
        &binding,
        &mut NativeMessageOutput::default(),
    )
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
    assert!(
        !observe_for_test(
            &mut output,
            terminal("thread-b", "turn-a", TurnStatus::Completed)
        )
        .unwrap()
    );
    assert!(
        !observe_for_test(
            &mut output,
            terminal("thread-a", "turn-b", TurnStatus::Completed)
        )
        .unwrap()
    );
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(
        observe_for_test(
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
    let delta = |thread: &str, text: String| {
        ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
            thread_id: thread.to_string(),
            turn_id: "turn-a".to_string(),
            item_id: "item".to_string(),
            delta: text,
        })
    };
    observe_for_test(&mut output, delta("unrelated", "discard".to_string())).unwrap();
    observe_for_test(&mut output, delta("thread-a", "model output".to_string())).unwrap();
    assert_eq!(output.output, "model output");
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(
        observe_for_test(&mut output, delta("thread-a", "x".repeat(MAX_OUTPUT_BYTES))).is_err()
    );
    assert_eq!(output.output, "model output");
    assert!(!output.terminal_observed);
}

#[test]
fn in_progress_is_not_a_terminal_observation() {
    let mut output = output();
    assert!(
        observe_for_test(
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
    observe_for_test(&mut output, usage("unrelated", 99)).unwrap();
    assert_eq!(output.observed_output_tokens, None);
    observe_for_test(&mut output, usage("thread-a", 42)).unwrap();
    assert!(observe_for_test(&mut output, usage("thread-a", -1)).is_err());
    assert!(observe_for_test(&mut output, usage("thread-a", 41)).is_err());
    assert_eq!(output.observed_output_tokens, Some(42));
    let mut failed = terminal("thread-a", "turn-a", TurnStatus::Failed);
    if let ServerNotification::TurnCompleted(ref mut notification) = failed {
        notification.turn.error = Some(TurnError {
            message: "provider error".to_string(),
            codex_error_info: None,
            additional_details: None,
        });
    }
    assert!(observe_for_test(&mut output, failed).unwrap());
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
        assert_eq!(output.boundary_status, NativeBoundaryStatus::Quarantined);
        // Grace has no owner parameter: it can still establish provider facts.
        assert!(
            observe_for_test(
                &mut output,
                terminal("thread-a", "turn-a", TurnStatus::Completed)
            )
            .unwrap()
        );
        assert_eq!(output.status, NativeRunStatus::Completed);
        assert_eq!(output.boundary_status, NativeBoundaryStatus::Quarantined);
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
    observe_for_test(
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
    observe_for_test(
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
    observe_for_test(
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
fn wire_admission_and_cognitive_final_use_precede_physical_turn_start() {
    let source = include_str!("native_app_server.rs");
    let wire_admission = source
        .find("let request_receipt = adapt_product_wire_v3(")
        .expect("product-bound wire admission");
    let authority_claim = source
        .find("authorizer.claim(authority_binding.clone())")
        .expect("final-use authority claim");
    let durable_dispatch = source
        .find("control.dispatch_native_with_pre_effect_abort(")
        .expect("durable native dispatch");
    let revalidation = source
        .find("owner.revalidate_cognitive_context(snapshot).await")
        .expect("final-use cognitive revalidation");
    let turn_start = source
        .find("request_typed_observed(ClientRequest::TurnStart")
        .expect("physical turn start");
    let durable_stop = source
        .find("control.abort_native_before_effect(")
        .expect("durable pre-turn stop");
    assert!(wire_admission < authority_claim);
    assert!(authority_claim < durable_dispatch);
    assert!(durable_dispatch < revalidation);
    assert!(revalidation < turn_start);
    assert!(durable_stop < turn_start);
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
    let host =
        CognitiveTestHost::start(root, agent_id, MODEL, &format!("{}/v1", server.uri())).await?;
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
        value.boundary_status = boundary_status;
        value.stop_reason = Some(match boundary_status {
            NativeBoundaryStatus::Cancelled => LOCAL_CANCELLED.to_string(),
            NativeBoundaryStatus::TimedOut => LOCAL_DEADLINE_ELAPSED.to_string(),
            _ => unreachable!(),
        });
        assert!(
            observe_for_test(
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

#[test]
fn completed_only_output_is_bound_deduplicated_and_never_predeclares_success() {
    let mut output = output();
    let binding = binding();
    let mut messages = NativeMessageOutput::default();
    let item = ThreadItem::AgentMessage {
        id: "message-final".to_string(),
        text: "fresh context accepted".to_string(),
        phase: None,
        memory_citation: None,
        delivery: None,
    };
    let completed = |thread: &str| {
        observed(ServerNotification::ItemCompleted(
            codex_app_server_protocol::ItemCompletedNotification {
                thread_id: thread.to_string(),
                turn_id: "turn-a".to_string(),
                completed_at_ms: 0,
                item: item.clone(),
            },
        ))
    };
    assert!(!observe_event(&mut output, &completed("foreign"), &binding, &mut messages).unwrap());
    assert!(output.output.is_empty());
    for _ in 0..2 {
        assert!(
            !observe_event(&mut output, &completed("thread-a"), &binding, &mut messages).unwrap()
        );
        assert_eq!(output.output, "fresh context accepted");
        assert!(!output.terminal_observed);
        assert!(!output.succeeded());
    }
    let mut notification = terminal("thread-a", "turn-a", TurnStatus::Completed);
    if let ServerNotification::TurnCompleted(value) = &mut notification {
        value.turn.items.push(item);
    }
    assert!(
        observe_event(
            &mut output,
            &observed(notification),
            &binding,
            &mut messages
        )
        .unwrap()
    );
    assert_eq!(output.output, "fresh context accepted");
    assert!(output.terminal_observed);
    assert!(output.codex_terminal_correlation_digest.is_some());
}
