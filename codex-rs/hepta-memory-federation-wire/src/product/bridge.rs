use codex_hepta_memory_federation::FederatedQueryV2;
use codex_hepta_memory_federation::RemoteFederatedResponseV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AdmittedFederationQueryV1;
use crate::AuthenticatedFrontierV1;
use crate::FederationHostAdmissionV1;
use crate::FederationHostQueryResultV1;
use crate::FederationQueryMessageV1;
use crate::FederationRecoveryStoreV1;
use crate::FederationWireClientV1;
use crate::FederationWireHostV1;
use crate::FederationWireMessageV1;
use crate::decode_registered_frame_v1;
use crate::registered_codec_v1;

use super::body::decode_query_v2;
use super::body::decode_response_v2;
use super::body::encode_query_v2;
use super::body::encode_response_v2;
use super::body::validate_response_for_query;
use super::body::validate_response_shape;
use super::context::FederationAuthenticatedTransportV1;
use super::context::FederationProductProfileV1;
use super::context::FederationTransportContextVerifierV1;
use super::error::FederationProductErrorV1;
use super::packet::FederationProductPacketV1;

/// Query admitted only after the selected transport context, authenticated
/// frame and canonical V2 body have all been checked.
pub struct AdmittedFederationProductQueryV1 {
    wire: AdmittedFederationQueryV1,
    query: FederatedQueryV2,
    transport_expires_unix_ms: u64,
}

impl AdmittedFederationProductQueryV1 {
    pub const fn query(&self) -> &FederatedQueryV2 {
        &self.query
    }

    pub fn transport_peer_id(&self) -> &StableId {
        self.wire.peer_id()
    }
}

pub enum FederationProductHostAdmissionV1 {
    Query(AdmittedFederationProductQueryV1),
    Reply(Vec<u8>),
    Inbound(crate::VerifiedFederationFrameV1),
}

pub struct FederationProductHostV1<S>
where
    S: FederationRecoveryStoreV1,
{
    wire: FederationWireHostV1<S>,
    profile: FederationProductProfileV1,
    transport_context_verifier: FederationTransportContextVerifierV1,
}

impl<S> FederationProductHostV1<S>
where
    S: FederationRecoveryStoreV1,
{
    pub fn new(
        wire: FederationWireHostV1<S>,
        profile: FederationProductProfileV1,
        transport_context_verifier: FederationTransportContextVerifierV1,
    ) -> Result<Self, FederationProductErrorV1> {
        if transport_context_verifier.transport_profile_id() != profile.transport_profile_id() {
            return Err(FederationProductErrorV1::TransportProfileMismatch);
        }
        if transport_context_verifier.local_peer_id() != wire.local_peer_id() {
            return Err(FederationProductErrorV1::InvalidTransportContext);
        }
        Ok(Self {
            wire,
            profile,
            transport_context_verifier,
        })
    }

    pub fn local_peer_id(&self) -> &StableId {
        self.wire.local_peer_id()
    }

    pub fn profile(&self) -> &FederationProductProfileV1 {
        &self.profile
    }

    pub fn admit(
        &mut self,
        transport: &FederationAuthenticatedTransportV1,
        payload: &[u8],
        now_unix_ms: u64,
    ) -> Result<FederationProductHostAdmissionV1, FederationProductErrorV1> {
        self.transport_context_verifier.require_current_context(
            transport,
            self.profile.transport_profile_id(),
            now_unix_ms,
        )?;
        let packet = FederationProductPacketV1::decode(payload, &self.profile)?;
        let preflight = decode_untrusted_frame(packet.authenticated_frame())?;
        if &preflight.sender_peer_id != transport.peer_id() {
            return Err(FederationProductErrorV1::TransportPeerMismatch);
        }
        let preflight_query = match &preflight.message {
            FederationWireMessageV1::Query(wire_query) => {
                if packet.body().is_empty() {
                    return Err(FederationProductErrorV1::MissingBody);
                }
                let query = decode_query_v2(packet.body())?;
                query.validate(now_unix_ms)?;
                require_query_binding(&query, wire_query, self.wire.local_peer_id())?;
                if query.deadline_unix_ms > preflight.expires_unix_ms
                    || query.deadline_unix_ms > transport.expires_unix_ms()
                {
                    return Err(FederationProductErrorV1::QueryBeyondAuthenticatedHorizon);
                }
                Some(query)
            }
            FederationWireMessageV1::Cancel(_)
            | FederationWireMessageV1::Response(_)
            | FederationWireMessageV1::CancelAck(_) => {
                if !packet.body().is_empty() {
                    return Err(FederationProductErrorV1::UnexpectedBody);
                }
                None
            }
        };
        let wire_admission = self.wire.admit(
            transport.peer_id(),
            packet.authenticated_frame(),
            now_unix_ms,
        )?;
        match (wire_admission, preflight_query) {
            (FederationHostAdmissionV1::Query(wire), Some(query)) => Ok(
                FederationProductHostAdmissionV1::Query(AdmittedFederationProductQueryV1 {
                    wire,
                    query,
                    transport_expires_unix_ms: transport.expires_unix_ms(),
                }),
            ),
            (FederationHostAdmissionV1::Reply(frame), None) => {
                let packet = FederationProductPacketV1::new(frame, Vec::new())?.encode()?;
                Ok(FederationProductHostAdmissionV1::Reply(packet))
            }
            (FederationHostAdmissionV1::Inbound(frame), None) => {
                Ok(FederationProductHostAdmissionV1::Inbound(frame))
            }
            (FederationHostAdmissionV1::Query(_), None)
            | (FederationHostAdmissionV1::Reply(_), Some(_))
            | (FederationHostAdmissionV1::Inbound(_), Some(_)) => {
                Err(FederationProductErrorV1::UnexpectedWireMessage)
            }
        }
    }

    pub fn complete_query(
        &mut self,
        admitted: AdmittedFederationProductQueryV1,
        response: RemoteFederatedResponseV2,
        frontier: AuthenticatedFrontierV1,
        now_unix_ms: u64,
    ) -> Result<Vec<u8>, FederationProductErrorV1> {
        validate_response_for_query(&response, &admitted.query)?;
        if response.expires_unix_ms > admitted.wire.response_expiry_ceiling_unix_ms()
            || response.expires_unix_ms > admitted.transport_expires_unix_ms
        {
            return Err(FederationProductErrorV1::ResponseBeyondAuthenticatedHorizon);
        }
        if frontier.owner_peer_id != response.peer_id
            || frontier.frontier != response.observed_frontier
            || frontier.observed_unix_ms > response.expires_unix_ms
        {
            return Err(FederationProductErrorV1::FrontierResponseMismatch);
        }
        let body = encode_response_v2(&response)?;
        let result = FederationHostQueryResultV1::new(
            response.response_digest,
            Digest32::of_bytes(&body),
            frontier,
        )?;
        let frame = self
            .wire
            .complete_query(admitted.wire, result, now_unix_ms)?;
        FederationProductPacketV1::new(frame, body)?.encode()
    }

    pub fn into_wire_host(self) -> FederationWireHostV1<S> {
        self.wire
    }
}

pub struct FederationProductClientV1<S>
where
    S: FederationRecoveryStoreV1,
{
    wire: FederationWireClientV1<S>,
    profile: FederationProductProfileV1,
    transport_context_verifier: FederationTransportContextVerifierV1,
}

impl<S> FederationProductClientV1<S>
where
    S: FederationRecoveryStoreV1,
{
    pub fn new(
        wire: FederationWireClientV1<S>,
        profile: FederationProductProfileV1,
        transport_context_verifier: FederationTransportContextVerifierV1,
    ) -> Result<Self, FederationProductErrorV1> {
        if transport_context_verifier.transport_profile_id() != profile.transport_profile_id() {
            return Err(FederationProductErrorV1::TransportProfileMismatch);
        }
        if transport_context_verifier.local_peer_id() != wire.local_peer_id() {
            return Err(FederationProductErrorV1::InvalidTransportContext);
        }
        Ok(Self {
            wire,
            profile,
            transport_context_verifier,
        })
    }

    pub fn profile(&self) -> &FederationProductProfileV1 {
        &self.profile
    }

    pub fn begin_query(
        &mut self,
        query: &FederatedQueryV2,
        now_unix_ms: u64,
    ) -> Result<Vec<u8>, FederationProductErrorV1> {
        query.validate(now_unix_ms)?;
        let body = encode_query_v2(query)?;
        let wire_query = FederationQueryMessageV1 {
            query_id: query.query_id.clone(),
            query_binding_digest: query.binding_digest(),
            scope_digest: query.scope_digest,
            purpose_digest: query.purpose_digest,
            generation_vector_digest: query.generation_vector_digest,
            maximum_results: query.maximum_results,
        };
        let frame = self.wire.begin_query(
            &query.peer_id,
            wire_query,
            now_unix_ms,
            query.deadline_unix_ms,
        )?;
        FederationProductPacketV1::new(frame, body)?.encode()
    }

    pub fn admit_response(
        &mut self,
        transport: &FederationAuthenticatedTransportV1,
        payload: &[u8],
        now_unix_ms: u64,
    ) -> Result<RemoteFederatedResponseV2, FederationProductErrorV1> {
        self.transport_context_verifier.require_current_context(
            transport,
            self.profile.transport_profile_id(),
            now_unix_ms,
        )?;
        let packet = FederationProductPacketV1::decode(payload, &self.profile)?;
        if packet.body().is_empty() {
            return Err(FederationProductErrorV1::MissingBody);
        }
        let preflight = decode_untrusted_frame(packet.authenticated_frame())?;
        if &preflight.sender_peer_id != transport.peer_id() {
            return Err(FederationProductErrorV1::TransportPeerMismatch);
        }
        let FederationWireMessageV1::Response(wire_response) = &preflight.message else {
            return Err(FederationProductErrorV1::UnexpectedWireMessage);
        };
        if Digest32::of_bytes(packet.body()) != wire_response.result_digest {
            return Err(FederationProductErrorV1::BodyDigestMismatch);
        }
        let response = decode_response_v2(packet.body())?;
        if &response.peer_id != transport.peer_id()
            || response.expires_unix_ms > preflight.expires_unix_ms
            || response.expires_unix_ms > transport.expires_unix_ms()
            || response.query_binding_digest != wire_response.query_binding_digest
            || response.response_digest != wire_response.response_digest
            || response.observed_frontier != wire_response.frontier.frontier
        {
            return Err(FederationProductErrorV1::ResponseBindingMismatch);
        }
        validate_response_shape(&response)?;
        let verified = self.wire.admit(
            transport.peer_id(),
            packet.authenticated_frame(),
            now_unix_ms,
        )?;
        if !matches!(verified.message(), FederationWireMessageV1::Response(_)) {
            return Err(FederationProductErrorV1::UnexpectedWireMessage);
        }
        Ok(response)
    }

    pub fn into_wire_client(self) -> FederationWireClientV1<S> {
        self.wire
    }
}

fn decode_untrusted_frame(
    payload: &[u8],
) -> Result<crate::AuthenticatedFederationFrameV1, FederationProductErrorV1> {
    let (schemas, codec) =
        registered_codec_v1().map_err(|_| FederationProductErrorV1::WireCodec)?;
    decode_registered_frame_v1(&schemas, &codec, payload)
        .map_err(|_| FederationProductErrorV1::WireCodec)
}

fn require_query_binding(
    query: &FederatedQueryV2,
    wire: &FederationQueryMessageV1,
    local_peer_id: &StableId,
) -> Result<(), FederationProductErrorV1> {
    if &query.peer_id != local_peer_id
        || query.query_id != wire.query_id
        || query.binding_digest() != wire.query_binding_digest
        || query.scope_digest != wire.scope_digest
        || query.purpose_digest != wire.purpose_digest
        || query.generation_vector_digest != wire.generation_vector_digest
        || query.maximum_results != wire.maximum_results
    {
        return Err(FederationProductErrorV1::QueryBindingMismatch);
    }
    Ok(())
}
