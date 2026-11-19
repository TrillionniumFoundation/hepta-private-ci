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
async fn command_drain_releases_blocked_stream_delivery_before_the_original_error_response()
-> anyhow::Result<()> {
    tokio::time::timeout(Duration::from_secs(5), async {
        for blocked in [OutboundBlock::Capacity, OutboundBlock::WriteAck] {
            let (outgoing_tx, mut outgoing_rx) = mpsc::channel(/*buffer*/ 1);
            let outgoing = Arc::new(OutgoingMessageSender::new(
                outgoing_tx, AnalyticsEventsClient::disabled(),
            ));
            let request_id = ConnectionRequestId { connection_id: ConnectionId(82), request_id: RequestId::Integer(2) };
            if matches!(blocked, OutboundBlock::Capacity) {
                outgoing.send_error(request_id.clone(), internal_error("occupied")).await;
            }
            let (output_tx, output_rx) = mpsc::channel(/*buffer*/ 1);
            let (drain_tx, drain_rx) = watch::channel(false);
            let collector = spawn_process_output(SpawnProcessOutputParams {
                connection_id: request_id.connection_id, process_id: Some("command".to_string()),
                output_rx, stdio_timeout_rx: drain_rx, outgoing: Arc::clone(&outgoing),
                stream: CommandExecOutputStream::Stdout, stream_output: true, output_bytes_cap: Some(4),
            });
            output_tx.send(b"payload".to_vec()).await?;
            drop(output_tx.reserve().await?);
            let held_ack = match blocked {
                OutboundBlock::Capacity => None,
                OutboundBlock::WriteAck => {
                    let OutgoingEnvelope::ToConnection { message, write_complete_tx, .. } =
                        outgoing_rx.recv().await.context("missing command output")?
                    else { anyhow::bail!("unexpected output routing"); };
                    let OutgoingMessage::AppServerNotification(envelope) = message else {
                        anyhow::bail!("output changed message kind");
                    };
                    assert_eq!(serde_json::to_value(envelope.notification)?, serde_json::json!({
                        "method": "command/exec/outputDelta",
                        "params": { "processId": "command", "stream": "stdout", "deltaBase64": "cGF5bA==", "capReached": true }
                    }));
                    Some(write_complete_tx.context("command output did not await its write acknowledgement")?)
                }
            };
            drain_tx.send(true)?;
            assert_eq!(collector.await?, "");
            let mut delivery = Box::pin(outgoing.send_error(
                request_id, internal_error("command/exec process exit observation was lost"),
            ));
            if matches!(blocked, OutboundBlock::Capacity) {
                assert!(futures::poll!(&mut delivery).is_pending());
                let _occupied = outgoing_rx.recv().await.context("occupied slot disappeared")?;
            }
            delivery.await;
            let OutgoingEnvelope::ToConnection { message, .. } =
                outgoing_rx.recv().await.context("original error response was lost")?
            else { anyhow::bail!("unexpected error routing"); };
            let OutgoingMessage::Error(error) = message else {
                anyhow::bail!("unknown native exit became a successful command response");
            };
            assert_eq!(error.error.message, "command/exec process exit observation was lost");
            drop(held_ack);
            drop(output_tx);
        }
        Ok::<(), anyhow::Error>(())
    }).await??;
    Ok(())
}
