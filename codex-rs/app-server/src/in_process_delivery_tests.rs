use anyhow::Context;
use codex_app_server_protocol::ProcessExitedNotification;
use codex_app_server_protocol::ProcessIndeterminateNotification;
use codex_app_server_protocol::ProcessIndeterminateReason;
use codex_app_server_protocol::ProcessOutputDeltaNotification;
use codex_app_server_protocol::ProcessOutputStream;
use codex_app_server_protocol::ThreadQueueChangedNotification;
use pretty_assertions::assert_eq;

use super::*;

fn occupied_slot() -> InProcessServerEvent {
    InProcessServerEvent::ServerNotification(Box::new(ServerNotification::ThreadQueueChanged(
        ThreadQueueChangedNotification {
            thread_id: "occupied".to_string(),
        },
    )))
}

#[tokio::test]
async fn a_full_original_queue_backpressures_both_process_terminal_observations()
-> anyhow::Result<()> {
    let terminals = [
        ServerNotification::ProcessExited(ProcessExitedNotification {
            process_handle: "known".to_string(),
            exit_code: 23,
            stdout: "seen".to_string(),
            stdout_cap_reached: false,
            stderr: String::new(),
            stderr_cap_reached: false,
        }),
        ServerNotification::ProcessIndeterminate(ProcessIndeterminateNotification {
            process_handle: "unknown".to_string(),
            reason: ProcessIndeterminateReason::ExitObservationLost,
            stdout: "seen".to_string(),
            stdout_cap_reached: false,
            stderr: String::new(),
            stderr_cap_reached: false,
        }),
    ];
    for terminal in terminals {
        let expected = serde_json::to_value(&terminal)?;
        let (tx, mut rx) = mpsc::channel(/*buffer*/ 1);
        tx.send(occupied_slot()).await?;
        let mut delivery = Box::pin(deliver_notification(&tx, terminal));
        assert!(futures::poll!(&mut delivery).is_pending());
        assert_eq!((rx.len(), tx.capacity()), (1, 0));
        let _occupied = rx.recv().await.context("occupied slot disappeared")?;
        assert_eq!(delivery.await, NotificationDelivery::Sent);
        let InProcessServerEvent::ServerNotification(notification) = rx
            .recv()
            .await
            .context("terminal observation was dropped")?
        else {
            anyhow::bail!("terminal observation changed event kind");
        };
        assert_eq!(serde_json::to_value(notification)?, expected);
        assert!(rx.try_recv().is_err());
    }
    Ok(())
}

#[tokio::test]
async fn closed_consumers_and_full_nonterminal_queues_keep_the_original_results()
-> anyhow::Result<()> {
    let output = ServerNotification::ProcessOutputDelta(ProcessOutputDeltaNotification {
        process_handle: "stream".to_string(),
        stream: ProcessOutputStream::Stdout,
        delta_base64: "YQ==".to_string(),
        cap_reached: false,
    });
    let (tx, rx) = mpsc::channel(/*buffer*/ 1);
    tx.send(occupied_slot()).await?;
    assert_eq!(
        deliver_notification(&tx, output.clone()).await,
        NotificationDelivery::Dropped
    );
    drop(rx);
    assert_eq!(
        deliver_notification(&tx, output).await,
        NotificationDelivery::Closed
    );
    let terminal = ServerNotification::ProcessIndeterminate(ProcessIndeterminateNotification {
        process_handle: "unknown".to_string(),
        reason: ProcessIndeterminateReason::ExitObservationLost,
        stdout: String::new(),
        stdout_cap_reached: false,
        stderr: String::new(),
        stderr_cap_reached: false,
    });
    assert_eq!(
        deliver_notification(&tx, terminal).await,
        NotificationDelivery::Closed
    );
    Ok(())
}
