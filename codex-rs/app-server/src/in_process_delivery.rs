use codex_app_server_protocol::ServerNotification;
use tokio::sync::mpsc;

use super::InProcessServerEvent;
use super::server_notification_requires_delivery;

#[derive(Debug, PartialEq, Eq)]
pub(super) enum NotificationDelivery {
    Sent,
    Dropped,
    Closed,
}

pub(super) async fn deliver_notification(
    event_tx: &mpsc::Sender<InProcessServerEvent>,
    notification: ServerNotification,
) -> NotificationDelivery {
    let requires_delivery = server_notification_requires_delivery(&notification);
    let event = InProcessServerEvent::ServerNotification(Box::new(notification));
    if requires_delivery {
        return match event_tx.send(event).await {
            Ok(()) => NotificationDelivery::Sent,
            Err(_) => NotificationDelivery::Closed,
        };
    }
    match event_tx.try_send(event) {
        Ok(()) => NotificationDelivery::Sent,
        Err(mpsc::error::TrySendError::Full(_)) => {
            tracing::warn!("dropping in-process server notification (queue full)");
            NotificationDelivery::Dropped
        }
        Err(mpsc::error::TrySendError::Closed(_)) => NotificationDelivery::Closed,
    }
}

#[cfg(test)]
#[path = "in_process_delivery_tests.rs"]
mod tests;
