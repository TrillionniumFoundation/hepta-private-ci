//! Retains one parsed event while the shared input pump services outbound work.

use async_channel::Sender;
use codex_api::RealtimeEvent;
use tracing::error;

pub(super) struct PendingRealtimeEvent {
    pub(super) event: RealtimeEvent,
    pub(super) should_stop: bool,
}

/// A cancelled send leaves the parsed event owned by the caller. Only a
/// completed send removes it, so reconnect and final drain do not re-parse it.
pub(super) async fn flush_pending_realtime_event(
    events_tx: &Sender<RealtimeEvent>,
    pending: &mut Option<PendingRealtimeEvent>,
) -> anyhow::Result<()> {
    let Some(event) = pending.as_ref() else {
        return Ok(());
    };
    let should_stop = event.should_stop;
    if events_tx.send(event.event.clone()).await.is_err() {
        // A closed receiver cannot accept this event on a later drain. Keep
        // the original terminal error and discard only the failed send.
        let _ = pending.take();
        anyhow::bail!("realtime output event channel closed");
    }
    let _ = pending.take();
    if should_stop {
        error!("realtime stream error event received");
        anyhow::bail!("realtime stream error event received");
    }
    Ok(())
}

#[cfg(test)]
#[path = "input_forwarding_tests.rs"]
mod tests;
