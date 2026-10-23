use super::*;
use codex_app_server_protocol::ItemCompletedNotification;

fn message_completed(thread: &str, turn: &str, item: &str, text: &str) -> ServerNotification {
    ServerNotification::ItemCompleted(ItemCompletedNotification {
        thread_id: thread.to_string(),
        turn_id: turn.to_string(),
        item: message_item(item, text),
        completed_at_ms: 100,
    })
}

fn message_item(id: &str, text: &str) -> ThreadItem {
    ThreadItem::AgentMessage {
        id: id.to_string(),
        text: text.to_string(),
        phase: None,
        memory_citation: None,
        delivery: None,
    }
}

fn terminal_snapshot(
    view: TurnItemsView,
    status: TurnStatus,
    items: &[(&str, &str)],
) -> ServerNotification {
    let ServerNotification::TurnCompleted(mut notification) =
        terminal("thread-a", "turn-a", status)
    else {
        panic!("terminal fixture");
    };
    notification.turn.items_view = view;
    notification.turn.items = items
        .iter()
        .map(|(id, text)| message_item(id, text))
        .collect();
    ServerNotification::TurnCompleted(notification)
}

#[test]
fn completed_message_is_output_evidence_and_never_a_terminal_success() {
    for status in [
        TurnStatus::Completed,
        TurnStatus::Failed,
        TurnStatus::Interrupted,
    ] {
        let mut output = output();
        output.owner_authority = NativeOwnerAuthority::ObservedReady;
        let mut binding = binding();
        let completion = message_completed("thread-a", "turn-a", "item-a", "answer");
        assert!(!observe_event(&mut output, &observed(completion.clone()), &mut binding).unwrap());
        assert!(!observe_event(&mut output, &observed(completion), &mut binding).unwrap());
        assert_eq!(output.output, "answer");
        assert_eq!(output.status, NativeRunStatus::Indeterminate);
        assert!(!output.terminal_observed);
        assert!(!output.succeeded());
        let expected_success = status == TurnStatus::Completed;
        assert!(
            observe_event(
                &mut output,
                &observed(terminal_snapshot(TurnItemsView::NotLoaded, status, &[])),
                &mut binding
            )
            .unwrap()
        );
        assert_eq!(output.output, "answer");
        assert!(output.terminal_observed);
        assert_eq!(output.succeeded(), expected_success);
    }
}

#[test]
fn output_completion_replaces_partial_bytes_and_refuses_late_deltas() {
    let mut output = output();
    let mut binding = binding();
    let delta = |text: &str| {
        ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
            thread_id: "thread-a".to_string(),
            turn_id: "turn-a".to_string(),
            item_id: "item-a".to_string(),
            delta: text.to_string(),
        })
    };
    observe_event(&mut output, &observed(delta("partial")), &mut binding).unwrap();
    observe_event(
        &mut output,
        &observed(message_completed("thread-a", "turn-a", "item-a", "answer")),
        &mut binding,
    )
    .unwrap();
    assert_eq!(output.output, "answer");
    assert!(observe_event(&mut output, &observed(delta("late")), &mut binding).is_err());
    assert!(
        observe_event(
            &mut output,
            &observed(message_completed("thread-a", "turn-a", "item-a", "changed")),
            &mut binding
        )
        .is_err()
    );
    assert_eq!(output.output, "answer");
    assert!(!output.terminal_observed);
}

#[test]
fn output_items_cannot_cross_thread_turn_or_transport_binding() {
    let mut output = output();
    let mut binding = binding();
    for (thread, turn) in [("other-thread", "turn-a"), ("thread-a", "other-turn")] {
        observe_event(
            &mut output,
            &observed(message_completed(thread, turn, "item-a", "poison")),
            &mut binding,
        )
        .unwrap();
    }
    let wrong_connection = RemoteAppServerObservedEvent::from_test_event(
        AppServerEvent::ServerNotification(Box::new(message_completed(
            "thread-a", "turn-a", "item-a", "poison",
        ))),
        /*connection_id*/ 99,
        Some("test-app-server".to_string()),
        Some("/home/agent".to_string()),
    );
    assert!(observe_event(&mut output, &wrong_connection, &mut binding).is_err());
    assert!(output.output.is_empty());
    assert!(binding.messages.render().is_empty());
    observe_event(
        &mut output,
        &observed(message_completed("thread-a", "turn-a", "item-a", "answer")),
        &mut binding,
    )
    .unwrap();
    assert_eq!(output.output, "answer");
    assert!(!output.succeeded());
}

#[test]
fn interleaved_partial_output_is_snapshotted_before_nonterminal_return() {
    for boundary in [
        NativeBoundaryStatus::Quarantined,
        NativeBoundaryStatus::TimedOut,
        NativeBoundaryStatus::Cancelled,
    ] {
        let mut output = output();
        let mut binding = binding();
        for (item, text) in [("item-a", "A"), ("item-b", "B"), ("item-a", "C")] {
            let delta = ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
                thread_id: "thread-a".to_string(),
                turn_id: "turn-a".to_string(),
                item_id: item.to_string(),
                delta: text.to_string(),
            });
            observe_event(&mut output, &observed(delta), &mut binding).unwrap();
        }
        output.boundary_status = boundary;
        output.owner_authority = NativeOwnerAuthority::Lost {
            reason: "owner unavailable".to_string(),
        };
        output.stop_reason = Some("observation stopped without terminal".to_string());
        let mut expected = output.clone();
        expected.output = "ACB".to_string();
        binding.snapshot_output(&mut output);
        assert_eq!(output, expected);
        assert!(!output.terminal_observed);
        assert!(!output.succeeded());
    }
}

#[test]
fn turn_item_views_keep_stream_summary_and_full_snapshot_semantics_distinct() {
    for (view, items, expected) in [
        (TurnItemsView::NotLoaded, vec![], "partial"),
        (
            TurnItemsView::Summary,
            vec![("item-a", "summary")],
            "partial",
        ),
        (TurnItemsView::Full, vec![("item-a", "full")], "full"),
    ] {
        let mut output = output();
        let mut binding = binding();
        let delta = ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
            thread_id: "thread-a".to_string(),
            turn_id: "turn-a".to_string(),
            item_id: "item-a".to_string(),
            delta: "partial".to_string(),
        });
        observe_event(&mut output, &observed(delta), &mut binding).unwrap();
        assert!(
            observe_event(
                &mut output,
                &observed(terminal_snapshot(view, TurnStatus::Completed, &items)),
                &mut binding
            )
            .unwrap()
        );
        assert_eq!(output.output, expected);
        assert!(output.terminal_observed);
    }
}

#[test]
fn full_snapshot_reorders_message_output_from_its_complete_item_order() {
    let mut output = output();
    let mut binding = binding();
    for (id, text) in [("item-b", "B"), ("item-a", "A")] {
        observe_event(
            &mut output,
            &observed(message_completed("thread-a", "turn-a", id, text)),
            &mut binding,
        )
        .unwrap();
    }
    assert_eq!(output.output, "BA");
    let full = terminal_snapshot(
        TurnItemsView::Full,
        TurnStatus::Completed,
        &[("item-a", "A"), ("item-b", "B")],
    );
    assert!(observe_event(&mut output, &observed(full), &mut binding).unwrap());
    assert_eq!(output.output, "AB");
}

#[test]
fn invalid_turn_snapshots_leave_observed_output_and_terminal_state_unchanged() {
    let oversized = "x".repeat(MAX_OUTPUT_BYTES);
    for (view, items) in [
        (TurnItemsView::NotLoaded, vec![("item-a", "A")]),
        (TurnItemsView::Full, vec![]),
        (TurnItemsView::Full, vec![("item-a", "changed")]),
        (TurnItemsView::Full, vec![("item-a", "A"), ("item-a", "A")]),
        (
            TurnItemsView::Full,
            vec![("item-a", "A"), ("item-b", oversized.as_str())],
        ),
    ] {
        let mut output = output();
        let mut binding = binding();
        observe_event(
            &mut output,
            &observed(message_completed("thread-a", "turn-a", "item-a", "A")),
            &mut binding,
        )
        .unwrap();
        let before = output.clone();
        let snapshot = terminal_snapshot(view, TurnStatus::Completed, &items);
        assert!(observe_event(&mut output, &observed(snapshot), &mut binding).is_err());
        assert_eq!(output, before);
        assert_eq!(binding.messages.render(), "A");
        assert!(!output.terminal_observed);
    }
}
