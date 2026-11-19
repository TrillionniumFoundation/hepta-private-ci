//! Task ownership and bounded shutdown fixtures, independent of any authority.
use super::super::*;

struct Stopped(Option<oneshot::Sender<()>>);
impl Drop for Stopped {
    fn drop(&mut self) {
        if let Some(sender) = self.0.take() {
            let _ = sender.send(());
        }
    }
}

async fn blocked_client() -> (RemoteAppServerClient, oneshot::Receiver<()>) {
    let (command_tx, command_rx) = mpsc::channel(1);
    let (response_tx, _) = oneshot::channel();
    assert!(
        command_tx
            .try_send(RemoteClientCommand::Shutdown { response_tx })
            .is_ok()
    );
    let (_event_tx, event_rx) = mpsc::unbounded_channel();
    let (stopped, did_stop) = oneshot::channel();
    let (started, did_start) = oneshot::channel();
    let worker_handle = tokio::spawn(async move {
        let _commands = command_rx;
        let _stopped = Stopped(Some(stopped));
        let _ = started.send(());
        std::future::pending::<()>().await;
    });
    did_start.await.unwrap();
    (
        RemoteAppServerClient {
            command_tx,
            event_rx: RemoteEventReceiver::Unbounded(event_rx),
            pending_events: VecDeque::new(),
            server_version: None,
            codex_home: None,
            connection_id: 1,
            worker_handle,
        },
        did_stop,
    )
}

#[tokio::test]
async fn cancelling_shutdown_while_command_queue_is_full_stops_original_worker() {
    let (client, stopped) = blocked_client().await;
    let handle = client.request_handle();
    assert!(
        timeout(Duration::from_millis(20), client.shutdown())
            .await
            .is_err()
    );
    timeout(Duration::from_secs(1), stopped)
        .await
        .unwrap()
        .unwrap();
    assert!(handle.command_tx.is_closed());
}

#[tokio::test]
async fn shutdown_deadline_includes_waiting_for_a_full_command_queue() {
    let (client, stopped) = blocked_client().await;
    timeout(SHUTDOWN_TIMEOUT + Duration::from_secs(1), client.shutdown())
        .await
        .unwrap()
        .unwrap();
    timeout(Duration::from_secs(1), stopped)
        .await
        .unwrap()
        .unwrap();
}
