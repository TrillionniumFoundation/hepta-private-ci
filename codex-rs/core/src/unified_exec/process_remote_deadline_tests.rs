use super::RemoteFixture;
use anyhow::Context;
use anyhow::Result;
use codex_exec_server::ExecProcessEvent;
use codex_exec_server::ReadResponse;
use codex_exec_server::WriteStatus;
use pretty_assertions::assert_eq;
use std::time::Duration;
use tokio::time::Instant;

#[tokio::test]
async fn explicit_deadline_waits_for_original_remote_exit_after_ack() -> Result<()> {
    let fixture = RemoteFixture::new(WriteStatus::Accepted).await?;
    fixture.release_ack();
    let mut operation = Box::pin(
        fixture
            .process
            .terminate_confirmed_until(Instant::now() + Duration::from_secs(2)),
    );
    assert!(futures::poll!(operation.as_mut()).is_pending());
    assert_eq!(*fixture.remote.termination_started.borrow(), 1);
    assert!(!fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), None);
    fixture.exited(61)?;
    operation.await?;
    assert!(fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), Some(61));
    assert_eq!(*fixture.remote.termination_started.borrow(), 1);
    Ok(())
}

#[tokio::test]
async fn explicit_deadline_bounds_unacknowledged_remote_request() -> Result<()> {
    let fixture = RemoteFixture::new(WriteStatus::Accepted).await?;
    let mut operation = Box::pin(
        fixture
            .process
            .terminate_confirmed_until(Instant::now() + Duration::from_secs(2)),
    );
    assert!(futures::poll!(operation.as_mut()).is_pending());
    assert_eq!(*fixture.remote.termination_started.borrow(), 1);
    let error = operation
        .await
        .expect_err("same deadline includes the pending request");
    assert!(error.to_string().contains("caller-provided deadline"));
    assert!(!fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), None);
    let failure = fixture
        .process
        .failure_message()
        .context("deadline failure")?;
    fixture.release_ack();
    fixture.exited(63)?;
    fixture.wait_for_state(|state| state.has_exited).await?;
    assert_eq!(fixture.process.exit_code(), Some(63));
    assert_eq!(fixture.process.failure_message(), Some(failure));
    assert_eq!(*fixture.remote.termination_started.borrow(), 1);
    Ok(())
}

#[tokio::test]
async fn cancelled_remote_deadline_observation_never_turns_ack_into_exit() -> Result<()> {
    let fixture = RemoteFixture::new(WriteStatus::Accepted).await?;
    let mut operation = Box::pin(
        fixture
            .process
            .terminate_confirmed_until(Instant::now() + Duration::from_secs(2)),
    );
    assert!(futures::poll!(operation.as_mut()).is_pending());
    assert_eq!(*fixture.remote.termination_started.borrow(), 1);
    drop(operation);
    assert!(!fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), None);
    let failure = fixture
        .process
        .failure_message()
        .context("cancelled observation")?;
    fixture.release_ack();
    fixture.exited(67)?;
    fixture.wait_for_state(|state| state.has_exited).await?;
    assert_eq!(fixture.process.exit_code(), Some(67));
    assert_eq!(fixture.process.failure_message(), Some(failure));
    assert_eq!(*fixture.remote.termination_started.borrow(), 1);
    Ok(())
}

#[tokio::test]
async fn explicit_deadline_preserves_native_exit_without_numeric_code() -> Result<()> {
    let fixture = RemoteFixture::new(WriteStatus::Accepted).await?;
    *fixture.remote.read_response.lock().await = ReadResponse {
        chunks: Vec::new(),
        next_seq: 2,
        exited: true,
        exit_code: None,
        closed: false,
        failure: None,
        sandbox_denied: false,
    };
    fixture.remote.events.send(ExecProcessEvent::Exited {
        seq: 1,
        exit_code: 0,
        sandbox_denied: None,
    })?;
    fixture.wait_for_state(|state| state.has_exited).await?;
    fixture
        .process
        .terminate_confirmed_until(Instant::now() + Duration::from_secs(2))
        .await?;
    assert!(fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), None);
    assert_eq!(*fixture.remote.termination_started.borrow(), 0);
    Ok(())
}
