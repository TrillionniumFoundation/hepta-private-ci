use super::EXIT_OBSERVATION_LOST;
use super::NoopSpawnLifecycle;
use super::UnifiedExecProcess;
use crate::unified_exec::UnifiedExecError;
use anyhow::Result;
use codex_sandboxing::SandboxType;
use codex_utils_pty::ProcessDriver;
use codex_utils_pty::SpawnedPty;
use codex_utils_pty::spawn_from_driver;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::sync::broadcast;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

struct DriverFixture {
    spawned: SpawnedPty,
    exit_tx: oneshot::Sender<i32>,
    stdout_tx: broadcast::Sender<Vec<u8>>,
    writer_rx: mpsc::Receiver<Vec<u8>>,
    terminations: Arc<AtomicUsize>,
}

fn driver_fixture() -> DriverFixture {
    let (writer_tx, writer_rx) = mpsc::channel(1);
    let (stdout_tx, stdout_rx) = broadcast::channel(8);
    let (exit_tx, exit_rx) = oneshot::channel();
    let terminations = Arc::new(AtomicUsize::new(0));
    let observe_terminations = Arc::clone(&terminations);
    let spawned = spawn_from_driver(ProcessDriver {
        writer_tx,
        stdout_rx,
        stderr_rx: None,
        exit_rx,
        terminator: Some(Box::new(move || {
            observe_terminations.fetch_add(1, Ordering::SeqCst);
        })),
        writer_handle: None,
        resizer: None,
        #[cfg(windows)]
        tty: false,
    });
    DriverFixture {
        spawned,
        exit_tx,
        stdout_tx,
        writer_rx,
        terminations,
    }
}

#[tokio::test]
async fn early_driver_sender_loss_returns_process_failure() -> Result<()> {
    let fixture = driver_fixture();
    drop(fixture.exit_tx);
    let error = tokio::time::timeout(
        Duration::from_secs(2),
        UnifiedExecProcess::from_spawned(
            fixture.spawned,
            SandboxType::None,
            Box::new(NoopSpawnLifecycle),
        ),
    )
    .await?
    .expect_err("no native exit result was delivered");
    assert!(matches!(error, UnifiedExecError::ProcessFailed { .. }));
    assert!(error.to_string().contains(EXIT_OBSERVATION_LOST));
    assert_eq!(fixture.terminations.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn late_driver_sender_loss_cannot_be_upgraded_by_write_or_termination() -> Result<()> {
    let mut fixture = driver_fixture();
    let process = UnifiedExecProcess::from_spawned(
        fixture.spawned,
        SandboxType::None,
        Box::new(NoopSpawnLifecycle),
    )
    .await?;
    let mut state_rx = process.state_rx.clone();
    let mut output = process.output_receiver();
    drop(fixture.exit_tx);
    tokio::time::timeout(Duration::from_secs(2), async {
        while state_rx.borrow().failure_message.is_none() {
            state_rx.changed().await?;
        }
        Ok::<(), tokio::sync::watch::error::RecvError>(())
    })
    .await??;
    assert!(!process.has_exited());
    assert_eq!(process.exit_code(), None);
    assert_eq!(
        process.failure_message(),
        Some(EXIT_OBSERVATION_LOST.to_string())
    );

    fixture.stdout_tx.send(b"observed tail".to_vec())?;
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(2), output.recv()).await??,
        b"observed tail".to_vec()
    );
    let write_error = process
        .write(b"must not be sent")
        .await
        .expect_err("unknown owner");
    assert!(matches!(
        write_error,
        UnifiedExecError::ProcessFailed { .. }
    ));
    assert!(matches!(
        fixture.writer_rx.try_recv(),
        Err(mpsc::error::TryRecvError::Empty)
    ));
    let terminate_error = process
        .terminate_confirmed()
        .await
        .expect_err("a termination request cannot supply a lost observation");
    assert!(matches!(
        terminate_error,
        UnifiedExecError::ProcessFailed { .. }
    ));
    process.fail_and_terminate("later failure".to_string());
    assert!(!process.has_exited());
    assert_eq!(process.exit_code(), None);
    assert_eq!(
        process.failure_message(),
        Some(EXIT_OBSERVATION_LOST.to_string())
    );
    drop(process);
    assert_eq!(fixture.terminations.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn observed_driver_exit_keeps_its_actual_code() -> Result<()> {
    let fixture = driver_fixture();
    fixture
        .exit_tx
        .send(23)
        .map_err(|_| anyhow::anyhow!("driver exit receiver closed"))?;
    let process = UnifiedExecProcess::from_spawned(
        fixture.spawned,
        SandboxType::None,
        Box::new(NoopSpawnLifecycle),
    )
    .await?;
    assert!(process.has_exited());
    assert_eq!(process.exit_code(), Some(23));
    assert_eq!(process.failure_message(), None);
    Ok(())
}
