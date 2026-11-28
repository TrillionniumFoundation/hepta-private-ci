//! Scheduling only. A wakeup carries no delivery ID, receipt or permission.
//! The original pending training owner supplies cancellation and its deadline.

use super::*;

impl TextIngress {
    pub(crate) fn original_ack_committed(&self) {
        self.ack_changed.notify_waiters();
    }

    pub(crate) async fn wait_for_original_ack(
        &self,
        delivery_id: Digest32,
    ) -> Result<(), AgentdError> {
        loop {
            // Register before reading the durable state. An Ack committed
            // during that read cannot disappear between checking and waiting.
            let changed = self.ack_changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            let status = self
                .evidence
                .authbus_delivery_status(delivery_id)
                .await
                .map_err(|error| invalid(&error.to_string()))?;
            if status.delivery_id != delivery_id
                || status.subject_id != self.subject
                || status.scope_digest != self.scope
            {
                return Err(invalid("original Ack belongs to another delivery or owner"));
            }
            match (status.state, status.acknowledgement) {
                (AuthBusDeliveryState::Acked, Some(_)) => return Ok(()),
                (AuthBusDeliveryState::Queued | AuthBusDeliveryState::Leased, None) => {
                    changed.await;
                }
                _ => {
                    return Err(invalid(
                        "original delivery cannot become an acknowledged turn",
                    ));
                }
            }
        }
    }
}
