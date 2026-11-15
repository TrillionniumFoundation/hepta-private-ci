use std::future::Future;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::task::Context;
use std::task::Poll;
use std::task::Waker;

use pretty_assertions::assert_eq;
use tokio::runtime::Builder;
use tokio::sync::oneshot;

// Exercise the exact private helper used by the vendored store. Bazel declares
// this source explicitly in integration_compile_data_extra.
#[path = "../../third_party/matrix-sdk-sqlite-0.19.1/src/cipher_task.rs"]
mod cipher_task;

type TestResult = Result<(), Box<dyn std::error::Error>>;

struct DropWitness(Option<oneshot::Sender<()>>);

impl Drop for DropWitness {
    fn drop(&mut self) {
        if let Some(sender) = self.0.take() {
            let _ = sender.send(());
        }
    }
}

#[test]
fn cancelling_a_queued_cipher_releases_its_capture_without_running_it() -> TestResult {
    let runtime = Builder::new_current_thread()
        .max_blocking_threads(1)
        .enable_all()
        .build()?;
    runtime.block_on(async {
        let (started_tx, started_rx) = oneshot::channel();
        let (release_tx, release_rx) = std::sync::mpsc::channel();
        let blocker = tokio::task::spawn_blocking(move || {
            let _ = started_tx.send(());
            release_rx.recv()
        });
        started_rx.await?;

        let (dropped_tx, dropped_rx) = oneshot::channel();
        let captured = DropWitness(Some(dropped_tx));
        let calls = Arc::new(AtomicUsize::new(0));
        let observed_calls = Arc::clone(&calls);
        let mut cipher = Box::pin(cipher_task::run(move || {
            let _captured = captured;
            calls.fetch_add(1, Ordering::SeqCst);
        }));
        let poll = cipher
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()));
        // Release the deliberately blocked worker before any assertion can
        // unwind and wait for the runtime's blocking pool to shut down.
        drop(cipher);
        release_tx.send(())?;
        blocker.await??;
        dropped_rx.await?;

        assert!(matches!(poll, Poll::Pending));
        assert_eq!(observed_calls.load(Ordering::SeqCst), 0);
        Ok(())
    })
}

#[test]
fn cancelling_a_running_cipher_drops_its_unclaimed_result() -> TestResult {
    let runtime = Builder::new_current_thread()
        .max_blocking_threads(1)
        .enable_all()
        .build()?;
    runtime.block_on(async {
        let (started_tx, started_rx) = oneshot::channel();
        let (release_tx, release_rx) = std::sync::mpsc::channel();
        let (dropped_tx, dropped_rx) = oneshot::channel();
        let completed = Arc::new(AtomicUsize::new(0));
        let observed_completed = Arc::clone(&completed);
        let mut cipher = Box::pin(cipher_task::run(move || {
            let _ = started_tx.send(());
            let _ = release_rx.recv();
            completed.fetch_add(1, Ordering::SeqCst);
            DropWitness(Some(dropped_tx))
        }));
        let poll = cipher
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()));
        started_rx.await?;
        // This current-thread executor can make progress while the computation
        // is still running. Cancellation does not claim to interrupt that work.
        drop(cipher);
        release_tx.send(())?;
        dropped_rx.await?;

        assert!(matches!(poll, Poll::Pending));
        assert_eq!(observed_completed.load(Ordering::SeqCst), 1);
        Ok(())
    })
}

#[tokio::test]
async fn completed_cipher_returns_its_exact_result() -> TestResult {
    assert_eq!(
        cipher_task::run(|| (17_u64, vec![2_u8, 3, 5])).await?,
        (17, vec![2, 3, 5])
    );
    Ok(())
}

#[tokio::test]
async fn cipher_worker_panic_is_a_join_error() {
    let result = cipher_task::run(|| panic!("controlled cipher worker failure")).await;
    assert!(matches!(result, Err(error) if error.is_panic()));
}
