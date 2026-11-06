use super::process::UnifiedExecProcess;
use crate::unified_exec::UnifiedExecError;
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
use std::collections::VecDeque;
use std::sync::Arc;
use tokio::sync::Mutex;
use tokio::sync::broadcast;
use tokio::sync::watch;
use tokio::time::Duration;
use tokio::time::Instant;

struct MockExecProcess {
    process_id: ProcessId,
    write_response: WriteResponse,
    read_responses: Mutex<VecDeque<ReadResponse>>,
    terminate_error: Option<String>,
    wake_tx: watch::Sender<u64>,
    events: broadcast::Sender<ExecProcessEvent>,
}

impl MockExecProcess {
    async fn read(&self) -> Result<ReadResponse, ExecServerError> {
        Ok(self
            .read_responses
            .lock()
            .await
            .pop_front()
            .unwrap_or(ReadResponse {
                chunks: Vec::new(),
                next_seq: 1,
                exited: false,
                exit_code: None,
                closed: false,
                failure: None,
                sandbox_denied: false,
            }))
    }

    async fn terminate(&self) -> Result<(), ExecServerError> {
        if let Some(message) = &self.terminate_error {
            return Err(ExecServerError::Protocol(message.clone()));
        }
        Ok(())
    }
}

impl ExecProcess for MockExecProcess {
    fn process_id(&self) -> &ProcessId {
        &self.process_id
    }

    fn subscribe_wake(&self) -> watch::Receiver<u64> {
        self.wake_tx.subscribe()
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
        Box::pin(MockExecProcess::read(self))
    }

    fn write(&self, _chunk: Vec<u8>) -> ExecProcessFuture<'_, WriteResponse> {
        Box::pin(async { Ok(self.write_response.clone()) })
    }

    fn signal(&self, _signal: ProcessSignal) -> ExecProcessFuture<'_, ()> {
        Box::pin(async { Ok(()) })
    }

    fn terminate(&self) -> ExecProcessFuture<'_, ()> {
        Box::pin(MockExecProcess::terminate(self))
    }
}

pub(super) async fn remote_process(
    write_status: WriteStatus,
    terminate_error: Option<String>,
    sandbox_type: codex_sandboxing::SandboxType,
) -> UnifiedExecProcess {
    remote_process_and_events(write_status, terminate_error, sandbox_type)
        .await
        .0
}

async fn remote_process_and_events(
    write_status: WriteStatus,
    terminate_error: Option<String>,
    sandbox_type: codex_sandboxing::SandboxType,
) -> (UnifiedExecProcess, broadcast::Sender<ExecProcessEvent>) {
    let (wake_tx, _wake_rx) = watch::channel(0);
    let (events, _) = broadcast::channel(8);
    let started = StartedExecProcess {
        process: Arc::new(MockExecProcess {
            process_id: "test-process".to_string().into(),
            write_response: WriteResponse {
                status: write_status,
            },
            read_responses: Mutex::new(VecDeque::new()),
            terminate_error,
            wake_tx,
            events: events.clone(),
        }),
        sandbox_type: Some(sandbox_type),
    };

    let process = UnifiedExecProcess::from_exec_server_started(started)
        .await
        .expect("remote process should start");
    (process, events)
}

pub(super) async fn exited_remote_process(
    write_status: WriteStatus,
    terminate_error: Option<String>,
    sandbox_type: codex_sandboxing::SandboxType,
) -> anyhow::Result<UnifiedExecProcess> {
    let (process, events) =
        remote_process_and_events(write_status, terminate_error, sandbox_type).await;
    events.send(ExecProcessEvent::Exited {
        seq: 1,
        exit_code: 0,
        sandbox_denied: Some(false),
    })?;
    events.send(ExecProcessEvent::Closed { seq: 2 })?;
    tokio::time::timeout(
        std::time::Duration::from_secs(2),
        process.cancellation_token().cancelled(),
    )
    .await?;
    anyhow::ensure!(
        process.has_exited(),
        "the actual Exited event was not observed"
    );
    Ok(process)
}

#[tokio::test]
async fn remote_write_unknown_process_marks_process_exited() -> anyhow::Result<()> {
    let process = exited_remote_process(
        WriteStatus::UnknownProcess,
        /*terminate_error*/ None,
        codex_sandboxing::SandboxType::None,
    )
    .await?;

    let err = process
        .write(b"hello")
        .await
        .expect_err("expected write failure");

    assert!(matches!(err, UnifiedExecError::WriteToStdin));
    assert!(process.has_exited());
    Ok(())
}

#[tokio::test]
async fn remote_write_closed_stdin_marks_process_exited() -> anyhow::Result<()> {
    let process = exited_remote_process(
        WriteStatus::StdinClosed,
        /*terminate_error*/ None,
        codex_sandboxing::SandboxType::None,
    )
    .await?;

    let err = process
        .write(b"hello")
        .await
        .expect_err("expected write failure");

    assert!(matches!(err, UnifiedExecError::WriteToStdin));
    assert!(process.has_exited());
    Ok(())
}

#[tokio::test]
async fn fail_and_terminate_preserves_failure_message() -> anyhow::Result<()> {
    let process = exited_remote_process(
        WriteStatus::Accepted,
        /*terminate_error*/ None,
        codex_sandboxing::SandboxType::None,
    )
    .await?;

    process.fail_and_terminate("network denied".to_string());
    process.fail_and_terminate("second failure".to_string());

    assert!(process.has_exited());
    assert_eq!(
        process.failure_message(),
        Some("network denied".to_string())
    );
    Ok(())
}

#[tokio::test]
async fn remote_terminate_confirmed_updates_state_on_success_only() -> anyhow::Result<()> {
    let process = remote_process(
        WriteStatus::Accepted,
        Some("terminate unavailable".to_string()),
        codex_sandboxing::SandboxType::None,
    )
    .await;

    let err = process
        .terminate_confirmed(Instant::now() + Duration::from_secs(1))
        .await
        .expect_err("expected terminate failure");

    assert!(matches!(err, UnifiedExecError::ProcessFailed { .. }));
    assert!(!process.has_exited());

    let process = exited_remote_process(
        WriteStatus::Accepted,
        /*terminate_error*/ None,
        codex_sandboxing::SandboxType::None,
    )
    .await?;

    process
        .terminate_confirmed(Instant::now() + Duration::from_secs(1))
        .await
        .expect("terminate should succeed");

    assert!(process.has_exited());
    Ok(())
}

#[tokio::test]
async fn remote_process_preserves_executor_sandbox_type() {
    let process = remote_process(
        WriteStatus::Accepted,
        /*terminate_error*/ None,
        codex_sandboxing::SandboxType::LinuxSeccomp,
    )
    .await;

    assert_eq!(
        process.sandbox_type(),
        codex_sandboxing::SandboxType::LinuxSeccomp
    );
}
