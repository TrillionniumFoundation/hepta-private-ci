use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use anyhow::Context;
use codex_analytics::AnalyticsEventsClient;
use codex_app_server_protocol::ProcessSpawnResponse;
use codex_app_server_protocol::RequestId;
use codex_utils_pty::ProcessDriver;
use codex_utils_pty::spawn_from_driver;
use pretty_assertions::assert_eq;
use tokio::sync::broadcast;
use tokio::sync::oneshot;

use super::*;
use crate::outgoing_message::ConnectionRequestId;
use crate::outgoing_message::OutgoingMessageSender;

struct AdmittedProcess {
    registry: Arc<ProcessRegistry>,
    guard: ProcessRegistrationGuard,
    terminations: Arc<AtomicUsize>,
    _driver_exit: oneshot::Sender<i32>,
}

fn admitted_process() -> anyhow::Result<AdmittedProcess> {
    let registry = Arc::new(ProcessRegistry::default());
    let (control_tx, _control_rx) = mpsc::channel(1);
    let guard = registry
        .admit(
            ConnectionProcessHandle {
                connection_id: ConnectionId(71),
                process_handle: "original".to_string(),
            },
            control_tx,
        )
        .map_err(|error| anyhow::anyhow!(error.message))?;
    let (writer_tx, _writer_rx) = mpsc::channel(1);
    let (output_tx, output_rx) = broadcast::channel(1);
    let (driver_exit, exit_rx) = oneshot::channel();
    let terminations = Arc::new(AtomicUsize::new(0));
    let cleanup_requests = Arc::clone(&terminations);
    let spawned = spawn_from_driver(ProcessDriver {
        writer_tx,
        stdout_rx: output_rx,
        stderr_rx: None,
        exit_rx,
        terminator: Some(Box::new(move || {
            cleanup_requests.fetch_add(1, Ordering::SeqCst);
        })),
        writer_handle: None,
        resizer: None,
        #[cfg(windows)]
        tty: false,
    });
    drop(output_tx);
    guard
        .registration()
        .owner
        .get_or_init(|| Arc::new(spawned.session));
    Ok(AdmittedProcess {
        registry,
        guard,
        terminations,
        _driver_exit: driver_exit,
    })
}

fn assert_retained_and_fenced(registry: &Arc<ProcessRegistry>) -> anyhow::Result<()> {
    let key = ConnectionProcessHandle {
        connection_id: ConnectionId(71),
        process_handle: "original".to_string(),
    };
    let state = registry.lock_state();
    let registration = &state
        .entries
        .get(&key)
        .context("registration was discarded")?
        .registration;
    let owner = registration
        .owner
        .get()
        .context("original owner was discarded")?;
    assert_eq!((owner.has_exited(), owner.exit_code()), (false, None));
    assert!(state.spawn_fenced);
    drop(state);
    assert!(registry.active(&key).is_err());
    let (tx, _rx) = mpsc::channel(1);
    assert!(
        registry
            .admit(
                ConnectionProcessHandle {
                    connection_id: ConnectionId(72),
                    process_handle: "later-connection".to_string(),
                },
                tx
            )
            .is_err()
    );
    Ok(())
}

#[tokio::test]
async fn cancellation_during_the_original_spawn_response_wait_retains_and_fences()
-> anyhow::Result<()> {
    let AdmittedProcess {
        registry,
        guard,
        terminations,
        _driver_exit,
    } = admitted_process()?;
    let (tx, _rx) = mpsc::channel(1);
    let outgoing = Arc::new(OutgoingMessageSender::new(
        tx,
        AnalyticsEventsClient::disabled(),
    ));
    let request_id = ConnectionRequestId {
        connection_id: ConnectionId(71),
        request_id: RequestId::Integer(1),
    };
    outgoing
        .send_error(request_id.clone(), internal_error("occupied outbound slot"))
        .await;
    let mut waiting = Box::pin(async move {
        let _guard = guard;
        outgoing
            .send_response(request_id, ProcessSpawnResponse {})
            .await;
    });
    assert!(futures::poll!(&mut waiting).is_pending());
    drop(waiting);
    assert_retained_and_fenced(&registry)?;
    assert_eq!(terminations.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn aborting_the_original_worker_retains_and_fences_without_a_retry_task() -> anyhow::Result<()>
{
    let AdmittedProcess {
        registry,
        guard,
        terminations,
        _driver_exit,
    } = admitted_process()?;
    let (ready_tx, ready_rx) = oneshot::channel();
    let worker = tokio::spawn(async move {
        let _guard = guard;
        let _ = ready_tx.send(());
        std::future::pending::<()>().await;
    });
    ready_rx.await?;
    worker.abort();
    let error = match worker.await {
        Err(error) => error,
        Ok(()) => anyhow::bail!("aborted worker reported completion"),
    };
    assert!(error.is_cancelled());
    assert_retained_and_fenced(&registry)?;
    assert_eq!(terminations.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn a_poisoned_registry_refuses_admission_without_discarding_existing_owners()
-> anyhow::Result<()> {
    let fixture = admitted_process()?;
    let registry = Arc::clone(&fixture.registry);
    let poison = std::thread::spawn(move || {
        let Ok(_held) = registry.state.lock() else {
            panic!("fixture started poisoned");
        };
        panic!("injected registry critical-section panic");
    });
    assert!(poison.join().is_err());
    assert_retained_and_fenced(&fixture.registry)?;
    Ok(())
}
