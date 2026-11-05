use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use codex_analytics::AnalyticsEventsClient;
use codex_app_server_protocol::RequestId;
use codex_utils_pty::ProcessDriver;
use codex_utils_pty::spawn_from_driver;
use pretty_assertions::assert_eq;
use tokio::sync::broadcast;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

use super::*;
use crate::error_code::INTERNAL_ERROR_CODE;
use crate::outgoing_message::OutgoingEnvelope;
use crate::outgoing_message::OutgoingMessage;

#[tokio::test]
async fn timeout_followed_by_lost_exit_observation_is_an_error_not_exit_124() -> anyhow::Result<()>
{
    tokio::time::timeout(Duration::from_secs(5), async {
        let (writer_tx, _writer_rx) = mpsc::channel(1);
        let (output_tx, output_rx) = broadcast::channel(1);
        let (_driver_exit_tx, driver_exit_rx) = oneshot::channel();
        let (terminate_tx, terminate_rx) = oneshot::channel();
        let mut terminate_tx = Some(terminate_tx);
        let mut spawned = spawn_from_driver(ProcessDriver {
            writer_tx,
            stdout_rx: output_rx,
            stderr_rx: None,
            exit_rx: driver_exit_rx,
            terminator: Some(Box::new(move || {
                if let Some(tx) = terminate_tx.take() {
                    let _ = tx.send(());
                }
            })),
            writer_handle: None,
            resizer: None,
            #[cfg(windows)]
            tty: false,
        });
        drop(output_tx);
        let (lost_tx, lost_rx) = oneshot::channel();
        spawned.exit_rx = lost_rx;
        let (outgoing_tx, mut outgoing_rx) = mpsc::channel(1);
        let (_control_tx, control_rx) = mpsc::channel(1);
        let task = tokio::spawn(run_command(RunCommandParams {
            outgoing: Arc::new(OutgoingMessageSender::new(
                outgoing_tx,
                AnalyticsEventsClient::disabled(),
            )),
            request_id: ConnectionRequestId {
                connection_id: ConnectionId(61),
                request_id: RequestId::Integer(3),
            },
            process_id: None,
            spawned,
            control_rx,
            stream_stdin: false,
            stream_stdout_stderr: false,
            expiration: 0u64.into(),
            output_bytes_cap: Some(64),
        }));
        // The original timeout/cleanup attempt occurs before the observation is lost.
        terminate_rx.await?;
        drop(lost_tx);
        let OutgoingEnvelope::ToConnection { message, .. } =
            outgoing_rx.recv().await.context("missing command result")?
        else {
            anyhow::bail!("unexpected outgoing routing");
        };
        let OutgoingMessage::Error(error) = message else {
            anyhow::bail!("unknown native exit was reported as a successful response");
        };
        assert_eq!(
            (error.id, error.error.code, error.error.message),
            (
                RequestId::Integer(3),
                INTERNAL_ERROR_CODE,
                "command/exec process exit observation was lost".to_string()
            ),
        );
        task.await?;
        assert!(outgoing_rx.try_recv().is_err());
        Ok::<(), anyhow::Error>(())
    })
    .await??;
    Ok(())
}
