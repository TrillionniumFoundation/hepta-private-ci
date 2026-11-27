use super::PendingRealtimeEvent;
use super::flush_pending_realtime_event;
use async_channel::bounded;
use codex_api::RealtimeEvent;
use futures::poll;
use pretty_assertions::assert_eq;
use std::task::Poll;

#[tokio::test]
async fn backpressure_keeps_the_same_parsed_event_across_cancelled_polls() {
    let (tx, rx) = bounded(/*cap*/ 1);
    tx.send(RealtimeEvent::ConversationItemDone {
        item_id: "first".to_string(),
    })
    .await
    .expect("fill event queue");
    let mut pending = Some(PendingRealtimeEvent {
        event: RealtimeEvent::ConversationItemDone {
            item_id: "second".to_string(),
        },
        should_stop: false,
    });
    {
        let delivery = flush_pending_realtime_event(&tx, &mut pending);
        tokio::pin!(delivery);
        assert!(matches!(poll!(delivery.as_mut()), Poll::Pending));
        // The input pump may service outbound work or reconnect at this point.
    }
    assert!(pending.is_some());
    assert_eq!(
        rx.recv().await.expect("first event"),
        RealtimeEvent::ConversationItemDone {
            item_id: "first".to_string(),
        }
    );
    flush_pending_realtime_event(&tx, &mut pending)
        .await
        .expect("retry the same pending send");
    assert!(pending.is_none());
    assert_eq!(
        rx.recv().await.expect("second event"),
        RealtimeEvent::ConversationItemDone {
            item_id: "second".to_string(),
        }
    );
    assert!(rx.try_recv().is_err());
}

#[tokio::test]
async fn error_event_is_forwarded_once_before_the_original_terminal_error() {
    let (tx, rx) = bounded(/*cap*/ 1);
    let mut pending = Some(PendingRealtimeEvent {
        event: RealtimeEvent::Error("original failure".to_string()),
        should_stop: true,
    });
    let error = flush_pending_realtime_event(&tx, &mut pending)
        .await
        .expect_err("the error event still terminates the input task");
    assert_eq!(error.to_string(), "realtime stream error event received");
    assert!(pending.is_none());
    assert_eq!(
        rx.recv().await.expect("original error event"),
        RealtimeEvent::Error("original failure".to_string())
    );
    flush_pending_realtime_event(&tx, &mut pending)
        .await
        .expect("an already delivered event is not sent again");
    assert!(rx.try_recv().is_err());
}

#[tokio::test]
async fn closed_receiver_preserves_the_original_error_and_consumes_the_failed_event() {
    let (tx, rx) = bounded(/*cap*/ 1);
    drop(rx);
    let mut pending = Some(PendingRealtimeEvent {
        event: RealtimeEvent::ConversationItemDone {
            item_id: "unforwardable".to_string(),
        },
        should_stop: false,
    });
    let error = flush_pending_realtime_event(&tx, &mut pending)
        .await
        .expect_err("the receiver is closed");
    assert_eq!(error.to_string(), "realtime output event channel closed");
    assert_eq!(error.chain().count(), 1);
    assert!(pending.is_none());
}
