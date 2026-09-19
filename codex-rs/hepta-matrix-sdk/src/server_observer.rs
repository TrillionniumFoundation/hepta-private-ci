use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_store::OutboxRecord;
use matrix_sdk::ruma::OwnedEventId;
use matrix_sdk::ruma::OwnedRoomId;

use crate::MatrixObserveFuture;
use crate::MatrixOutboundObserver;
use crate::MatrixSdkClient;
use crate::MatrixServerObservation;
use crate::MatrixTransportError;

impl MatrixOutboundObserver for MatrixSdkClient {
    fn observe_server_event<'a>(
        &'a self,
        record: &'a OutboxRecord,
        event_id: &'a MatrixEventId,
    ) -> MatrixObserveFuture<'a> {
        Box::pin(async move {
            if !self
                .config()
                .binding
                .allowed_rooms
                .contains(&record.room_id)
                || record.binding_revision != self.config().binding.revision
                || record.generation != self.config().matrix_generation
            {
                return Err(MatrixTransportError::Permanent);
            }
            let native_room_id = OwnedRoomId::try_from(record.room_id.as_str())
                .map_err(|_| MatrixTransportError::Permanent)?;
            let native_event_id = OwnedEventId::try_from(event_id.as_str())
                .map_err(|_| MatrixTransportError::Permanent)?;
            let room = self
                .client()
                .get_room(&native_room_id)
                .ok_or(MatrixTransportError::Retryable)?;

            // This is deliberately a fresh authenticated homeserver request,
            // not an event-cache lookup and not a reinterpretation of the send
            // response. It closes the response-loss window even when /sync has
            // already advanced past the event and omitted unsigned txn data.
            let observed = room
                .event(&native_event_id, None)
                .await
                .map_err(|_| MatrixTransportError::Retryable)?;
            let raw = observed.raw();
            let observed_event_id = raw
                .get_field::<String>("event_id")
                .map_err(|_| MatrixTransportError::Permanent)?
                .ok_or(MatrixTransportError::Permanent)?;
            let observed_sender = raw
                .get_field::<String>("sender")
                .map_err(|_| MatrixTransportError::Permanent)?
                .ok_or(MatrixTransportError::Permanent)?;
            if observed_event_id != event_id.as_str()
                || observed_sender != self.config().binding.expected_mxid.as_str()
            {
                return Err(MatrixTransportError::Permanent);
            }
            Ok(Some(MatrixServerObservation {
                event_id: event_id.clone(),
                observation_digest: Sha256Digest::for_bytes(raw.json().get().as_bytes())
                    .as_str()
                    .to_string(),
            }))
        })
    }
}
