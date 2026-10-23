use super::wait_for_terminalization_or_listener_cancel;
use pretty_assertions::assert_eq;
use std::ops::ControlFlow;
use std::task::Poll;
use tokio::sync::oneshot;

#[tokio::test]
async fn listener_cancel_releases_pending_wait_without_completing_owner() {
    let (owner_tx, mut owner_rx) = oneshot::channel();
    let (cancel_tx, mut cancel_rx) = oneshot::channel();
    let mut wait = Box::pin(wait_for_terminalization_or_listener_cancel(
        async {
            (&mut owner_rx)
                .await
                .expect("owner completes independently");
        },
        &mut cancel_rx,
    ));
    assert!(futures::poll!(wait.as_mut()).is_pending());

    cancel_tx.send(()).expect("listener is still waiting");
    assert_eq!(
        futures::poll!(wait.as_mut()),
        Poll::Ready(ControlFlow::Break(()))
    );
    drop(wait);
    assert_eq!(
        owner_rx.try_recv(),
        Err(oneshot::error::TryRecvError::Empty)
    );

    owner_tx
        .send(())
        .expect("owner was not cancelled or completed");
    assert_eq!(owner_rx.await, Ok(()));
}

#[tokio::test]
async fn owner_must_complete_before_an_active_listener_can_continue() {
    let (owner_tx, owner_rx) = oneshot::channel();
    let (cancel_tx, mut cancel_rx) = oneshot::channel();
    let mut wait = Box::pin(wait_for_terminalization_or_listener_cancel(
        async { owner_rx.await.expect("owner completion") },
        &mut cancel_rx,
    ));
    assert!(futures::poll!(wait.as_mut()).is_pending());

    owner_tx.send(()).expect("owner is still awaited");
    assert_eq!(
        futures::poll!(wait.as_mut()),
        Poll::Ready(ControlFlow::Continue(()))
    );
    drop(wait);
    cancel_tx
        .send(())
        .expect("completion did not consume cancellation");
    assert_eq!(cancel_rx.await, Ok(()));
}

#[tokio::test]
async fn cancellation_wins_when_owner_and_listener_are_both_ready() {
    let (owner_tx, mut owner_rx) = oneshot::channel();
    let (cancel_tx, mut cancel_rx) = oneshot::channel();
    owner_tx.send(()).expect("owner receiver");
    cancel_tx.send(()).expect("listener receiver");

    let mut wait = Box::pin(wait_for_terminalization_or_listener_cancel(
        async { (&mut owner_rx).await.expect("owner completion") },
        &mut cancel_rx,
    ));
    assert_eq!(
        futures::poll!(wait.as_mut()),
        Poll::Ready(ControlFlow::Break(()))
    );
    drop(wait);
    assert_eq!(owner_rx.try_recv(), Ok(()));
}

#[tokio::test]
async fn dropped_listener_sender_also_retires_pending_wait() {
    let (owner_tx, mut owner_rx) = oneshot::channel();
    let (cancel_tx, mut cancel_rx) = oneshot::channel();
    drop(cancel_tx);

    let mut wait = Box::pin(wait_for_terminalization_or_listener_cancel(
        async { (&mut owner_rx).await.expect("owner completion") },
        &mut cancel_rx,
    ));
    assert_eq!(
        futures::poll!(wait.as_mut()),
        Poll::Ready(ControlFlow::Break(()))
    );
    drop(wait);
    assert_eq!(
        owner_rx.try_recv(),
        Err(oneshot::error::TryRecvError::Empty)
    );
    owner_tx
        .send(())
        .expect("retiring the listener leaves its owner alone");
}
