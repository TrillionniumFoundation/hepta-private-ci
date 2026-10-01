use std::error::Error;
use std::sync::Arc;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::DecodedEnvelope;
use codex_hepta_wire::FrozenSchemaRegistryBuilder;
use codex_hepta_wire::ManagedAuthenticatedWireSession;
use codex_hepta_wire::NegotiationOffer;
use codex_hepta_wire::NegotiationTranscript;
use codex_hepta_wire::SchemaDescriptor;
use codex_hepta_wire::SchemaPolicy;
use codex_hepta_wire::SessionEndpoint;
use codex_hepta_wire::SessionMacKey;
use codex_hepta_wire::WireCapabilities;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireSession;
use codex_hepta_wire::WireVersion;
use codex_hepta_wire::negotiate;

pub type Outcome<T = ()> = Result<T, Box<dyn Error>>;

pub fn session(channel: u8) -> Outcome<WireSession> {
    let schema = StableId::new("schema.managed-fuzz.v1")?;
    let producer = StableId::new("producer.managed-fuzz")?;
    let role = StableId::new("role.managed-fuzz")?;
    let descriptor = SchemaDescriptor::new(schema, WireVersion::V2, WireVersion::V2, 4096)?;
    let required = WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
    let mut builder = FrozenSchemaRegistryBuilder::new();
    builder.register(SchemaPolicy::new(
        descriptor,
        vec![producer],
        vec![role.clone()],
        required,
    )?)?;
    let registry = Arc::new(builder.freeze()?);
    let offer = NegotiationOffer::current();
    let negotiated = negotiate(&offer, &offer, required)?;
    let transcript = NegotiationTranscript::from_offers(
        &offer,
        &offer,
        negotiated,
        registry.snapshot_digest(),
        &[channel; 32],
    )?;
    Ok(WireSession::new(negotiated, role, registry, transcript)?)
}

pub fn owner(channel: u8, endpoint: SessionEndpoint) -> Outcome<ManagedAuthenticatedWireSession> {
    Ok(ManagedAuthenticatedWireSession::new(
        session(channel)?,
        SessionMacKey::new([9; 32])?,
        endpoint,
    )?)
}

pub fn envelope(payload: &[u8], producer: &str) -> Outcome<DecodedEnvelope> {
    // These are positive-path fixtures used before tamper/policy tests. The
    // frozen wire contract rejects empty bodies, so an empty fuzz corpus maps
    // to the minimum legal positive fixture, not an ignored constructor error.
    // Raw invalid records are still tested unchanged at the receive boundary.
    let payload = if payload.is_empty() {
        vec![0]
    } else {
        payload[..payload.len().min(4096)].to_vec()
    };
    Ok(DecodedEnvelope::V2(WireEnvelopeV2::new(
        StableId::new("schema.managed-fuzz.v1")?,
        StableId::new(producer)?,
        Generation::new(1)?,
        payload,
    )?))
}
