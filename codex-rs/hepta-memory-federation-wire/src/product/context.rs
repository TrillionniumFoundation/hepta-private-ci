use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use hmac::Hmac;
use hmac::Mac;
use sha2::Sha256;
use zeroize::Zeroize;

use super::error::FederationProductErrorV1;
use super::packet::MAX_FEDERATION_PRODUCT_PACKET_BYTES;

pub const FEDERATION_TRANSPORT_CONTEXT_KEY_BYTES: usize = 32;
const FEDERATION_TRANSPORT_CONTEXT_DOMAIN: &[u8] =
    b"hepta:memory-federation:authenticated-transport-context:v1";
type HmacSha256 = Hmac<Sha256>;

/// Evidence emitted only by a configured transport-context issuer after the
/// selected transport authenticated its local endpoint, peer, and channel.
///
/// The fields and attestation are private. Callers cannot construct a context
/// directly or rewrite the local owner, peer, profile, channel binding,
/// lifetime, key, or generation after issuance.
///
/// ```compile_fail
/// use codex_hepta_memory_federation_wire::FederationAuthenticatedTransportV1;
/// let _ = FederationAuthenticatedTransportV1::from_verified_channel;
/// ```
#[derive(Clone, Eq, PartialEq)]
pub struct FederationAuthenticatedTransportV1 {
    local_peer_id: StableId,
    peer_id: StableId,
    transport_profile_id: StableId,
    channel_binding_digest: Digest32,
    established_unix_ms: u64,
    expires_unix_ms: u64,
    context_key_id: StableId,
    context_key_generation: u64,
    attestation: Digest32,
}

impl fmt::Debug for FederationAuthenticatedTransportV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FederationAuthenticatedTransportV1")
            .field("local_peer_id", &self.local_peer_id)
            .field("peer_id", &self.peer_id)
            .field("transport_profile_id", &self.transport_profile_id)
            .field("channel_binding_digest", &self.channel_binding_digest)
            .field("established_unix_ms", &self.established_unix_ms)
            .field("expires_unix_ms", &self.expires_unix_ms)
            .field("context_key_id", &self.context_key_id)
            .field("context_key_generation", &self.context_key_generation)
            .field("attestation", &"<verified>")
            .finish()
    }
}

impl FederationAuthenticatedTransportV1 {
    pub fn local_peer_id(&self) -> &StableId {
        &self.local_peer_id
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

    pub fn context_key_id(&self) -> &StableId {
        &self.context_key_id
    }

    pub const fn context_key_generation(&self) -> u64 {
        self.context_key_generation
    }
}

/// Minting capability owned by one selected authenticated transport endpoint.
/// The attestation key is deployment secret material and is never serialized
/// into the product packet, recovery snapshot, or source-controlled profile.
pub struct FederationTransportContextIssuerV1 {
    local_peer_id: StableId,
    transport_profile_id: StableId,
    context_key_id: StableId,
    context_key_generation: u64,
    secret: [u8; FEDERATION_TRANSPORT_CONTEXT_KEY_BYTES],
}

impl FederationTransportContextIssuerV1 {
    pub fn new(
        local_peer_id: StableId,
        transport_profile_id: StableId,
        context_key_id: StableId,
        context_key_generation: u64,
        secret: [u8; FEDERATION_TRANSPORT_CONTEXT_KEY_BYTES],
    ) -> Result<Self, FederationProductErrorV1> {
        if context_key_generation == 0 || secret.iter().all(|byte| *byte == 0) {
            return Err(FederationProductErrorV1::InvalidTransportContext);
        }
        Ok(Self {
            local_peer_id,
            transport_profile_id,
            context_key_id,
            context_key_generation,
            secret,
        })
    }

    pub fn local_peer_id(&self) -> &StableId {
        &self.local_peer_id
    }

    pub fn transport_profile_id(&self) -> &StableId {
        &self.transport_profile_id
    }

    pub fn verifier(&self) -> FederationTransportContextVerifierV1 {
        FederationTransportContextVerifierV1 {
            local_peer_id: self.local_peer_id.clone(),
            transport_profile_id: self.transport_profile_id.clone(),
            context_key_id: self.context_key_id.clone(),
            context_key_generation: self.context_key_generation,
            secret: self.secret,
        }
    }

    pub fn issue_verified_channel(
        &self,
        peer_id: StableId,
        channel_binding_digest: Digest32,
        established_unix_ms: u64,
        expires_unix_ms: u64,
    ) -> Result<FederationAuthenticatedTransportV1, FederationProductErrorV1> {
        if peer_id == self.local_peer_id
            || channel_binding_digest.is_zero()
            || established_unix_ms == 0
            || established_unix_ms >= expires_unix_ms
        {
            return Err(FederationProductErrorV1::InvalidTransportContext);
        }
        let payload = transport_context_payload(
            &self.local_peer_id,
            &peer_id,
            &self.transport_profile_id,
            channel_binding_digest,
            established_unix_ms,
            expires_unix_ms,
            &self.context_key_id,
            self.context_key_generation,
        )?;
        let attestation = sign_transport_context(&self.secret, &payload)?;
        Ok(FederationAuthenticatedTransportV1 {
            local_peer_id: self.local_peer_id.clone(),
            peer_id,
            transport_profile_id: self.transport_profile_id.clone(),
            channel_binding_digest,
            established_unix_ms,
            expires_unix_ms,
            context_key_id: self.context_key_id.clone(),
            context_key_generation: self.context_key_generation,
            attestation,
        })
    }
}

impl fmt::Debug for FederationTransportContextIssuerV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FederationTransportContextIssuerV1")
            .field("local_peer_id", &self.local_peer_id)
            .field("transport_profile_id", &self.transport_profile_id)
            .field("context_key_id", &self.context_key_id)
            .field("context_key_generation", &self.context_key_generation)
            .field("secret", &"<redacted>")
            .finish()
    }
}

impl Drop for FederationTransportContextIssuerV1 {
    fn drop(&mut self) {
        self.secret.zeroize();
    }
}

/// Verification capability held by the product bridge for one local wire
/// owner. A context minted for another local host, key, generation, or transport
/// profile fails before replay or attempt state is consumed.
pub struct FederationTransportContextVerifierV1 {
    local_peer_id: StableId,
    transport_profile_id: StableId,
    context_key_id: StableId,
    context_key_generation: u64,
    secret: [u8; FEDERATION_TRANSPORT_CONTEXT_KEY_BYTES],
}

impl FederationTransportContextVerifierV1 {
    pub fn local_peer_id(&self) -> &StableId {
        &self.local_peer_id
    }

    pub fn transport_profile_id(&self) -> &StableId {
        &self.transport_profile_id
    }

    pub fn require_current_context(
        &self,
        context: &FederationAuthenticatedTransportV1,
        expected_transport_profile_id: &StableId,
        now_unix_ms: u64,
    ) -> Result<(), FederationProductErrorV1> {
        if context.transport_profile_id != self.transport_profile_id
            || &context.transport_profile_id != expected_transport_profile_id
        {
            return Err(FederationProductErrorV1::TransportProfileMismatch);
        }
        if context.local_peer_id != self.local_peer_id
            || context.peer_id == self.local_peer_id
            || context.context_key_id != self.context_key_id
            || context.context_key_generation != self.context_key_generation
        {
            return Err(FederationProductErrorV1::InvalidTransportContext);
        }
        if now_unix_ms < context.established_unix_ms || now_unix_ms >= context.expires_unix_ms {
            return Err(FederationProductErrorV1::TransportContextExpired);
        }
        if context.channel_binding_digest.is_zero() {
            return Err(FederationProductErrorV1::InvalidTransportContext);
        }
        let payload = transport_context_payload(
            &context.local_peer_id,
            &context.peer_id,
            &context.transport_profile_id,
            context.channel_binding_digest,
            context.established_unix_ms,
            context.expires_unix_ms,
            &context.context_key_id,
            context.context_key_generation,
        )?;
        verify_transport_context(&self.secret, &payload, context.attestation)
    }
}

impl fmt::Debug for FederationTransportContextVerifierV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FederationTransportContextVerifierV1")
            .field("local_peer_id", &self.local_peer_id)
            .field("transport_profile_id", &self.transport_profile_id)
            .field("context_key_id", &self.context_key_id)
            .field("context_key_generation", &self.context_key_generation)
            .field("secret", &"<redacted>")
            .finish()
    }
}

impl Drop for FederationTransportContextVerifierV1 {
    fn drop(&mut self) {
        self.secret.zeroize();
    }
}

fn transport_context_payload(
    local_peer_id: &StableId,
    peer_id: &StableId,
    transport_profile_id: &StableId,
    channel_binding_digest: Digest32,
    established_unix_ms: u64,
    expires_unix_ms: u64,
    context_key_id: &StableId,
    context_key_generation: u64,
) -> Result<Vec<u8>, FederationProductErrorV1> {
    let mut payload = Vec::with_capacity(288);
    append_transport_component(&mut payload, FEDERATION_TRANSPORT_CONTEXT_DOMAIN)?;
    append_transport_component(&mut payload, local_peer_id.as_str().as_bytes())?;
    append_transport_component(&mut payload, peer_id.as_str().as_bytes())?;
    append_transport_component(&mut payload, transport_profile_id.as_str().as_bytes())?;
    append_transport_component(&mut payload, channel_binding_digest.as_array())?;
    append_transport_component(&mut payload, &established_unix_ms.to_be_bytes())?;
    append_transport_component(&mut payload, &expires_unix_ms.to_be_bytes())?;
    append_transport_component(&mut payload, context_key_id.as_str().as_bytes())?;
    append_transport_component(&mut payload, &context_key_generation.to_be_bytes())?;
    Ok(payload)
}

fn append_transport_component(
    output: &mut Vec<u8>,
    component: &[u8],
) -> Result<(), FederationProductErrorV1> {
    let length = u32::try_from(component.len())
        .map_err(|_| FederationProductErrorV1::InvalidTransportContext)?;
    output.extend_from_slice(&length.to_be_bytes());
    output.extend_from_slice(component);
    Ok(())
}

fn sign_transport_context(
    secret: &[u8; FEDERATION_TRANSPORT_CONTEXT_KEY_BYTES],
    payload: &[u8],
) -> Result<Digest32, FederationProductErrorV1> {
    let mut mac = HmacSha256::new_from_slice(secret)
        .map_err(|_| FederationProductErrorV1::InvalidTransportContext)?;
    mac.update(payload);
    let bytes = mac.finalize().into_bytes();
    let mut attestation = [0_u8; 32];
    attestation.copy_from_slice(&bytes);
    Ok(Digest32::from_array(attestation))
}

fn verify_transport_context(
    secret: &[u8; FEDERATION_TRANSPORT_CONTEXT_KEY_BYTES],
    payload: &[u8],
    attestation: Digest32,
) -> Result<(), FederationProductErrorV1> {
    let mut mac = HmacSha256::new_from_slice(secret)
        .map_err(|_| FederationProductErrorV1::InvalidTransportContext)?;
    mac.update(payload);
    mac.verify_slice(attestation.as_array())
        .map_err(|_| FederationProductErrorV1::InvalidTransportContext)
}

/// Source-controlled product profile. It narrows the packet budget and pins a
/// transport profile identity; it does not select a network implementation or
/// contain transport-context attestation secret material.
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
