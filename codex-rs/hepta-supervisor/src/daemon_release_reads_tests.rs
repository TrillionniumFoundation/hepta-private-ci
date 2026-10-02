use super::*;
use std::future::Future;
use std::sync::Arc;
use std::task::Poll;

fn reader() -> (Arc<ReleaseReads>, mpsc::Receiver<ReadJob>) {
    let (jobs, receiver) = mpsc::sync_channel(1);
    (
        Arc::new(ReleaseReads {
            jobs,
            pending: Mutex::new(None),
        }),
        receiver,
    )
}

fn take_reply(
    receiver: &mpsc::Receiver<ReadJob>,
    expected: &str,
) -> oneshot::Sender<Result<ReleaseReadPin, FleetRegistryError>> {
    match receiver.try_recv().expect("one physical read") {
        ReadJob::Validate { release_id, reply } => {
            assert_eq!(release_id.as_str(), expected);
            reply
        }
        ReadJob::Pause { .. } => panic!("unexpected barrier"),
    }
}

#[tokio::test(flavor = "current_thread")]
async fn timeout_retains_one_read_and_same_release_observes_its_late_result() {
    let (reader, receiver) = reader();
    let cancellation = CancellationToken::new();
    assert!(matches!(
        reader
            .prevalidate("first".parse().unwrap(), &cancellation)
            .await,
        ReadResult::Busy
    ));
    let reply = take_reply(&receiver, "first");
    assert!(matches!(
        reader
            .prevalidate("different".parse().unwrap(), &cancellation)
            .await,
        ReadResult::Busy
    ));
    assert!(
        receiver.try_recv().is_err(),
        "no duplicate or different queued read"
    );
    assert!(
        reply
            .send(Err(FleetRegistryError::Invalid(
                "late read rejection".into()
            )))
            .is_ok()
    );
    assert!(
        matches!(reader.prevalidate("first".parse().unwrap(), &cancellation).await,
        ReadResult::Rejected(FleetRegistryError::Invalid(message)) if message == "late read rejection")
    );
    assert!(
        receiver.try_recv().is_err(),
        "late result is delivered without another read"
    );
    assert!(reader.pending.lock().await.is_none());
}

#[tokio::test(flavor = "current_thread")]
async fn abandoned_request_retains_progress_without_admitting_any_operation() {
    let (reader, receiver) = reader();
    let cancellation = CancellationToken::new();
    let mut request = Box::pin(reader.prevalidate("first".parse().unwrap(), &cancellation));
    std::future::poll_fn(|cx| {
        assert!(request.as_mut().poll(cx).is_pending());
        Poll::Ready(())
    })
    .await;
    let reply = take_reply(&receiver, "first");
    drop(request);
    assert!(
        reply
            .send(Err(FleetRegistryError::ReleasePrevalidationRequired))
            .is_ok()
    );
    assert!(matches!(
        reader
            .prevalidate("first".parse().unwrap(), &cancellation)
            .await,
        ReadResult::Busy
    ));
    assert!(receiver.try_recv().is_err());
    assert!(reader.pending.lock().await.is_none());
}

#[tokio::test(flavor = "current_thread")]
async fn cancelled_daemon_never_submits_a_read() {
    let (reader, receiver) = reader();
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    assert!(matches!(
        reader
            .prevalidate("first".parse().unwrap(), &cancellation)
            .await,
        ReadResult::Stopped
    ));
    assert!(receiver.try_recv().is_err());
}

#[tokio::test(flavor = "current_thread")]
async fn lock_contention_consumes_the_original_wait_budget() {
    let (reader, receiver) = reader();
    let held = reader.pending.lock().await;
    let cancellation = CancellationToken::new();
    let result = tokio::time::timeout(
        Duration::from_millis(500),
        reader.prevalidate("first".parse().unwrap(), &cancellation),
    )
    .await
    .unwrap();
    assert!(matches!(result, ReadResult::Busy));
    assert!(receiver.try_recv().is_err());
    drop(held);
}

#[tokio::test(flavor = "current_thread")]
async fn completed_other_release_is_discarded_before_a_new_physical_read() {
    let (reader, receiver) = reader();
    let cancellation = CancellationToken::new();
    let mut first = Box::pin(reader.prevalidate("first".parse().unwrap(), &cancellation));
    std::future::poll_fn(|cx| {
        assert!(first.as_mut().poll(cx).is_pending());
        Poll::Ready(())
    })
    .await;
    let reply = take_reply(&receiver, "first");
    drop(first);
    assert!(
        reply
            .send(Err(FleetRegistryError::Invalid("old release".into())))
            .is_ok()
    );
    let mut second = Box::pin(reader.prevalidate("second".parse().unwrap(), &cancellation));
    std::future::poll_fn(|cx| {
        assert!(second.as_mut().poll(cx).is_pending());
        Poll::Ready(())
    })
    .await;
    let reply = take_reply(&receiver, "second");
    assert!(
        reply
            .send(Err(FleetRegistryError::Invalid("new release".into())))
            .is_ok()
    );
    assert!(
        matches!(second.await, ReadResult::Rejected(FleetRegistryError::Invalid(message))
        if message == "new release")
    );
}
