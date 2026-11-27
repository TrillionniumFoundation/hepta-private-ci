use super::RetryTelemetryCapture;
use super::RetryTelemetryEvent;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::process::Command;
use std::sync::Arc;
use std::sync::Barrier;
use std::time::Duration;
use tokio::sync::mpsc;

const CHILD_ENV: &str = "CODEX_RETRY_CAPTURE_REGISTRATION_CHILD";
const TEST_NAME: &str =
    "suite::retry_after::capture_tests::retry_capture_registration_is_thread_local";

fn emit_retry_and_request(attempt: u64) {
    tracing::event!(
        target: "codex_otel.trace_safe",
        tracing::Level::TRACE,
        event.name = "codex.retry",
        retry.attempt = attempt,
        retry.delay_ms = 0_u64,
        retry.layer = "http",
        retry.operation = "request",
    );
    if tracing::enabled!(target: "codex_http_client::transport", tracing::Level::TRACE) {
        tracing::trace!(target: "codex_http_client::transport", "capture test request");
    }
}

// Separate macro locations ensure these callsites are still unregistered after
// the other capture has exited; rebuilding an earlier callsite cannot mask this.
fn emit_fresh_retry_and_request(attempt: u64) {
    tracing::event!(
        target: "codex_otel.trace_safe",
        tracing::Level::TRACE,
        event.name = "codex.retry",
        retry.attempt = attempt,
        retry.delay_ms = 0_u64,
        retry.layer = "http",
        retry.operation = "request",
    );
    if tracing::enabled!(target: "codex_http_client::transport", tracing::Level::TRACE) {
        tracing::trace!(target: "codex_http_client::transport", "fresh capture test request");
    }
}

fn assert_retry(capture: &mut RetryTelemetryCapture, attempt: u64) -> Result<()> {
    assert_eq!(
        capture.events.try_recv()?,
        RetryTelemetryEvent {
            attempt,
            delay: Duration::ZERO,
            layer: "http".to_string(),
            operation: "request".to_string(),
        }
    );
    let _ = capture.resumptions.try_recv()?;
    assert_eq!(
        capture.events.try_recv(),
        Err(mpsc::error::TryRecvError::Empty)
    );
    assert_eq!(
        capture.resumptions.try_recv(),
        Err(mpsc::error::TryRecvError::Empty)
    );
    Ok(())
}

#[test]
fn retry_capture_registration_is_thread_local() -> Result<()> {
    if std::env::var_os(CHILD_ENV).is_none() {
        // Isolate the global callsite registry from other test cases. Another
        // live subscriber in this process would otherwise hide the regression.
        let output = Command::new(std::env::current_exe()?)
            .arg("--exact")
            .arg(TEST_NAME)
            .arg("--test-threads=1")
            .env(CHILD_ENV, "1")
            .output()?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(
            output.status.success(),
            "isolated capture regression failed\nstdout:\n{stdout}\nstderr:\n{stderr}"
        );
        assert!(
            stdout.contains("test result: ok. 1 passed; 0 failed; 0 ignored;"),
            "the child must execute exactly one regression\n{stdout}"
        );
        return Ok(());
    }

    assert!(tracing::dispatcher::get_default(|dispatch| {
        dispatch.is::<tracing::subscriber::NoSubscriber>()
    }));
    let mut capture = RetryTelemetryCapture::install();
    let capture_weak = tracing::dispatcher::get_default(tracing::Dispatch::downgrade);
    std::thread::spawn(|| {
        assert!(tracing::dispatcher::get_default(|dispatch| {
            dispatch.is::<tracing::subscriber::NoSubscriber>()
        }));
        emit_retry_and_request(/*attempt*/ 1);
    })
    .join()
    .expect("unsubscribed registration worker should exit");
    assert_eq!(
        capture.events.try_recv(),
        Err(mpsc::error::TryRecvError::Empty)
    );
    assert_eq!(
        capture.resumptions.try_recv(),
        Err(mpsc::error::TryRecvError::Empty)
    );
    emit_retry_and_request(/*attempt*/ 2);
    assert_retry(&mut capture, /*attempt*/ 2)?;

    let ready = Arc::new(Barrier::new(/*n*/ 2));
    let emitted = Arc::new(Barrier::new(/*n*/ 2));
    let worker_ready = Arc::clone(&ready);
    let worker_emitted = Arc::clone(&emitted);
    let worker = std::thread::spawn(move || -> Result<()> {
        let mut second = RetryTelemetryCapture::install();
        let second_weak = tracing::dispatcher::get_default(tracing::Dispatch::downgrade);
        worker_ready.wait();
        emit_retry_and_request(/*attempt*/ 22);
        worker_emitted.wait();
        assert_retry(&mut second, /*attempt*/ 22)?;
        drop(second);
        assert!(second_weak.upgrade().is_none());
        assert!(tracing::dispatcher::get_default(|dispatch| {
            dispatch.is::<tracing::subscriber::NoSubscriber>()
        }));
        Ok(())
    });
    ready.wait();
    emit_retry_and_request(/*attempt*/ 11);
    emitted.wait();
    assert_retry(&mut capture, /*attempt*/ 11)?;
    worker.join().expect("second capture worker should exit")?;

    std::thread::spawn(|| {
        assert!(tracing::dispatcher::get_default(|dispatch| {
            dispatch.is::<tracing::subscriber::NoSubscriber>()
        }));
        emit_fresh_retry_and_request(/*attempt*/ 33);
    })
    .join()
    .expect("fresh registration worker should exit");
    assert_eq!(
        capture.events.try_recv(),
        Err(mpsc::error::TryRecvError::Empty)
    );
    emit_fresh_retry_and_request(/*attempt*/ 44);
    assert_retry(&mut capture, /*attempt*/ 44)?;

    let mut nested = RetryTelemetryCapture::install();
    emit_retry_and_request(/*attempt*/ 55);
    assert_retry(&mut nested, /*attempt*/ 55)?;
    drop(nested);
    emit_retry_and_request(/*attempt*/ 66);
    assert_retry(&mut capture, /*attempt*/ 66)?;
    drop(capture);
    assert!(capture_weak.upgrade().is_none());
    assert!(tracing::dispatcher::get_default(|dispatch| {
        dispatch.is::<tracing::subscriber::NoSubscriber>()
    }));
    Ok(())
}

#[test]
fn registration_anchor_drops_with_capture() {
    let capture = RetryTelemetryCapture::install();
    let anchor_weak = capture.registration_anchor.downgrade();
    assert!(anchor_weak.upgrade().is_some());
    drop(capture);
    assert!(anchor_weak.upgrade().is_none());
}
