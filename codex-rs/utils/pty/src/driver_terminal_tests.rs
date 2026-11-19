use crate::ProcessDriver;
use crate::spawn_from_driver;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::sync::broadcast;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

#[tokio::test]
async fn driver_sender_drop_keeps_unknown_exit_and_drains_output() -> Result<()> {
    let (writer_tx, _writer_rx) = mpsc::channel(1);
    let (stdout_tx, stdout_rx) = broadcast::channel(8);
    let (exit_tx, exit_rx) = oneshot::channel();
    let terminations = Arc::new(AtomicUsize::new(0));
    let observe_terminations = Arc::clone(&terminations);
    let mut spawned = spawn_from_driver(ProcessDriver {
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
    drop(exit_tx);
    assert!(
        tokio::time::timeout(Duration::from_secs(2), &mut spawned.exit_rx)
            .await?
            .is_err()
    );
    assert!(!spawned.session.has_exited());
    assert_eq!(spawned.session.exit_code(), None);

    // Late output still drains after the driver's observation channel failed.
    stdout_tx.send(b"retained tail".to_vec())?;
    drop(stdout_tx);
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(2), spawned.stdout_rx.recv()).await?,
        Some(b"retained tail".to_vec())
    );
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(2), spawned.stdout_rx.recv()).await?,
        None
    );
    spawned.session.request_terminate();
    spawned.session.request_terminate();
    assert_eq!(terminations.load(Ordering::SeqCst), 1);
    assert!(!spawned.session.has_exited());
    assert_eq!(spawned.session.exit_code(), None);
    Ok(())
}
