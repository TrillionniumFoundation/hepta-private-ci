use super::*;
use codex_app_server_protocol::ItemCompletedNotification;

fn completed_message(thread: &str, turn: &str, id: &str, text: &str) -> ServerNotification {
    ServerNotification::ItemCompleted(ItemCompletedNotification {
        thread_id: thread.to_string(),
        turn_id: turn.to_string(),
        item: ThreadItem::AgentMessage {
            id: id.to_string(),
            text: text.to_string(),
            phase: None,
            memory_citation: None,
            delivery: None,
        },
        completed_at_ms: 1,
    })
}

#[test]
fn canonical_completion_without_any_delta_projects_the_actual_output() {
    let mut output = output();
    observe_for_test(
        &mut output,
        completed_message("unrelated", "turn-a", "message", "wrong thread"),
    )
    .unwrap();
    observe_for_test(
        &mut output,
        completed_message("thread-a", "unrelated", "message", "wrong turn"),
    )
    .unwrap();
    assert!(output.output.is_empty());
    observe_for_test(
        &mut output,
        completed_message("thread-a", "turn-a", "message", "actual completed text"),
    )
    .unwrap();
    assert_eq!(output.output, "actual completed text");
    assert!(!output.terminal_observed);
    assert!(
        observe_for_test(
            &mut output,
            terminal("thread-a", "turn-a", TurnStatus::Completed)
        )
        .unwrap()
    );
    assert_eq!(output.output, "actual completed text");
    assert!(output.terminal_observed);
    assert!(
        !output.succeeded(),
        "output cannot establish owner authority"
    );
}

#[test]
fn terminal_summary_supplements_items_without_double_counting_streamed_text() {
    let mut output = output();
    observe_for_test(
        &mut output,
        ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
            thread_id: "thread-a".to_string(),
            turn_id: "turn-a".to_string(),
            item_id: "first".to_string(),
            delta: "par".to_string(),
        }),
    )
    .unwrap();
    observe_for_test(
        &mut output,
        completed_message("thread-a", "turn-a", "first", "partial answer "),
    )
    .unwrap();
    let mut summary = terminal("thread-a", "turn-a", TurnStatus::Completed);
    if let ServerNotification::TurnCompleted(ref mut completed) = summary {
        completed.turn.items_view = TurnItemsView::Summary;
        completed.turn.items = vec![ThreadItem::AgentMessage {
            id: "last".to_string(),
            text: "final answer".to_string(),
            phase: None,
            memory_citation: None,
            delivery: None,
        }];
    }
    assert!(observe_for_test(&mut output, summary.clone()).unwrap());
    assert_eq!(output.output, "partial answer final answer");
    assert!(observe_for_test(&mut output, summary).unwrap());
    assert_eq!(output.output, "partial answer final answer");
}

#[test]
fn oversized_completed_item_cannot_erase_or_terminalize_valid_partial_output() {
    let mut output = output();
    observe_for_test(
        &mut output,
        ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
            thread_id: "thread-a".to_string(),
            turn_id: "turn-a".to_string(),
            item_id: "message".to_string(),
            delta: "partial".to_string(),
        }),
    )
    .unwrap();
    assert!(
        observe_for_test(
            &mut output,
            completed_message(
                "thread-a",
                "turn-a",
                "message",
                &"x".repeat(MAX_OUTPUT_BYTES + 1),
            )
        )
        .is_err()
    );
    assert_eq!(output.output, "partial");
    assert!(!output.terminal_observed);
}

#[test]
fn terminal_output_from_another_connection_cannot_replace_valid_text() {
    let mut output = output();
    observe_for_test(
        &mut output,
        completed_message("thread-a", "turn-a", "first", "valid output"),
    )
    .unwrap();
    let mut notification = terminal("thread-a", "turn-a", TurnStatus::Completed);
    if let ServerNotification::TurnCompleted(ref mut completed) = notification {
        completed.turn.items = vec![ThreadItem::AgentMessage {
            id: "forged".to_string(),
            text: "unbound text".to_string(),
            phase: None,
            memory_citation: None,
            delivery: None,
        }];
    }
    let foreign = RemoteAppServerObservedEvent::from_test_event(
        AppServerEvent::ServerNotification(Box::new(notification)),
        /*connection_id*/ 8,
        Some("test-app-server".to_string()),
        Some("/home/agent".to_string()),
    );
    assert!(
        observe_event(
            &mut output.run,
            &mut output.projection,
            &foreign,
            &binding()
        )
        .is_err()
    );
    assert_eq!(output.output, "valid output");
    assert!(!output.terminal_observed);
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
}

#[test]
fn nonterminal_observations_require_exact_connection_version_and_home() {
    use codex_app_server_protocol::ThreadTokenUsage;
    use codex_app_server_protocol::ThreadTokenUsageUpdatedNotification;
    use codex_app_server_protocol::TokenUsageBreakdown;

    let counts = TokenUsageBreakdown {
        total_tokens: 999,
        input_tokens: 0,
        cached_input_tokens: 0,
        cache_write_input_tokens: 0,
        output_tokens: 999,
        reasoning_output_tokens: 0,
    };
    let notifications = [
        ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
            thread_id: "thread-a".to_string(),
            turn_id: "turn-a".to_string(),
            item_id: "unbound".to_string(),
            delta: "unbound delta".to_string(),
        }),
        completed_message("thread-a", "turn-a", "unbound", "unbound completed text"),
        ServerNotification::ThreadTokenUsageUpdated(ThreadTokenUsageUpdatedNotification {
            thread_id: "thread-a".to_string(),
            turn_id: "turn-a".to_string(),
            token_usage: ThreadTokenUsage {
                total: counts.clone(),
                last: counts,
                model_context_window: None,
            },
        }),
    ];
    for (connection_id, server_version, codex_home) in [
        (8, "test-app-server", "/home/agent"),
        (7, "another-app-server", "/home/agent"),
        (7, "test-app-server", "/home/another-agent"),
    ] {
        for notification in &notifications {
            let mut output = output();
            observe_for_test(
                &mut output,
                completed_message("thread-a", "turn-a", "first", "valid output"),
            )
            .unwrap();
            let expected = output.run.clone();
            let foreign = RemoteAppServerObservedEvent::from_test_event(
                AppServerEvent::ServerNotification(Box::new(notification.clone())),
                connection_id,
                Some(server_version.to_string()),
                Some(codex_home.to_string()),
            );
            assert!(
                observe_event(
                    &mut output.run,
                    &mut output.projection,
                    &foreign,
                    &binding(),
                )
                .is_err()
            );
            output.run.output = output.projection.text();
            assert_eq!(output.run, expected);
        }
    }
}

#[test]
fn interleaved_small_deltas_materialize_only_at_the_consumer_boundary() {
    let mut output = output();
    let binding = binding();
    for index in 0..100_000 {
        let event = observed(ServerNotification::AgentMessageDelta(
            AgentMessageDeltaNotification {
                thread_id: "thread-a".to_string(),
                turn_id: "turn-a".to_string(),
                item_id: if index % 2 == 0 { "first" } else { "second" }.to_string(),
                delta: if index % 2 == 0 { "a" } else { "b" }.to_string(),
            },
        ));
        assert!(!observe_event(&mut output.run, &mut output.projection, &event, &binding).unwrap());
        assert!(output.output.is_empty());
    }
    output.run.output = output.projection.text();
    assert_eq!(
        output.output,
        format!("{}{}", "a".repeat(50_000), "b".repeat(50_000))
    );
    assert!(!output.terminal_observed);
}
