use std::collections::BTreeMap;

use codex_hepta_types::StableId;

use super::FederationClientError;
use super::FederationWireClientV1;
use super::SealedClientFrameV1;
use super::snapshot::ClientAttemptIdentity;
use super::snapshot::ClientAttemptMetadata;
use super::snapshot::restore_client_snapshot;
use crate::codec::encode_registered_frame_v1;
use crate::codec::registered_codec_v1;
use crate::credential::PeerCredentialRegistryV1;
use crate::credential::PeerCredentialV1;
use crate::host::FederationOutboundCredentialV1;
use crate::host::MAX_FEDERATION_HOST_PEERS;
use crate::protocol::AuthenticatedFederationFrameV1;
use crate::protocol::FederationCancelMessageV1;
use crate::protocol::FederationCancellationDispositionV1;
use crate::protocol::FederationNonceV1;
use crate::protocol::FederationQueryMessageV1;
use crate::protocol::FederationWireMessageV1;
use crate::protocol::MAX_AUTHENTICATED_FRAME_LIFETIME_MS;
use crate::recovery::DurableFederationStateV1;
use crate::recovery::FederationRecoveryLimitsV1;
use crate::recovery::FederationRecoveryStoreV1;
use crate::replay::ReplayCacheV1;

impl<S> FederationWireClientV1<S>
where
    S: FederationRecoveryStoreV1,
{
    pub fn open(
        local_peer_id: StableId,
        credentials: PeerCredentialRegistryV1,
        replay_capacity: usize,
        replay_per_credential_capacity: usize,
        limits: FederationRecoveryLimitsV1,
        mut recovery_store: S,
        now_unix_ms: u64,
    ) -> Result<Self, FederationClientError> {
        let replay = ReplayCacheV1::with_limits(replay_capacity, replay_per_credential_capacity)?;
        let (recovery, attempts, frontiers) = match recovery_store.load()? {
            Some(bytes) => restore_client_snapshot(&local_peer_id, limits, now_unix_ms, &bytes)?,
            None => (
                DurableFederationStateV1::empty(local_peer_id.clone(), limits, now_unix_ms)?,
                BTreeMap::new(),
                BTreeMap::new(),
            ),
        };
        let mut client = Self {
            local_peer_id,
            limits,
            credentials,
            outbound_credentials: BTreeMap::new(),
            replay,
            recovery,
            attempts,
            frontiers,
            recovery_store,
        };
        client.persist_current()?;
        Ok(client)
    }

    pub fn local_peer_id(&self) -> &StableId {
        &self.local_peer_id
    }

    pub fn bind_outbound_credential(
        &mut self,
        receiver_peer_id: StableId,
        credential: FederationOutboundCredentialV1,
    ) -> Result<(), FederationClientError> {
        if receiver_peer_id == self.local_peer_id {
            return Err(FederationClientError::TransportPeerMismatch);
        }
        if !self
            .outbound_credentials
            .contains_key(receiver_peer_id.as_str())
            && self.outbound_credentials.len() >= MAX_FEDERATION_HOST_PEERS
        {
            return Err(FederationClientError::PeerCapacityExhausted);
        }
        self.outbound_credentials
            .insert(receiver_peer_id.as_str().to_string(), credential);
        Ok(())
    }

    pub fn enroll_credential(
        &mut self,
        credential: PeerCredentialV1,
    ) -> Result<(), FederationClientError> {
        self.credentials.enroll(credential)?;
        Ok(())
    }

    pub fn rotate_credential(
        &mut self,
        credential: PeerCredentialV1,
    ) -> Result<(), FederationClientError> {
        self.credentials.rotate(credential)?;
        Ok(())
    }

    pub fn revoke_credential(
        &mut self,
        sender_peer_id: &StableId,
        receiver_peer_id: &StableId,
        key_id: &StableId,
        generation: u64,
    ) -> Result<(), FederationClientError> {
        self.credentials
            .revoke(sender_peer_id, receiver_peer_id, key_id, generation)?;
        Ok(())
    }

    pub fn begin_query(
        &mut self,
        receiver_peer_id: &StableId,
        query: FederationQueryMessageV1,
        now_unix_ms: u64,
        expiry_ceiling_unix_ms: u64,
    ) -> Result<Vec<u8>, FederationClientError> {
        let sealed = self.seal_outbound(
            receiver_peer_id,
            FederationWireMessageV1::Query(query.clone()),
            now_unix_ms,
            expiry_ceiling_unix_ms,
        )?;
        let mut next = self.clone_recovery(now_unix_ms)?;
        next.begin_attempt(
            receiver_peer_id,
            &query.query_id,
            query.query_binding_digest,
            sealed.expires_unix_ms,
            now_unix_ms,
        )?;
        let mut attempts = self.attempts.clone();
        attempts.insert(
            ClientAttemptIdentity::new(
                receiver_peer_id,
                &query.query_id,
                query.query_binding_digest,
            ),
            ClientAttemptMetadata {
                expires_unix_ms: sealed.expires_unix_ms,
                cancellation_id: None,
            },
        );
        self.replace_state(next, attempts, self.frontiers.clone())?;
        Ok(sealed.payload)
    }

    pub fn cancel_query(
        &mut self,
        receiver_peer_id: &StableId,
        cancellation: FederationCancelMessageV1,
        now_unix_ms: u64,
        expiry_ceiling_unix_ms: u64,
    ) -> Result<Vec<u8>, FederationClientError> {
        let sealed = self.seal_outbound(
            receiver_peer_id,
            FederationWireMessageV1::Cancel(cancellation.clone()),
            now_unix_ms,
            expiry_ceiling_unix_ms,
        )?;
        let mut next = self.clone_recovery(now_unix_ms)?;
        let acknowledgement = next.observe_cancel(receiver_peer_id, &cancellation, now_unix_ms)?;
        match acknowledgement.disposition {
            FederationCancellationDispositionV1::ObservedBeforeTerminal => {}
            FederationCancellationDispositionV1::TerminalAlreadyObserved => {
                return Err(FederationClientError::AttemptAlreadyTerminal);
            }
            FederationCancellationDispositionV1::UnknownAttempt => {
                return Err(FederationClientError::UnknownAttempt);
            }
        }
        let identity = ClientAttemptIdentity::new(
            receiver_peer_id,
            &cancellation.query_id,
            cancellation.query_binding_digest,
        );
        let mut attempts = self.attempts.clone();
        let metadata = attempts
            .get_mut(&identity)
            .ok_or(FederationClientError::UnknownAttempt)?;
        metadata.cancellation_id = Some(cancellation.cancellation_id);
        self.replace_state(next, attempts, self.frontiers.clone())?;
        Ok(sealed.payload)
    }

    pub fn into_recovery_store(self) -> S {
        self.recovery_store
    }

    pub(super) fn seal_outbound(
        &self,
        receiver_peer_id: &StableId,
        message: FederationWireMessageV1,
        now_unix_ms: u64,
        expiry_ceiling_unix_ms: u64,
    ) -> Result<SealedClientFrameV1, FederationClientError> {
        let selector = self
            .outbound_credentials
            .get(receiver_peer_id.as_str())
            .ok_or(FederationClientError::MissingOutboundCredential)?;
        let credential = self.credentials.require_current(
            &self.local_peer_id,
            receiver_peer_id,
            selector.key_id(),
            selector.generation(),
            now_unix_ms,
        )?;
        let expires_unix_ms = expiry_ceiling_unix_ms
            .min(credential.expires_unix_ms())
            .min(now_unix_ms.saturating_add(MAX_AUTHENTICATED_FRAME_LIFETIME_MS));
        if expires_unix_ms <= now_unix_ms {
            return Err(FederationClientError::FrameExpired);
        }
        let frame = AuthenticatedFederationFrameV1::seal(
            credential,
            now_unix_ms,
            expires_unix_ms,
            FederationNonceV1::generate()?,
            message,
        )?;
        let (schemas, codec) = registered_codec_v1().map_err(|_| FederationClientError::Codec)?;
        let payload = encode_registered_frame_v1(&schemas, &codec, &frame)
            .map_err(|_| FederationClientError::Codec)?;
        Ok(SealedClientFrameV1 {
            payload,
            expires_unix_ms,
        })
    }
}
