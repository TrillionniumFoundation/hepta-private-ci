use super::*;
use codex_app_server_protocol::ItemCompletedNotification;
use codex_app_server_protocol::ItemStartedNotification;
use codex_app_server_protocol::ThreadTokenUsage;
use codex_app_server_protocol::ThreadTokenUsageUpdatedNotification;
use codex_app_server_protocol::TokenUsageBreakdown;

#[test]
fn selected_event_already_cancelled_terminal_keeps_fact_without_text_or_success() {
    let mut value = output();
    value.owner_authority = NativeOwnerAuthority::ObservedReady;
    let mut observation = NativeTurnObservation::new(binding());
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    // The notification is already selected, so this deterministically models
    // select! choosing an available terminal over the available cancel branch.
    let event = observed(snapshot(
        vec![message("selected", "late text")],
        TurnItemsView::Summary,
    ));
    let result = observation.observe_selected_event(
        &mut value,
        &event,
        Instant::now() + Duration::from_secs(60),
        &cancellation,
    );
    assert_eq!(result, Err(LOCAL_CANCELLED.to_string()));
    assert_eq!(value.output, "");
    assert_eq!(value.status, NativeRunStatus::Completed);
    assert_eq!(value.boundary_status, NativeBoundaryStatus::Cancelled);
    assert!(value.terminal_observed);
    assert!(value.codex_terminal_correlation_digest.is_some());
    assert!(!value.succeeded());
}

#[test]
fn selected_event_expired_deadline_terminal_keeps_fact_without_text_or_success() {
    let mut value = output();
    value.owner_authority = NativeOwnerAuthority::ObservedReady;
    let mut observation = NativeTurnObservation::new(binding());
    let cancellation = CancellationToken::new();
    let deadline = Instant::now();
    let event = observed(snapshot(
        vec![message("selected", "late text")],
        TurnItemsView::Summary,
    ));
    let result = observation.observe_selected_event(&mut value, &event, deadline, &cancellation);
    assert_eq!(result, Err(LOCAL_DEADLINE_ELAPSED.to_string()));
    assert_eq!(value.output, "");
    assert_eq!(value.status, NativeRunStatus::Completed);
    assert_eq!(value.boundary_status, NativeBoundaryStatus::TimedOut);
    assert!(value.terminal_observed);
    assert!(value.codex_terminal_correlation_digest.is_some());
    assert!(!value.succeeded());
}

fn message(id: &str, text: &str) -> ThreadItem {
    ThreadItem::AgentMessage {
        id: id.to_string(),
        text: text.to_string(),
        phase: None,
        memory_citation: None,
        delivery: None,
    }
}

fn completed(id: &str, text: &str) -> ServerNotification {
    ServerNotification::ItemCompleted(ItemCompletedNotification {
        item: message(id, text),
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        completed_at_ms: 1,
    })
}

fn started(id: &str) -> ServerNotification {
    ServerNotification::ItemStarted(ItemStartedNotification {
        item: message(id, ""),
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        started_at_ms: 1,
    })
}

fn delta(id: &str, text: &str) -> ServerNotification {
    ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
        item_id: id.to_string(),
        delta: text.to_string(),
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
    })
}

fn snapshot(items: Vec<ThreadItem>, view: TurnItemsView) -> ServerNotification {
    let mut notification = terminal("thread-a", "turn-a", TurnStatus::Completed);
    if let ServerNotification::TurnCompleted(completed) = &mut notification {
        completed.turn.items = items;
        completed.turn.items_view = view;
    }
    notification
}

#[test]
fn completed_only_item_supplies_text_without_predeclaring_authority() {
    let mut value = output();
    let mut observation = NativeTurnObservation::new(binding());
    assert!(
        !observe_for_test(
            &mut observation,
            &mut value,
            completed("message-a", "fresh context accepted")
        )
        .unwrap()
    );
    assert_eq!(value.output, "fresh context accepted");
    assert_eq!(value.status, NativeRunStatus::Indeterminate);
    assert!(!value.terminal_observed);
    assert!(!value.succeeded());
    assert!(
        observe_for_test(
            &mut observation,
            &mut value,
            snapshot(
                vec![message("message-a", "fresh context accepted")],
                TurnItemsView::Summary
            )
        )
        .unwrap()
    );
    assert_eq!(value.output, "fresh context accepted");
    assert!(value.terminal_observed);
    assert!(!value.succeeded());
}

#[test]
fn delta_complete_and_summary_converge_once_per_item_in_utf8_bytes() {
    let mut value = output();
    let mut observation = NativeTurnObservation::new(binding());
    for notification in [
        delta("message-a", "你"),
        delta("message-a", "好"),
        completed("message-a", "你好世界"),
        completed("message-a", "你好世界"),
        snapshot(
            vec![message("message-a", "你好世界")],
            TurnItemsView::Summary,
        ),
    ] {
        observe_for_test(&mut observation, &mut value, notification).unwrap();
    }
    assert_eq!(value.output, "你好世界");
    assert_eq!(value.output.len(), 12);
}

#[test]
fn started_item_order_survives_interleaved_deltas_and_reverse_completions() {
    let mut value = output();
    let mut observation = NativeTurnObservation::new(binding());
    for notification in [
        started("first"),
        started("second"),
        delta("second", "B"),
        delta("first", "A"),
        completed("second", "B2"),
        completed("first", "A1"),
        snapshot(vec![message("second", "B2")], TurnItemsView::Summary),
    ] {
        observe_for_test(&mut observation, &mut value, notification).unwrap();
    }
    assert_eq!(value.output, "A1B2");
}

#[test]
fn nonempty_full_snapshot_supplies_exact_order_with_or_without_prior_deltas() {
    for preceding in [
        Vec::new(),
        vec![delta("second", "B"), delta("first", "A")],
        vec![completed("first", "A1"), completed("second", "B2")],
    ] {
        let mut value = output();
        let mut observation = NativeTurnObservation::new(binding());
        for notification in preceding {
            observe_for_test(&mut observation, &mut value, notification).unwrap();
        }
        assert!(
            observe_for_test(
                &mut observation,
                &mut value,
                snapshot(
                    vec![message("first", "A1"), message("second", "B2")],
                    TurnItemsView::Full
                )
            )
            .unwrap()
        );
        assert_eq!(value.output, "A1B2");
    }
}

#[test]
fn wrong_thread_turn_and_transport_never_supply_text() {
    let mut value = output();
    let mut observation = NativeTurnObservation::new(binding());
    for wrong_thread in [false, true] {
        for mut notification in [
            started("foreign"),
            delta("foreign", "secret"),
            completed("foreign", "secret"),
        ] {
            let (thread, turn) = match &mut notification {
                ServerNotification::ItemStarted(item) => (&mut item.thread_id, &mut item.turn_id),
                ServerNotification::AgentMessageDelta(item) => {
                    (&mut item.thread_id, &mut item.turn_id)
                }
                ServerNotification::ItemCompleted(item) => (&mut item.thread_id, &mut item.turn_id),
                _ => unreachable!(),
            };
            *if wrong_thread { thread } else { turn } = "unrelated".to_string();
            assert!(!observe_for_test(&mut observation, &mut value, notification).unwrap());
        }
    }
    let foreign = RemoteAppServerObservedEvent::from_test_event(
        AppServerEvent::ServerNotification(Box::new(completed("foreign", "secret"))),
        /*connection_id*/ 8,
        Some("test-app-server".to_string()),
        Some("/home/agent".to_string()),
    );
    assert!(observation.observe_event(&mut value, &foreign).is_err());
    assert_eq!(value.output, "");
    assert!(!value.terminal_observed);
}

#[test]
fn cancelled_timed_out_and_quarantined_observe_usage_and_terminal_without_late_text() {
    for boundary in [
        NativeBoundaryStatus::Cancelled,
        NativeBoundaryStatus::TimedOut,
        NativeBoundaryStatus::Quarantined,
    ] {
        let mut value = output();
        let mut observation = NativeTurnObservation::new(binding());
        observe_for_test(
            &mut observation,
            &mut value,
            completed("before", "observed before stop"),
        )
        .unwrap();
        value.boundary_status = boundary;
        value.stop_reason = Some("original stop".to_string());
        for notification in [
            started("late"),
            delta("late", "secret"),
            completed("late", "secret"),
        ] {
            observe_for_test(&mut observation, &mut value, notification).unwrap();
        }
        let counts = TokenUsageBreakdown {
            total_tokens: 42,
            input_tokens: 0,
            cached_input_tokens: 0,
            cache_write_input_tokens: 0,
            output_tokens: 42,
            reasoning_output_tokens: 0,
        };
        observe_for_test(
            &mut observation,
            &mut value,
            ServerNotification::ThreadTokenUsageUpdated(ThreadTokenUsageUpdatedNotification {
                thread_id: "thread-a".to_string(),
                turn_id: "turn-a".to_string(),
                token_usage: ThreadTokenUsage {
                    total: counts.clone(),
                    last: counts,
                    model_context_window: None,
                },
            }),
        )
        .unwrap();
        assert!(
            observe_for_test(
                &mut observation,
                &mut value,
                snapshot(vec![message("late", "secret")], TurnItemsView::Summary)
            )
            .unwrap()
        );
        assert_eq!(value.output, "observed before stop");
        assert_eq!(value.observed_output_tokens, Some(42));
        assert_eq!(value.boundary_status, boundary);
        assert_eq!(value.stop_reason.as_deref(), Some("original stop"));
        assert!(value.terminal_observed);
        assert!(!value.succeeded());
        assert!(
            !observe_for_test(
                &mut observation,
                &mut value,
                completed("after-terminal", "secret")
            )
            .unwrap()
        );
        assert_eq!(value.output, "observed before stop");
    }
}

#[test]
fn complete_and_snapshot_enforce_original_total_byte_limit_atomically() {
    let exact = "界".repeat(MAX_OUTPUT_BYTES / 3) + &"x".repeat(MAX_OUTPUT_BYTES % 3);
    let mut value = output();
    let mut observation = NativeTurnObservation::new(binding());
    observe_for_test(&mut observation, &mut value, completed("full", &exact)).unwrap();
    assert_eq!(value.output.len(), MAX_OUTPUT_BYTES);
    assert!(observe_for_test(&mut observation, &mut value, completed("extra", "x")).is_err());
    assert_eq!(value.output, exact);
    assert!(
        observe_for_test(
            &mut observation,
            &mut value,
            snapshot(
                vec![message("full", &exact), message("extra", "x")],
                TurnItemsView::Full
            )
        )
        .is_err()
    );
    assert_eq!(value.output, exact);
    assert!(!value.terminal_observed);
}

#[test]
fn conflicting_item_reuse_and_terminal_duplicates_fail_without_partial_text() {
    let mut value = output();
    let mut observation = NativeTurnObservation::new(binding());
    observe_for_test(&mut observation, &mut value, delta("bound", "prefix")).unwrap();
    assert!(observe_for_test(&mut observation, &mut value, completed("bound", "other")).is_err());
    observe_for_test(
        &mut observation,
        &mut value,
        completed("bound", "prefix done"),
    )
    .unwrap();
    for notification in [
        completed("bound", "prefix done changed"),
        delta("bound", "extra"),
        snapshot(
            vec![
                message("bound", "prefix done"),
                message("bound", "prefix done"),
            ],
            TurnItemsView::Full,
        ),
        snapshot(vec![message("new", "other")], TurnItemsView::Full),
        snapshot(
            vec![message("bound", "prefix done")],
            TurnItemsView::NotLoaded,
        ),
    ] {
        assert!(observe_for_test(&mut observation, &mut value, notification).is_err());
        assert_eq!(value.output, "prefix done");
        assert!(!value.terminal_observed);
    }
}

#[test]
fn empty_items_and_oversized_ids_cannot_grow_unbounded_metadata() {
    let mut value = output();
    let mut observation = NativeTurnObservation::new(binding());
    assert!(observe_for_test(&mut observation, &mut value, completed("", "")).is_err());
    assert!(
        observe_for_test(
            &mut observation,
            &mut value,
            completed(&"x".repeat(129), "")
        )
        .is_err()
    );
    for index in 0..128 {
        observe_for_test(
            &mut observation,
            &mut value,
            started(&format!("item-{index}")),
        )
        .unwrap();
    }
    assert!(observe_for_test(&mut observation, &mut value, completed("one-too-many", "")).is_err());
    assert_eq!(value.output, "");
    assert!(
        observe_for_test(
            &mut observation,
            &mut value,
            snapshot(Vec::new(), TurnItemsView::Full)
        )
        .unwrap()
    );
}

#[test]
fn selected_event_terminal_before_later_cancel_keeps_original_success_boundary() {
    let mut value = output();
    value.owner_authority = NativeOwnerAuthority::ObservedReady;
    let mut observation = NativeTurnObservation::new(binding());
    let cancellation = CancellationToken::new();
    let event = observed(snapshot(
        vec![message("selected", "accepted before cancel")],
        TurnItemsView::Summary,
    ));
    assert!(
        observation
            .observe_selected_event(
                &mut value,
                &event,
                Instant::now() + Duration::from_secs(60),
                &cancellation,
            )
            .unwrap()
    );
    assert!(value.succeeded());
    let before_cancel = value.clone();
    cancellation.cancel();
    // The accepted terminal already has its original correlation receipt.
    // A later local token cannot retroactively change that observed ordering.
    assert!(
        !observation
            .observe_selected_event(&mut value, &event, Instant::now(), &cancellation,)
            .unwrap()
    );
    assert_eq!(value, before_cancel);
}

#[test]
fn selected_event_cancelled_usage_then_grace_terminal_keeps_original_stop() {
    let mut value = output();
    value.owner_authority = NativeOwnerAuthority::ObservedReady;
    let mut observation = NativeTurnObservation::new(binding());
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let counts = TokenUsageBreakdown {
        total_tokens: 42,
        input_tokens: 0,
        cached_input_tokens: 0,
        cache_write_input_tokens: 0,
        output_tokens: 42,
        reasoning_output_tokens: 0,
    };
    let usage = observed(ServerNotification::ThreadTokenUsageUpdated(
        ThreadTokenUsageUpdatedNotification {
            thread_id: "thread-a".to_string(),
            turn_id: "turn-a".to_string(),
            token_usage: ThreadTokenUsage {
                total: counts.clone(),
                last: counts,
                model_context_window: None,
            },
        },
    ));
    assert_eq!(
        observation.observe_selected_event(
            &mut value,
            &usage,
            Instant::now() + Duration::from_secs(60),
            &cancellation,
        ),
        Err(LOCAL_CANCELLED.to_string())
    );
    assert_eq!(value.observed_output_tokens, Some(42));
    assert!(!value.terminal_observed);
    // The original driver uses a fresh grace token after recording local stop.
    // Grace may establish terminality but must never grant a fresh text window.
    let grace = CancellationToken::new();
    for notification in [delta("late", "secret"), completed("late", "secret")] {
        assert!(
            !observation
                .observe_selected_event(
                    &mut value,
                    &observed(notification),
                    Instant::now() + INTERRUPT_GRACE,
                    &grace,
                )
                .unwrap()
        );
    }
    let terminal = observed(snapshot(
        vec![message("late", "secret")],
        TurnItemsView::Summary,
    ));
    assert!(
        observation
            .observe_selected_event(
                &mut value,
                &terminal,
                Instant::now() + INTERRUPT_GRACE,
                &grace,
            )
            .unwrap()
    );
    assert_eq!(value.output, "");
    assert_eq!(value.observed_output_tokens, Some(42));
    assert_eq!(value.stop_reason.as_deref(), Some(LOCAL_CANCELLED));
    assert_eq!(value.boundary_status, NativeBoundaryStatus::Cancelled);
    assert!(value.terminal_observed);
    assert!(!value.succeeded());
}
