use codex_hepta_types::StableId;

use super::FederationClientError;
use super::FederationWireClientV1;
use super::snapshot::ClientAttemptIdentity;
use super::snapshot::ClientAttemptMetadata;
use crate::codec::decode_registered_frame_v1;
use crate::codec::registered_codec_v1;
use crate::protocol::FederationCancelAckMessageV1;
use crate::protocol::FederationWireMessageV1;
use crate::protocol::VerifiedFederationFrameV1;
use crate::recovery::DurableFederationStateV1;
use crate::recovery::FederationRecoveryStoreV1;

impl<S> FederationWireClientV1<S>
where
    S: FederationRecoveryStoreV1,
{
    pub fn admit(
        &mut self,
        transport_peer_id: &StableId,
        payload: &[u8],
        now_unix_ms: u64,
    ) -> Result<VerifiedFederationFrameV1, FederationClientError> {
        let (schemas, codec) = registered_codec_v1().map_err(|_| FederationClientError::Codec)?;
        let frame = decode_registered_frame_v1(&schemas, &codec, payload)
            .map_err(|_| FederationClientError::Codec)?;
        if &frame.sender_peer_id != transport_peer_id {
            return Err(FederationClientError::TransportPeerMismatch);
        }

        let mut next = self.clone_recovery(now_unix_ms)?;
        let durable_replay_key = next.preflight_frame(
            &frame.sender_peer_id,
            &frame.receiver_peer_id,
            &frame.key_id,
            frame.key_generation,
            frame.nonce.as_bytes(),
            frame.expires_unix_ms,
            now_unix_ms,
        )?;
        let verified = frame.verify(
            &self.local_peer_id,
            now_unix_ms,
            &self.credentials,
            &mut self.replay,
        )?;
        next.record_verified_frame(
            durable_replay_key,
            verified.sender_peer_id(),
            verified.expires_unix_ms(),
        )?;

        match verified.message() {
            FederationWireMessageV1::Response(response) => {
                if &response.frontier.owner_peer_id != verified.sender_peer_id() {
                    return Err(FederationClientError::FrontierOwnerMismatch);
                }
                if response.frontier.observed_unix_ms > verified.issued_unix_ms() {
                    return Err(FederationClientError::RemoteObservationClockInvalid);
                }
                match self.frontiers.get(verified.sender_peer_id().as_str()) {
                    Some(previous) => response
                        .frontier
                        .require_successor_of(previous)
                        .map_err(FederationClientError::Protocol)?,
                    None if !response.frontier.parent_witness_digest.is_zero() => {
                        return Err(FederationClientError::FrontierChainUnanchored);
                    }
                    None => {}
                }
                let identity = ClientAttemptIdentity::new(
                    verified.sender_peer_id(),
                    &response.query_id,
                    response.query_binding_digest,
                );
                let metadata = self
                    .attempts
                    .get(&identity)
                    .ok_or(FederationClientError::UnknownAttempt)?;
                if metadata.cancellation_id.is_some() {
                    return Err(FederationClientError::AttemptCancelled);
                }
                next.observe_terminal(
                    verified.sender_peer_id(),
                    &response.query_id,
                    response.query_binding_digest,
                    verified.message().binding_digest(),
                    now_unix_ms,
                )?;
                let mut attempts = self.attempts.clone();
                attempts.remove(&identity);
                let mut frontiers = self.frontiers.clone();
                frontiers.insert(
                    verified.sender_peer_id().as_str().to_string(),
                    response.frontier.clone(),
                );
                self.replace_state(next, attempts, frontiers)?;
            }
            FederationWireMessageV1::CancelAck(acknowledgement) => {
                self.validate_cancellation_ack(
                    &next,
                    verified.sender_peer_id(),
                    acknowledgement,
                    verified.issued_unix_ms(),
                )?;
                self.replace_state(
                    next,
                    self.attempts.clone(),
                    self.frontiers.clone(),
                )?;
            }
            FederationWireMessageV1::Query(_) | FederationWireMessageV1::Cancel(_) => {
                return Err(FederationClientError::UnexpectedInboundMessage);
            }
        }
        Ok(verified)
    }

    pub(super) fn validate_cancellation_ack(
        &self,
        recovery: &DurableFederationStateV1,
        peer_id: &StableId,
        acknowledgement: &FederationCancelAckMessageV1,
        frame_issued_unix_ms: u64,
    ) -> Result<(), FederationClientError> {
        if acknowledgement.observed_unix_ms > frame_issued_unix_ms {
            return Err(FederationClientError::RemoteObservationClockInvalid);
        }
        if !recovery.is_cancelled(
            peer_id,
            &acknowledgement.query_id,
            acknowledgement.query_binding_digest,
        ) {
            return Err(FederationClientError::UnknownCancellation);
        }
        let identity = ClientAttemptIdentity::new(
            peer_id,
            &acknowledgement.query_id,
            acknowledgement.query_binding_digest,
        );
        match self.attempts.get(&identity) {
            Some(ClientAttemptMetadata {
                cancellation_id: Some(expected),
                ..
            }) if expected == &acknowledgement.cancellation_id => Ok(()),
            Some(ClientAttemptMetadata {
                cancellation_id: Some(_),
                ..
            }) => Err(FederationClientError::CancellationAckMismatch),
            Some(_) | None => Err(FederationClientError::UnknownCancellation),
        }
    }

}
