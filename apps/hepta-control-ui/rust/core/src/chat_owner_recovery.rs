//! Original-owner reference recovery; this module issues no initial sends.
use super::*;

impl ChatOwnerAdapter {
    /// Called only after the authenticated host reads this exact retained
    /// signature from its original issuer. Recovered text is never a draft or
    /// an InitialSubmit ticket; expiry does not prevent a read-only lookup.
    pub fn restore_reference(
        &mut self,
        envelope: SignedTextRef,
        delivery_id: [u8; 32],
        now_ms: u64,
    ) -> Result<DeliveryView, ChatOwnerError> {
        self.advance_clock(now_ms)?;
        let scope = self.require_capability(ChatCapability::ReadDeliveryStatus, now_ms)?;
        if !scope.same_destination(&envelope.scope)
            || envelope.scope.agent_generation > scope.agent_generation
            || delivery_id == [0; 32]
        {
            return Err(ChatOwnerError::BindingMismatch);
        }
        let key = envelope.metadata.message_id.clone();
        if let Some(pending) = self.pending.get_mut(&key) {
            if !pending.envelope.scope.same_destination(&envelope.scope)
                || pending.envelope.scope.agent_generation != envelope.scope.agent_generation
                || pending.envelope.metadata != envelope.metadata
                || pending.envelope.text != envelope.text
                || pending
                    .view
                    .delivery_id
                    .is_some_and(|old| old != delivery_id)
            {
                return Err(ChatOwnerError::BindingMismatch);
            }
            pending.view.delivery_id = Some(delivery_id);
            return Ok(pending.view.clone());
        }
        if self.pending.len() >= MAX_PENDING_DELIVERIES {
            return Err(ChatOwnerError::Capacity);
        }
        let view = DeliveryView {
            message_id: key.clone(),
            delivery_id: Some(delivery_id),
            state: DeliveryState::Unknown,
            delivery_attempts: 0,
            queue_receipt_digest: None,
            fresh: false,
        };
        self.pending.insert(
            key,
            PendingDelivery {
                envelope,
                view: view.clone(),
                in_flight: None,
            },
        );
        Ok(view)
    }

    /// Consume the original Root's independently verified retirement receipt.
    /// The host must first receive that exact response; a local timeout, expiry
    /// or AuthBus quarantine is insufficient. This frees transient correlation
    /// without manufacturing an AuthBus acknowledgement or a completed turn.
    pub fn retire_original_reference(
        &mut self,
        ticket: &DispatchTicket,
        now_ms: u64,
    ) -> Result<DeliveryView, ChatOwnerError> {
        self.advance_clock(now_ms)?;
        self.validate_ticket(ticket, now_ms)?;
        if ticket.kind != DispatchKind::DeliveryStatus || ticket.delivery_id.is_none() {
            return Err(ChatOwnerError::NotRetirable);
        }
        self.pending
            .remove(&ticket.envelope.metadata.message_id)
            .map(|pending| pending.view)
            .ok_or(ChatOwnerError::UnknownDelivery)
    }
}
