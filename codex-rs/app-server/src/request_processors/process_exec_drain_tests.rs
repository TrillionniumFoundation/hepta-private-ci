use anyhow::Context;
use codex_analytics::AnalyticsEventsClient;
use codex_app_server_protocol::RequestId;
use pretty_assertions::assert_eq;

use super::*;
use crate::outgoing_message::OutgoingEnvelope;
use crate::outgoing_message::OutgoingMessage;

#[derive(Clone, Copy)]
enum OutboundBlock {
    Capacity,
    WriteAck,
}

#[tokio::test]
async fn the_original_drain_signal_cancels_a_blocked_delta_before_terminal_delivery()
-> anyhow::Result<()> {
    tokio::time::timeout(Duration::from_secs(5), async {
        for blocked in [OutboundBlock::Capacity, OutboundBlock::WriteAck] {
            let (outgoing_tx, mut outgoing_rx) = mpsc::channel(/*buffer*/ 1);
            let outgoing = Arc::new(OutgoingMessageSender::new(
                outgoing_tx, AnalyticsEventsClient::disabled(),
            ));
            let request_id = ConnectionRequestId { connection_id: ConnectionId(81), request_id: RequestId::Integer(1) };
            if matches!(blocked, OutboundBlock::Capacity) {
                outgoing.send_error(request_id.clone(), crate::error_code::internal_error("occupied")).await;
            }
            let (output_tx, output_rx) = mpsc::channel(/*buffer*/ 1);
            let (drain_tx, drain_rx) = watch::channel(false);
            let collector = collect_spawn_process_output(SpawnProcessOutputParams {
                connection_id: request_id.connection_id,
                process_handle: "retained".to_string(),
                output_rx, stdio_timeout_rx: drain_rx, outgoing: Arc::clone(&outgoing),
                stream: ProcessOutputStream::Stdout, stream_output: true, output_bytes_cap: Some(4),
            });
            output_tx.send(b"payload".to_vec()).await?;
            // The next permit proves the collector consumed the chunk before its send blocks.
            drop(output_tx.reserve().await?);
            let held_ack = match blocked {
                OutboundBlock::Capacity => None,
                OutboundBlock::WriteAck => {
                    let OutgoingEnvelope::ToConnection { message, write_complete_tx, .. } =
                        outgoing_rx.recv().await.context("missing output delta")?
                    else { anyhow::bail!("unexpected output routing"); };
                    let OutgoingMessage::AppServerNotification(envelope) = message else {
                        anyhow::bail!("output changed message kind");
                    };
                    assert_eq!(serde_json::to_value(envelope.notification)?, serde_json::json!({
                        "method": "process/outputDelta",
                        "params": { "processHandle": "retained", "stream": "stdout", "deltaBase64": "cGF5bA==", "capReached": true }
                    }));
                    Some(write_complete_tx.context("output send did not wait for a write acknowledgement")?)
                }
            };
            // This is the same watch signal raised by the original IO_DRAIN_TIMEOUT_MS timer.
            drain_tx.send(true)?;
            let capture = collector.await?;
            assert_eq!((capture.text.as_str(), capture.cap_reached), ("", true));
            let terminal = ServerNotification::ProcessIndeterminate(ProcessIndeterminateNotification {
                process_handle: "retained".to_string(), reason: ProcessIndeterminateReason::ExitObservationLost,
                stdout: capture.text, stdout_cap_reached: capture.cap_reached,
                stderr: String::new(), stderr_cap_reached: false,
            });
            let mut delivery = Box::pin(outgoing.send_server_notification_to_connection_and_wait(
                request_id.connection_id, terminal,
            ));
            assert!(futures::poll!(&mut delivery).is_pending());
            if matches!(blocked, OutboundBlock::Capacity) {
                let _occupied = outgoing_rx.recv().await.context("occupied slot disappeared")?;
                assert!(futures::poll!(&mut delivery).is_pending());
            }
            let OutgoingEnvelope::ToConnection { message, write_complete_tx, .. } =
                outgoing_rx.recv().await.context("terminal was not delivered after drain")?
            else { anyhow::bail!("unexpected terminal routing"); };
            let OutgoingMessage::AppServerNotification(envelope) = message else {
                anyhow::bail!("terminal changed message kind");
            };
            assert!(matches!(envelope.notification, ServerNotification::ProcessIndeterminate(_)));
            write_complete_tx.context("terminal did not retain write acknowledgement")?
                .send(()).map_err(|_| anyhow::anyhow!("terminal receiver abandoned its write acknowledgement"))?;
            assert!(delivery.await);
            drop(held_ack);
            drop(output_tx);
        }
        Ok::<(), anyhow::Error>(())
    }).await??;
    Ok(())
}
