use super::*;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::task::Context;
use std::task::Poll;
use std::time::Duration;

#[derive(Default)]
struct TestSink {
    blocked: bool,
    fail_flush: bool,
    blocked_flush: bool,
    sent: Vec<u8>,
}
impl Sink<u8> for TestSink {
    type Error = io::Error;
    fn poll_ready(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<io::Result<()>> {
        if self.blocked {
            Poll::Pending
        } else {
            Poll::Ready(Ok(()))
        }
    }
    fn start_send(mut self: Pin<&mut Self>, item: u8) -> io::Result<()> {
        self.sent.push(item);
        Ok(())
    }
    fn poll_flush(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<io::Result<()>> {
        if self.blocked_flush {
            return Poll::Pending;
        }
        Poll::Ready(if self.fail_flush {
            Err(io::Error::other("uncertain flush"))
        } else {
            Ok(())
        })
    }
    fn poll_close(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        self.poll_flush(cx)
    }
}
fn guard(deadline: Instant, entered: Arc<AtomicUsize>) -> RemoteRequestSendGuard {
    RemoteRequestSendGuard::new(deadline, std::future::pending(), async move {
        Ok(move || {
            entered.fetch_add(1, Ordering::SeqCst);
            Ok(())
        })
    })
}
#[tokio::test]
async fn queued_request_expired_before_dequeue_never_enters_or_sends() {
    let entered = Arc::new(AtomicUsize::new(0));
    let guard = guard(Instant::now(), entered.clone());
    let (mut tx, _rx) = oneshot::channel::<()>();
    let mut sink = TestSink::default();
    assert_eq!(
        send_guarded(&mut sink, 7, &mut tx, guard)
            .await
            .unwrap_err()
            .kind(),
        io::ErrorKind::TimedOut
    );
    assert!(sink.sent.is_empty());
    assert_eq!(entered.load(Ordering::SeqCst), 0);
}
#[tokio::test]
async fn abandoned_queued_request_never_enters_or_sends() {
    let entered = Arc::new(AtomicUsize::new(0));
    let (mut tx, rx) = oneshot::channel::<()>();
    drop(rx);
    let mut sink = TestSink::default();
    assert!(
        send_guarded(
            &mut sink,
            7,
            &mut tx,
            guard(Instant::now() + Duration::from_secs(5), entered.clone())
        )
        .await
        .is_err()
    );
    assert!(sink.sent.is_empty());
    assert_eq!(entered.load(Ordering::SeqCst), 0);
}
#[tokio::test]
async fn stalled_socket_readiness_is_bounded_by_deadline() {
    let entered = Arc::new(AtomicUsize::new(0));
    let (mut tx, _rx) = oneshot::channel::<()>();
    let mut sink = TestSink {
        blocked: true,
        ..Default::default()
    };
    assert_eq!(
        send_guarded(
            &mut sink,
            7,
            &mut tx,
            guard(Instant::now() + Duration::from_millis(5), entered.clone())
        )
        .await
        .unwrap_err()
        .kind(),
        io::ErrorKind::TimedOut
    );
    assert!(sink.sent.is_empty());
    assert_eq!(entered.load(Ordering::SeqCst), 0);
}
#[tokio::test]
async fn stalled_preparation_is_cancelled_without_entering() {
    let (cancel_tx, cancel_rx) = oneshot::channel::<()>();
    let (prepared_tx, prepared_rx) = oneshot::channel();
    let guard = RemoteRequestSendGuard::new(
        Instant::now() + Duration::from_secs(5),
        async {
            let _ = cancel_rx.await;
        },
        async {
            let _ = prepared_tx.send(());
            std::future::pending::<()>().await;
            Ok(|| Ok(()))
        },
    );
    let (mut tx, _rx) = oneshot::channel::<()>();
    let mut sink = TestSink::default();
    let (result, ()) = tokio::join!(send_guarded(&mut sink, 7, &mut tx, guard), async {
        prepared_rx.await.unwrap();
        cancel_tx.send(()).unwrap();
    });
    assert_eq!(result.unwrap_err().kind(), io::ErrorKind::Interrupted);
    assert!(sink.sent.is_empty());
}
#[tokio::test]
async fn rejected_final_authority_never_sends() {
    let guard = RemoteRequestSendGuard::new(
        Instant::now() + Duration::from_secs(5),
        std::future::pending(),
        async { Ok(|| Err::<(), _>(io::Error::new(io::ErrorKind::PermissionDenied, "revoked"))) },
    );
    let (mut tx, _rx) = oneshot::channel::<()>();
    let mut sink = TestSink::default();
    assert_eq!(
        send_guarded(&mut sink, 7, &mut tx, guard)
            .await
            .unwrap_err()
            .kind(),
        io::ErrorKind::PermissionDenied
    );
    assert!(sink.sent.is_empty());
}
#[tokio::test]
async fn deadline_elapsing_inside_entry_never_sends() {
    let guard = RemoteRequestSendGuard::new(
        Instant::now() + Duration::from_millis(10),
        std::future::pending(),
        async {
            Ok(|| {
                std::thread::sleep(Duration::from_millis(20));
                Ok(())
            })
        },
    );
    let (mut tx, _rx) = oneshot::channel::<()>();
    let mut sink = TestSink::default();
    assert_eq!(
        send_guarded(&mut sink, 7, &mut tx, guard)
            .await
            .unwrap_err()
            .kind(),
        io::ErrorKind::TimedOut
    );
    assert!(sink.sent.is_empty());
}
#[tokio::test]
async fn flush_failure_does_not_retry_physical_send() {
    let entered = Arc::new(AtomicUsize::new(0));
    let (mut tx, _rx) = oneshot::channel::<()>();
    let mut sink = TestSink {
        fail_flush: true,
        ..Default::default()
    };
    assert!(
        send_guarded(
            &mut sink,
            7,
            &mut tx,
            guard(Instant::now() + Duration::from_secs(5), entered.clone())
        )
        .await
        .is_err()
    );
    assert_eq!(sink.sent, vec![7]);
    assert_eq!(entered.load(Ordering::SeqCst), 1);
}
#[tokio::test]
async fn successful_guard_enters_once_and_sends_once() {
    let entered = Arc::new(AtomicUsize::new(0));
    let (mut tx, _rx) = oneshot::channel::<()>();
    let mut sink = TestSink::default();
    send_guarded(
        &mut sink,
        7,
        &mut tx,
        guard(Instant::now() + Duration::from_secs(5), entered.clone()),
    )
    .await
    .unwrap();
    assert_eq!(sink.sent, vec![7]);
    assert_eq!(entered.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn cancellation_during_synchronous_entry_prevents_send() {
    let (cancel_tx, cancel_rx) = oneshot::channel::<()>();
    let guard = RemoteRequestSendGuard::new(
        Instant::now() + Duration::from_secs(5),
        async {
            let _ = cancel_rx.await;
        },
        async {
            Ok(move || {
                cancel_tx.send(()).unwrap();
                Ok(())
            })
        },
    );
    let (mut tx, _rx) = oneshot::channel::<()>();
    let mut sink = TestSink::default();
    assert_eq!(
        send_guarded(&mut sink, 7, &mut tx, guard)
            .await
            .unwrap_err()
            .kind(),
        io::ErrorKind::Interrupted
    );
    assert!(sink.sent.is_empty());
}

#[tokio::test]
async fn stalled_flush_is_bounded_without_retry_after_send() {
    let entered = Arc::new(AtomicUsize::new(0));
    let (mut tx, _rx) = oneshot::channel::<()>();
    let mut sink = TestSink {
        blocked_flush: true,
        ..Default::default()
    };
    assert_eq!(
        send_guarded(
            &mut sink,
            7,
            &mut tx,
            guard(Instant::now() + Duration::from_millis(20), entered.clone())
        )
        .await
        .unwrap_err()
        .kind(),
        io::ErrorKind::TimedOut
    );
    assert_eq!(sink.sent, vec![7]);
    assert_eq!(entered.load(Ordering::SeqCst), 1);
}
