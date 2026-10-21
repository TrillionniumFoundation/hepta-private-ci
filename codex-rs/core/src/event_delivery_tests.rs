use super::*;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::TurnAbortReason;
use codex_protocol::protocol::TurnAbortedEvent;
use codex_protocol::protocol::WarningEvent;
use futures::poll;
use pretty_assertions::assert_eq;
use std::task::Poll;

fn aborted_event() -> Event {
    Event {
        id: "reused-turn-id".to_string(),
        msg: EventMsg::TurnAborted(TurnAbortedEvent {
            turn_id: Some("reused-turn-id".to_string()),
            reason: TurnAbortReason::Interrupted,
            started_at: None,
            completed_at: None,
            duration_ms: None,
        }),
    }
}

fn event_bytes(event: &Event) -> Vec<u8> {
    serde_json::to_vec(event).expect("serialize the complete raw protocol event")
}

#[tokio::test]
async fn cancelled_receive_preserves_next_event_and_receiving_never_waits_for_owner() {
    let (sender, receiver) = unbounded();
    {
        let receive = receiver.recv_delivery();
        tokio::pin!(receive);
        assert!(poll!(receive.as_mut()).is_pending());
    }
    let completion = StartTransitionCompletion::new();
    sender
        .send_delivery(EventDelivery {
            event: aborted_event(),
            terminalization: TerminalEventCompletion::owned(Arc::clone(&completion)),
        })
        .await
        .unwrap();

    // The item is ready even while its owner is not. A post-receive await inside this
    // future would return Pending, allowing the caller's select to lose the consumed event.
    let receive = receiver.recv_delivery();
    tokio::pin!(receive);
    let Poll::Ready(Ok(delivery)) = poll!(receive.as_mut()) else {
        panic!("receiving a queued event must not await owner completion");
    };
    assert_eq!(event_bytes(&delivery.event), event_bytes(&aborted_event()));
    let wait = delivery.terminalization.wait();
    tokio::pin!(wait);
    assert!(poll!(wait.as_mut()).is_pending());
    completion.complete();
    assert!(poll!(wait.as_mut()).is_ready());
}

#[tokio::test]
async fn identical_logical_turn_ids_retain_distinct_owner_completions() {
    let (sender, receiver) = unbounded();
    let old_owner = StartTransitionCompletion::new();
    let new_owner = StartTransitionCompletion::new();
    for owner in [&old_owner, &new_owner] {
        sender
            .send_delivery(EventDelivery {
                event: aborted_event(),
                terminalization: TerminalEventCompletion::owned(Arc::clone(owner)),
            })
            .await
            .unwrap();
    }
    old_owner.complete();
    drop(old_owner);
    let old = receiver.recv_delivery().await.unwrap();
    let new = receiver.recv_delivery().await.unwrap();
    assert_eq!(event_bytes(&old.event), event_bytes(&new.event));
    assert!(poll!(Box::pin(old.terminalization.wait())).is_ready());
    let wait = new.terminalization.wait();
    tokio::pin!(wait);
    assert!(poll!(wait.as_mut()).is_pending());
    // Re-checking the old delivery must not observe the new unresolved owner.
    assert!(poll!(Box::pin(old.terminalization.wait())).is_ready());
    new_owner.complete();
    assert!(poll!(wait.as_mut()).is_ready());
}

#[tokio::test]
async fn mcp_events_and_terminal_witness_use_one_ordered_queue() {
    let (sender, receiver) = unbounded();
    let mcp_sender = codex_mcp::McpEventSender::new({
        let sender = sender.clone();
        move |event| {
            let sender = sender.clone();
            async move { sender.send(event).await }
        }
    });
    let completion = StartTransitionCompletion::new();
    let before = Event {
        id: "before".into(),
        msg: EventMsg::Warning(WarningEvent {
            message: "before".into(),
        }),
    };
    let after = Event {
        id: "after".into(),
        msg: EventMsg::Warning(WarningEvent {
            message: "after".into(),
        }),
    };
    mcp_sender.send(before.clone()).await.unwrap();
    sender
        .send_delivery(EventDelivery {
            event: aborted_event(),
            terminalization: TerminalEventCompletion::owned(Arc::clone(&completion)),
        })
        .await
        .unwrap();
    mcp_sender.send(after.clone()).await.unwrap();
    assert_eq!(
        event_bytes(&receiver.recv().await.unwrap()),
        event_bytes(&before)
    );
    let terminal = receiver.recv_delivery().await.unwrap();
    assert_eq!(event_bytes(&terminal.event), event_bytes(&aborted_event()));
    assert!(poll!(Box::pin(terminal.terminalization.wait())).is_pending());
    assert_eq!(
        event_bytes(&receiver.recv().await.unwrap()),
        event_bytes(&after)
    );
    completion.complete();
    assert!(poll!(Box::pin(terminal.terminalization.wait())).is_ready());
}
