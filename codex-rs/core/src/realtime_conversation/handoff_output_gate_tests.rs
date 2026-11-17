use super::send_owned_handoff_output;
use super::tests::handoff;
use super::tests::output_complete;
use crate::realtime_conversation::RealtimeOutbound;
use crate::realtime_conversation::RealtimeSessionKind;
use futures::poll;
use pretty_assertions::assert_eq;
use std::task::Poll;

#[tokio::test]
async fn backpressure_serializes_ack_progress_and_retirement_before_returning() {
    let (mut state, _unused_rx) = handoff(RealtimeSessionKind::V2);
    let (tx, rx) = async_channel::bounded(/*cap*/ 1);
    state.output_tx = tx;
    state.stream.lock().await.pending_steer_ack = Some("steer".to_string());
    let queued = RealtimeOutbound::StandaloneSpeech {
        text: "already queued".to_string(),
    };
    state
        .output_tx
        .send(queued.clone())
        .await
        .expect("fill queue");
    let update = RealtimeOutbound::HandoffUpdate {
        handoff_id: "owner".to_string(),
        text: "progress".to_string(),
        phase: None,
    };
    let completed = RealtimeOutbound::CompletedHandoff {
        handoff_id: "owner".to_string(),
        text: "complete".to_string(),
        phase: None,
    };
    let progress = send_owned_handoff_output(&state, Some(update.clone()), /*complete*/ false);
    let retirement =
        send_owned_handoff_output(&state, Some(completed.clone()), /*complete*/ true);
    let late = send_owned_handoff_output(
        &state,
        Some(RealtimeOutbound::HandoffAppend {
            handoff_id: "owner".to_string(),
            text: "late timer".to_string(),
            phase: None,
        }),
        /*complete*/ false,
    );
    tokio::pin!(progress, retirement, late);
    assert!(matches!(poll!(progress.as_mut()), Poll::Pending));
    assert!(
        state
            .stream
            .try_lock()
            .expect("the stream guard is released before the send waits")
            .pending_steer_ack
            .is_none()
    );
    assert!(matches!(poll!(retirement.as_mut()), Poll::Pending));
    assert!(matches!(poll!(late.as_mut()), Poll::Pending));
    assert_eq!(rx.recv().await.expect("queued output"), queued);
    assert!(matches!(poll!(progress.as_mut()), Poll::Pending));
    assert!(matches!(poll!(retirement.as_mut()), Poll::Pending));
    assert_eq!(
        rx.recv().await.expect("accepted steering acknowledgement"),
        RealtimeOutbound::HandoffSteerAck {
            handoff_id: "steer".to_string(),
        }
    );
    assert!(matches!(poll!(progress.as_mut()), Poll::Ready(Ok(()))));
    assert!(matches!(poll!(retirement.as_mut()), Poll::Pending));
    // Marking retirement does not let another caller return before its send.
    assert!(matches!(poll!(late.as_mut()), Poll::Pending));
    assert_eq!(rx.recv().await.expect("progress"), update);
    retirement.await.expect("retirement sends before returning");
    late.await
        .expect("late output waits, then observes retirement");
    assert_eq!(rx.recv().await.expect("completion"), completed);
    assert!(rx.try_recv().is_err());
    assert!(output_complete(&state).await);
}

#[tokio::test]
async fn cancellation_releases_coordination_without_undoing_committed_retirement() {
    for complete in [false, true] {
        let (mut state, _unused_rx) = handoff(RealtimeSessionKind::V2);
        let (tx, rx) = async_channel::bounded(/*cap*/ 1);
        state.output_tx = tx;
        state.stream.lock().await.pending_steer_ack = Some("accepted steer".to_string());
        let queued = RealtimeOutbound::StandaloneSpeech {
            text: "already queued".to_string(),
        };
        state
            .output_tx
            .send(queued.clone())
            .await
            .expect("fill queue");
        let original = if complete {
            RealtimeOutbound::CompletedHandoff {
                handoff_id: "owner".to_string(),
                text: "cancelled completion".to_string(),
                phase: None,
            }
        } else {
            RealtimeOutbound::HandoffUpdate {
                handoff_id: "owner".to_string(),
                text: "cancelled progress".to_string(),
                phase: None,
            }
        };
        let waiting =
            send_owned_handoff_output(&state, /*output*/ None, /*complete*/ false);
        tokio::pin!(waiting);
        {
            let delivery = send_owned_handoff_output(&state, Some(original), complete);
            tokio::pin!(delivery);
            assert!(matches!(poll!(delivery.as_mut()), Poll::Pending));
            assert!(matches!(poll!(waiting.as_mut()), Poll::Pending));
            // Drop the actual blocked send; no detached task or timer owns it.
        }
        waiting
            .await
            .expect("cancellation releases the output permit");
        assert_eq!(rx.recv().await.expect("existing queued output"), queued);
        // The original path also takes the ACK before a cancellable send.
        assert!(state.stream.lock().await.pending_steer_ack.is_none());
        let next = RealtimeOutbound::HandoffUpdate {
            handoff_id: "owner".to_string(),
            text: "next progress".to_string(),
            phase: None,
        };
        send_owned_handoff_output(&state, Some(next.clone()), /*complete*/ false)
            .await
            .expect("the next call observes the retained completion state");
        if complete {
            assert!(rx.try_recv().is_err());
        } else {
            assert_eq!(rx.recv().await.expect("next progress"), next);
            assert!(rx.try_recv().is_err());
        }
        assert_eq!(output_complete(&state).await, complete);
    }
}
