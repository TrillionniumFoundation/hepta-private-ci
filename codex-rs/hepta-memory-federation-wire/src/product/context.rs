use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::error::FederationProductErrorV1;
use super::packet::MAX_FEDERATION_PRODUCT_PACKET_BYTES;

/// Evidence emitted only after a selected transport authenticated its peer and
/// channel. Ordinary product code cannot substitute a bare peer string.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationAuthenticatedTransportV1 {
    peer_id: StableId,
    transport_profile_id: StableId,
    channel_binding_digest: Digest32,
    established_unix_ms: u64,
    expires_unix_ms: u64,
}

impl FederationAuthenticatedTransportV1 {
    pub fn from_verified_channel(
        peer_id: StableId,
        transport_profile_id: StableId,
        channel_binding_digest: Digest32,
        established_unix_ms: u64,
        expires_unix_ms: u64,
    ) -> Result<Self, FederationProductErrorV1> {
        if channel_binding_digest.is_zero()
            || established_unix_ms == 0
            || established_unix_ms >= expires_unix_ms
        {
            return Err(FederationProductErrorV1::InvalidTransportContext);
        }
        Ok(Self {
            peer_id,
            transport_profile_id,
            channel_binding_digest,
            established_unix_ms,
            expires_unix_ms,
        })
    }

    pub fn peer_id(&self) -> &StableId {
        &self.peer_id
    }

    pub fn transport_profile_id(&self) -> &StableId {
        &self.transport_profile_id
    }

    pub const fn channel_binding_digest(&self) -> Digest32 {
        self.channel_binding_digest
    }

    pub const fn established_unix_ms(&self) -> u64 {
        self.established_unix_ms
    }

    pub const fn expires_unix_ms(&self) -> u64 {
        self.expires_unix_ms
    }

    pub(super) fn require_current_profile(
        &self,
        expected_transport_profile_id: &StableId,
        now_unix_ms: u64,
    ) -> Result<(), FederationProductErrorV1> {
        if &self.transport_profile_id != expected_transport_profile_id {
            return Err(FederationProductErrorV1::TransportProfileMismatch);
        }
        if now_unix_ms < self.established_unix_ms || now_unix_ms >= self.expires_unix_ms {
            return Err(FederationProductErrorV1::TransportContextExpired);
        }
        if self.channel_binding_digest.is_zero() {
            return Err(FederationProductErrorV1::InvalidTransportContext);
        }
        Ok(())
    }
}

/// Source-controlled product profile. It narrows the packet budget and pins a
/// transport profile identity; it does not select a network implementation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationProductProfileV1 {
    profile_id: StableId,
    transport_profile_id: StableId,
    maximum_packet_bytes: usize,
}

impl FederationProductProfileV1 {
    pub fn new(
        profile_id: StableId,
        transport_profile_id: StableId,
        maximum_packet_bytes: usize,
    ) -> Result<Self, FederationProductErrorV1> {
        if !(64..=MAX_FEDERATION_PRODUCT_PACKET_BYTES).contains(&maximum_packet_bytes) {
            return Err(FederationProductErrorV1::InvalidProfile);
        }
        Ok(Self {
            profile_id,
            transport_profile_id,
            maximum_packet_bytes,
        })
    }

    pub fn profile_id(&self) -> &StableId {
        &self.profile_id
    }

    pub fn transport_profile_id(&self) -> &StableId {
        &self.transport_profile_id
    }

    pub const fn maximum_packet_bytes(&self) -> usize {
        self.maximum_packet_bytes
    }
}
