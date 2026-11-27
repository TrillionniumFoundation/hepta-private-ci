use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use anyhow::Context;
use codex_utils_pty::ProcessDriver;
use codex_utils_pty::spawn_from_driver;
use pretty_assertions::assert_eq;
use tokio::sync::broadcast;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

use super::*;

#[tokio::test]
async fn first_unknown_fences_new_connections_and_retains_the_original_owner() -> anyhow::Result<()>
{
    let registry = Arc::new(ProcessRegistry::default());
    let (control_tx, _control_rx) = mpsc::channel(1);
    let mut guard = registry
        .admit(
            ConnectionProcessHandle {
                connection_id: ConnectionId(1),
                process_handle: "original".to_string(),
            },
            control_tx,
        )
        .map_err(|error| anyhow::anyhow!(error.message))?;
    let registration = Arc::clone(guard.registration());
    let (writer_tx, _writer_rx) = mpsc::channel(1);
    let (output_tx, output_rx) = broadcast::channel(1);
    let (_exit_tx, exit_rx) = oneshot::channel();
    let terminations = Arc::new(AtomicUsize::new(0));
    let observed_terminations = Arc::clone(&terminations);
    let spawned = spawn_from_driver(ProcessDriver {
        writer_tx,
        stdout_rx: output_rx,
        stderr_rx: None,
        exit_rx,
        terminator: Some(Box::new(move || {
            observed_terminations.fetch_add(1, Ordering::SeqCst);
        })),
        writer_handle: None,
        resizer: None,
        #[cfg(windows)]
        tty: false,
    });
    drop(output_tx);
    let owner = registration.owner.get_or_init(|| Arc::new(spawned.session));
    let original_owner = Arc::downgrade(owner);
    let original_registration = Arc::downgrade(&registration);

    guard.observation_lost();
    assert!(registry.connection_closed(ConnectionId(1)).is_empty());
    drop(guard);
    drop(registration);
    assert!(original_registration.upgrade().is_some());
    let owner = original_owner
        .upgrade()
        .context("registry lost the original owner")?;
    assert_eq!((owner.has_exited(), owner.exit_code()), (false, None));
    assert_eq!(terminations.load(Ordering::SeqCst), 1);

    let (control_tx, _control_rx) = mpsc::channel(1);
    let error = match registry.admit(
        ConnectionProcessHandle {
            connection_id: ConnectionId(2),
            process_handle: "new-connection".to_string(),
        },
        control_tx,
    ) {
        Ok(_) => anyhow::bail!("a new connection bypassed the first-unknown fence"),
        Err(error) => error,
    };
    assert!(error.message.contains("process/spawn is fenced"));
    assert_eq!(registry.lock_state().entries.len(), 1);
    Ok(())
}

#[tokio::test]
async fn late_control_loss_cannot_poison_a_new_registration_with_the_same_handle()
-> anyhow::Result<()> {
    let registry = Arc::new(ProcessRegistry::default());
    let key = ConnectionProcessHandle {
        connection_id: ConnectionId(3),
        process_handle: "reused-after-exit".to_string(),
    };
    let (old_tx, _old_rx) = mpsc::channel(1);
    let mut old_guard = registry
        .admit(key.clone(), old_tx)
        .map_err(|error| anyhow::anyhow!(error.message))?;
    let old = Arc::clone(old_guard.registration());
    old_guard.observed_exit();
    drop(old_guard);
    let (new_tx, _new_rx) = mpsc::channel(1);
    let current_guard = registry
        .admit(key.clone(), new_tx)
        .map_err(|error| anyhow::anyhow!(error.message))?;

    let current = current_guard.registration();
    registry.observation_lost(&old);
    registry.observed_exit(&old);

    let observed = registry
        .active(&key)
        .map_err(|error| anyhow::anyhow!(error.message))?;
    assert!(Arc::ptr_eq(current, &observed));
    assert!(!registry.lock_state().spawn_fenced);
    Ok(())
}
