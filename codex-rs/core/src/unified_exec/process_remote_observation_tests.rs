use super::TERMINATION_NOT_OBSERVED;
use super::UnifiedExecProcess;
use crate::unified_exec::UnifiedExecError;
use crate::unified_exec::process_state::ProcessState;
use anyhow::Result;
use codex_exec_server::ExecProcess;
use codex_exec_server::ExecProcessEvent;
use codex_exec_server::ExecProcessEventReceiver;
use codex_exec_server::ExecProcessFuture;
use codex_exec_server::ExecServerError;
use codex_exec_server::ProcessId;
use codex_exec_server::ProcessSignal;
use codex_exec_server::ReadResponse;
use codex_exec_server::StartedExecProcess;
use codex_exec_server::WriteResponse;
use codex_exec_server::WriteStatus;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;
use tokio::sync::broadcast;
use tokio::sync::watch;

struct RemoteProcess {
    id: ProcessId,
    events: broadcast::Sender<ExecProcessEvent>,
    wake: watch::Sender<u64>,
    write_status: WriteStatus,
    read_response: Mutex<ReadResponse>,
    termination_started: watch::Sender<u64>,
    release_ack: watch::Sender<bool>,
}

impl ExecProcess for RemoteProcess {
    fn process_id(&self) -> &ProcessId {
        &self.id
    }

    fn subscribe_wake(&self) -> watch::Receiver<u64> {
        self.wake.subscribe()
    }

    fn subscribe_events(&self) -> ExecProcessEventReceiver {
        ExecProcessEventReceiver::from_receiver(self.events.subscribe())
    }

    fn read(
        &self,
        _after_seq: Option<u64>,
        _max_bytes: Option<usize>,
        _wait_ms: Option<u64>,
    ) -> ExecProcessFuture<'_, ReadResponse> {
        Box::pin(async { Ok(self.read_response.lock().await.clone()) })
    }

    fn write(&self, _chunk: Vec<u8>) -> ExecProcessFuture<'_, WriteResponse> {
        Box::pin(async {
            Ok(WriteResponse {
                status: self.write_status,
            })
        })
    }

    fn signal(&self, _signal: ProcessSignal) -> ExecProcessFuture<'_, ()> {
        Box::pin(async { Ok(()) })
    }

    fn terminate(&self) -> ExecProcessFuture<'_, ()> {
        Box::pin(async {
            self.termination_started.send_modify(|count| *count += 1);
            let mut release = self.release_ack.subscribe();
            release
                .wait_for(|ready| *ready)
                .await
                .map_err(|error| ExecServerError::Protocol(error.to_string()))?;
            Ok(())
        })
    }
}

struct RemoteFixture {
    process: Arc<UnifiedExecProcess>,
    remote: Arc<RemoteProcess>,
}

impl RemoteFixture {
    async fn new(write_status: WriteStatus) -> Result<Self> {
        let (events, _) = broadcast::channel(8);
        let (wake, _) = watch::channel(0);
        let (termination_started, _) = watch::channel(0);
        let (release_ack, _) = watch::channel(false);
        let remote = Arc::new(RemoteProcess {
            id: "controlled-observation".to_string().into(),
            events,
            wake,
            write_status,
            read_response: Mutex::new(ReadResponse {
                chunks: Vec::new(),
                next_seq: 1,
                exited: false,
                exit_code: None,
                closed: false,
                failure: None,
                sandbox_denied: false,
            }),
            termination_started,
            release_ack,
        });
        let process = Arc::new(
            UnifiedExecProcess::from_exec_server_started(StartedExecProcess {
                process: remote.clone(),
                sandbox_type: Some(codex_sandboxing::SandboxType::None),
            })
            .await?,
        );
        Ok(Self { process, remote })
    }

    async fn wait_for_state(&self, condition: impl Fn(&ProcessState) -> bool) -> Result<()> {
        let mut state = self.process.state_rx.clone();
        tokio::time::timeout(Duration::from_secs(2), state.wait_for(condition)).await??;
        Ok(())
    }

    async fn wait_for_termination(&self) -> Result<()> {
        let mut started = self.remote.termination_started.subscribe();
        tokio::time::timeout(
            Duration::from_secs(2),
            started.wait_for(|count| *count != 0),
        )
        .await??;
        Ok(())
    }

    fn release_ack(&self) {
        self.remote.release_ack.send_modify(|ready| *ready = true);
    }

    fn exited(&self, code: i32) -> Result<()> {
        self.remote.events.send(ExecProcessEvent::Exited {
            seq: 1,
            exit_code: code,
            sandbox_denied: Some(false),
        })?;
        Ok(())
    }
}

impl Drop for RemoteFixture {
    fn drop(&mut self) {
        self.release_ack();
    }
}

#[tokio::test]
async fn remote_stdin_or_handle_errors_do_not_establish_exit() -> Result<()> {
    for status in [WriteStatus::StdinClosed, WriteStatus::UnknownProcess] {
        let fixture = RemoteFixture::new(status).await?;
        let error = fixture
            .process
            .write(b"input")
            .await
            .expect_err("write refused");
        assert!(matches!(error, UnifiedExecError::WriteToStdin));
        assert!(!fixture.process.has_exited());
        assert_eq!(fixture.process.exit_code(), None);
        fixture.exited(41)?;
        fixture.wait_for_state(|state| state.has_exited).await?;
        assert_eq!(fixture.process.exit_code(), Some(41));
    }
    Ok(())
}

#[tokio::test]
async fn termination_ack_without_exit_is_indeterminate() -> Result<()> {
    let fixture = RemoteFixture::new(WriteStatus::Accepted).await?;
    let task = tokio::spawn({
        let process = Arc::clone(&fixture.process);
        async move { process.terminate_confirmed().await }
    });
    fixture.wait_for_termination().await?;
    fixture.release_ack();
    let error = tokio::time::timeout(Duration::from_secs(2), task)
        .await??
        .expect_err("an ACK carries no native exit observation");
    assert!(matches!(error, UnifiedExecError::ProcessFailed { .. }));
    assert!(!fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), None);
    assert_eq!(
        fixture.process.failure_message(),
        Some(TERMINATION_NOT_OBSERVED.to_string())
    );
    Ok(())
}

#[tokio::test]
async fn termination_ack_after_observation_loss_stays_indeterminate() -> Result<()> {
    let fixture = RemoteFixture::new(WriteStatus::Accepted).await?;
    let task = tokio::spawn({
        let process = Arc::clone(&fixture.process);
        async move { process.terminate_confirmed().await }
    });
    fixture.wait_for_termination().await?;
    // Force observation failure strictly between request entry and its ACK.
    fixture.remote.events.send(ExecProcessEvent::Failed(
        "lost original observation".to_string(),
    ))?;
    fixture
        .wait_for_state(|state| state.failure_message.is_some())
        .await?;
    assert!(!fixture.process.has_exited());
    fixture.release_ack();
    let error = tokio::time::timeout(Duration::from_secs(2), task)
        .await??
        .expect_err("a delayed ACK must not overwrite unknown state");
    assert!(matches!(error, UnifiedExecError::ProcessFailed { .. }));
    fixture
        .process
        .fail_and_terminate("later policy failure".to_string());
    assert!(!fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), None);
    assert_eq!(
        fixture.process.failure_message(),
        Some("lost original observation".to_string())
    );
    Ok(())
}

#[tokio::test]
async fn observed_exit_survives_concurrent_control_failure() -> Result<()> {
    let fixture = RemoteFixture::new(WriteStatus::Accepted).await?;
    let task = tokio::spawn({
        let process = Arc::clone(&fixture.process);
        async move { process.terminate_confirmed().await }
    });
    fixture.wait_for_termination().await?;
    fixture.exited(47)?;
    fixture.wait_for_state(|state| state.has_exited).await?;
    fixture
        .process
        .fail_and_terminate("policy failure after native exit".to_string());
    fixture.release_ack();
    tokio::time::timeout(Duration::from_secs(2), task).await???;
    assert!(fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), Some(47));
    assert_eq!(
        fixture.process.failure_message(),
        Some("policy failure after native exit".to_string())
    );
    Ok(())
}

#[tokio::test]
async fn observed_exit_without_code_is_terminal() -> Result<()> {
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
    // The existing missing-sandbox-field path reads retained same-process
    // facts. Its explicit exited flag is independent of a numeric code.
    fixture.remote.events.send(ExecProcessEvent::Exited {
        seq: 1,
        exit_code: 0,
        sandbox_denied: None,
    })?;
    fixture.wait_for_state(|state| state.has_exited).await?;
    fixture
        .process
        .fail_and_terminate("later failure".to_string());
    fixture.process.terminate_confirmed().await?;
    assert!(fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), None);
    assert_eq!(*fixture.remote.termination_started.borrow(), 0);
    Ok(())
}

#[tokio::test]
async fn logical_failure_before_native_exit_preserves_first_failure() -> Result<()> {
    let fixture = RemoteFixture::new(WriteStatus::Accepted).await?;
    fixture
        .process
        .fail_and_terminate("first policy failure".to_string());
    fixture.wait_for_termination().await?;
    assert!(!fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), None);
    fixture.exited(29)?;
    fixture.wait_for_state(|state| state.has_exited).await?;
    fixture
        .process
        .fail_and_terminate("second failure".to_string());
    assert!(fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), Some(29));
    assert_eq!(
        fixture.process.failure_message(),
        Some("first policy failure".to_string())
    );
    Ok(())
}

#[path = "process_remote_deadline_tests.rs"]
mod deadline_tests;
