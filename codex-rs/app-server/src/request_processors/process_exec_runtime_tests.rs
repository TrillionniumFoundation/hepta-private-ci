use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use codex_analytics::AnalyticsEventsClient;
use codex_app_server_protocol::RequestId;
use codex_utils_pty::ProcessDriver;
use codex_utils_pty::SpawnedProcess;
use codex_utils_pty::spawn_from_driver;
use pretty_assertions::assert_eq;
use tokio::sync::broadcast;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use super::*;
use crate::outgoing_message::OutgoingEnvelope;
use crate::outgoing_message::OutgoingMessage;
use crate::request_processors::process_exec_processor::registry::ConnectionProcessHandle;
use crate::request_processors::process_exec_processor::registry::ProcessRegistry;

fn driver_process() -> (SpawnedProcess, oneshot::Sender<i32>) {
    let (writer_tx, _writer_rx) = mpsc::channel(1);
    let (output_tx, output_rx) = broadcast::channel(1);
    let (exit_tx, exit_rx) = oneshot::channel();
    let spawned = spawn_from_driver(ProcessDriver {
        writer_tx,
        stdout_rx: output_rx,
        stderr_rx: None,
        exit_rx,
        terminator: None,
        writer_handle: None,
        resizer: None,
        #[cfg(windows)]
        tty: false,
    });
    let _ = output_tx.send(b"observed output".to_vec());
    drop(output_tx);
    (spawned, exit_tx)
}

#[tokio::test]
async fn lost_exit_channel_emits_unknown_and_retains_the_original_owner() -> anyhow::Result<()> {
    tokio::time::timeout(Duration::from_secs(5), async {
        let registry = Arc::new(ProcessRegistry::default());
        let (control_tx, control_rx) = mpsc::channel(1);
        let guard = registry
            .admit(
                ConnectionProcessHandle {
                    connection_id: ConnectionId(41),
                    process_handle: "lost".to_string(),
                },
                control_tx,
            )
            .map_err(|error| anyhow::anyhow!(error.message))?;
        let registration = Arc::clone(guard.registration());
        let (spawned, _driver_exit_tx) = driver_process();
        let session = Arc::clone(registration.owner.get_or_init(|| Arc::new(spawned.session)));
        let retained_owner = Arc::downgrade(&session);
        let (lost_tx, lost_rx) = oneshot::channel();
        drop(lost_tx);
        let (outgoing_tx, mut outgoing_rx) = mpsc::channel(1);
        let task = tokio::spawn(run_process(RunProcessParams {
            outgoing: Arc::new(OutgoingMessageSender::new(
                outgoing_tx,
                AnalyticsEventsClient::disabled(),
            )),
            request_id: ConnectionRequestId {
                connection_id: ConnectionId(41),
                request_id: RequestId::Integer(1),
            },
            process_handle: "lost".to_string(),
            session,
            stdout_rx: spawned.stdout_rx,
            stderr_rx: spawned.stderr_rx,
            exit_rx: lost_rx,
            guard,
            control_rx,
            stream_stdin: false,
            stream_stdout_stderr: false,
            expiration: ExecExpiration::Cancellation(CancellationToken::new()),
            output_bytes_cap: Some(64),
        }));
        let OutgoingEnvelope::ToConnection {
            message,
            write_complete_tx,
            ..
        } = outgoing_rx
            .recv()
            .await
            .context("missing process observation")?
        else {
            anyhow::bail!("unexpected outgoing routing");
        };
        let OutgoingMessage::AppServerNotification(envelope) = message else {
            anyhow::bail!("lost observation was not a typed notification");
        };
        assert_eq!(
            serde_json::to_value(envelope.notification)?,
            serde_json::json!({
                "method": "process/indeterminate",
                "params": {
                    "processHandle": "lost",
                    "reason": "exitObservationLost",
                    "stdout": "observed output",
                    "stdoutCapReached": false,
                    "stderr": "",
                    "stderrCapReached": false
                }
            }),
        );
        if let Some(tx) = write_complete_tx {
            let _ = tx.send(());
        }
        task.await?;
        assert!(outgoing_rx.try_recv().is_err());
        assert!(registry.connection_closed(ConnectionId(41)).is_empty());
        let owner = retained_owner
            .upgrade()
            .context("unknown owner was dropped")?;
        assert_eq!((owner.has_exited(), owner.exit_code()), (false, None));
        let (new_tx, _new_rx) = mpsc::channel(1);
        assert!(
            registry
                .admit(
                    ConnectionProcessHandle {
                        connection_id: ConnectionId(42),
                        process_handle: "next".to_string()
                    },
                    new_tx,
                )
                .is_err()
        );
        Ok::<(), anyhow::Error>(())
    })
    .await??;
    Ok(())
}

#[tokio::test]
async fn observed_exit_preserves_its_code_and_releases_only_that_registration() -> anyhow::Result<()>
{
    tokio::time::timeout(Duration::from_secs(5), async {
        let registry = Arc::new(ProcessRegistry::default());
        let key = ConnectionProcessHandle {
            connection_id: ConnectionId(51),
            process_handle: "known".to_string(),
        };
        let (control_tx, control_rx) = mpsc::channel(1);
        let guard = registry
            .admit(key.clone(), control_tx)
            .map_err(|error| anyhow::anyhow!(error.message))?;
        let registration = Arc::clone(guard.registration());
        let (spawned, driver_exit_tx) = driver_process();
        let session = Arc::clone(registration.owner.get_or_init(|| Arc::new(spawned.session)));
        driver_exit_tx
            .send(23)
            .map_err(|_| anyhow::anyhow!("driver exit receiver lost"))?;
        let (outgoing_tx, mut outgoing_rx) = mpsc::channel(1);
        let task = tokio::spawn(run_process(RunProcessParams {
            outgoing: Arc::new(OutgoingMessageSender::new(
                outgoing_tx,
                AnalyticsEventsClient::disabled(),
            )),
            request_id: ConnectionRequestId {
                connection_id: ConnectionId(51),
                request_id: RequestId::Integer(2),
            },
            process_handle: "known".to_string(),
            session,
            stdout_rx: spawned.stdout_rx,
            stderr_rx: spawned.stderr_rx,
            exit_rx: spawned.exit_rx,
            guard,
            control_rx,
            stream_stdin: false,
            stream_stdout_stderr: false,
            expiration: ExecExpiration::Cancellation(CancellationToken::new()),
            output_bytes_cap: Some(64),
        }));
        let OutgoingEnvelope::ToConnection {
            message,
            write_complete_tx,
            ..
        } = outgoing_rx.recv().await.context("missing process exit")?
        else {
            anyhow::bail!("unexpected outgoing routing");
        };
        let OutgoingMessage::AppServerNotification(envelope) = message else {
            anyhow::bail!("observed exit was not a typed notification");
        };
        assert_eq!(
            serde_json::to_value(envelope.notification)?,
            serde_json::json!({
                "method": "process/exited",
                "params": { "processHandle": "known", "exitCode": 23, "stdout": "observed output",
                    "stdoutCapReached": false, "stderr": "", "stderrCapReached": false }
            })
        );
        if let Some(tx) = write_complete_tx {
            let _ = tx.send(());
        }
        task.await?;
        let (new_tx, _new_rx) = mpsc::channel(1);
        registry
            .admit(key, new_tx)
            .map_err(|error| anyhow::anyhow!(error.message))?;
        Ok::<(), anyhow::Error>(())
    })
    .await??;
    Ok(())
}

#[tokio::test]
async fn a_control_loop_panic_uses_the_original_drain_and_typed_unknown_path() -> anyhow::Result<()>
{
    tokio::time::timeout(Duration::from_secs(5), async {
        let registry = Arc::new(ProcessRegistry::default());
        let (control_tx, control_rx) = mpsc::channel(/*buffer*/ 1);
        let guard = registry.admit(
            ConnectionProcessHandle { connection_id: ConnectionId(91), process_handle: "panicked".to_string() },
            control_tx,
        ).map_err(|error| anyhow::anyhow!(error.message))?;
        let (writer_tx, _writer_rx) = mpsc::channel(/*buffer*/ 1);
        let (output_tx, output_rx) = broadcast::channel(/*capacity*/ 1);
        let (_driver_exit_tx, exit_rx) = oneshot::channel();
        let spawned = spawn_from_driver(ProcessDriver {
            writer_tx, stdout_rx: output_rx, stderr_rx: None, exit_rx,
            terminator: Some(Box::new(|| panic!("injected original control callback failure"))),
            writer_handle: None, resizer: None,
            #[cfg(windows)]
            tty: false,
        });
        drop(output_tx);
        let session = Arc::clone(guard.registration().owner.get_or_init(|| Arc::new(spawned.session)));
        let retained = Arc::downgrade(&session);
        let (outgoing_tx, mut outgoing_rx) = mpsc::channel(/*buffer*/ 1);
        let task = tokio::spawn(run_process(RunProcessParams {
            outgoing: Arc::new(OutgoingMessageSender::new(outgoing_tx, AnalyticsEventsClient::disabled())),
            request_id: ConnectionRequestId { connection_id: ConnectionId(91), request_id: RequestId::Integer(1) },
            process_handle: "panicked".to_string(), session, stdout_rx: spawned.stdout_rx, stderr_rx: spawned.stderr_rx,
            exit_rx: spawned.exit_rx, guard, control_rx, stream_stdin: false, stream_stdout_stderr: false,
            expiration: 0u64.into(), output_bytes_cap: Some(64),
        }));
        let OutgoingEnvelope::ToConnection { message, write_complete_tx, .. } =
            outgoing_rx.recv().await.context("panic lost the terminal observation")?
        else { anyhow::bail!("unexpected routing"); };
        let OutgoingMessage::AppServerNotification(envelope) = message else {
            anyhow::bail!("panic was reported as a successful response");
        };
        assert_eq!(serde_json::to_value(envelope.notification)?, serde_json::json!({
            "method": "process/indeterminate",
            "params": { "processHandle": "panicked", "reason": "exitObservationLost",
                "stdout": "", "stdoutCapReached": false, "stderr": "", "stderrCapReached": false }
        }));
        if let Some(tx) = write_complete_tx { let _ = tx.send(()); }
        task.await?;
        let owner = retained.upgrade().context("panic discarded the original owner")?;
        assert_eq!((owner.has_exited(), owner.exit_code()), (false, None));
        let (tx, _rx) = mpsc::channel(/*buffer*/ 1);
        assert!(registry.admit(ConnectionProcessHandle {
            connection_id: ConnectionId(92), process_handle: "next".to_string(),
        }, tx).is_err());
        Ok::<(), anyhow::Error>(())
    }).await??;
    Ok(())
}
