//! Real local channels only. These controls neither construct a Root launch nor
//! run a fit, supply a user, activate trust or claim an end-to-end deployment.

use std::future::Future;
use std::future::poll_fn;
use std::task::Poll;
use std::time::Duration;

use tokio::sync::oneshot;

use super::receive_before_original_end;
use crate::terminal_learning_runtime::paired_terminal_evaluator_channel_v1;

#[tokio::test]
async fn handoff_retains_the_actual_evaluator_channel_and_its_original_peer() {
    let (peer, inbox) = paired_terminal_evaluator_channel_v1();
    let (send, receive) = oneshot::channel();
    assert!(send.send(inbox).is_ok());
    let end = tokio::time::Instant::now() + Duration::from_secs(/*secs*/ 1);
    let mut received = receive_before_original_end(receive, end).await.unwrap();
    let mut waiting = Box::pin(received.receive());
    poll_fn(|context| {
        assert!(waiting.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
    drop(peer);
    assert!(
        tokio::time::timeout_at(end, waiting)
            .await
            .unwrap()
            .is_none()
    );
}

#[tokio::test]
async fn expired_ready_handoff_and_missing_launch_cannot_create_an_inbox() {
    let (_peer, inbox) = paired_terminal_evaluator_channel_v1();
    let (send, receive) = oneshot::channel();
    assert!(send.send(inbox).is_ok());
    let expired = tokio::time::Instant::now() - Duration::from_secs(/*secs*/ 1);
    let result = receive_before_original_end(receive, expired).await;
    assert!(matches!(result, Err(error) if error.to_string().contains("deadline expired")));
    let (send, receive) = oneshot::channel::<crate::PairedTerminalEvaluatorInboxV1>();
    drop(send);
    let end = tokio::time::Instant::now() + Duration::from_secs(/*secs*/ 1);
    let result = receive_before_original_end(receive, end).await;
    assert!(matches!(result, Err(error) if error.to_string().contains("launch disappeared")));
}
