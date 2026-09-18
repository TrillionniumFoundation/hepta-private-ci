//! Deterministic, bounded wire envelopes and protocol admission for Hepta module ports.
//!
//! HPTA V1 remains byte-frozen and uses a payload-only fault-detection digest.
//! HPTA V2 adds a complete-frame digest that binds schema, producer, generation
//! and payload. Neither version transports authority: consumers must validate an
//! independently issued grant at the effect boundary.
//!
//! Version negotiation, schema admission and stream framing are separate layers
//! so a decoder never silently reinterprets an unknown version or domain payload.

#![forbid(unsafe_code)]

mod envelope;
mod integrity;
mod negotiation;
mod schema;
mod stream;

pub use envelope::MAX_WIRE_PAYLOAD_BYTES;
pub use envelope::WireEnvelope;
pub use envelope::WireError;
pub use integrity::FRAME_V2_DIGEST_DOMAIN;
pub use integrity::HPTA_V1;
pub use integrity::HPTA_V2;
pub use integrity::WireEnvelopeV2;
pub use integrity::WireFrame;
pub use integrity::complete_frame_digest;
pub use negotiation::NegotiatedWire;
pub use negotiation::NegotiationError;
pub use negotiation::NegotiationPolicy;
pub use negotiation::WireFeature;
pub use negotiation::WireOffer;
pub use negotiation::WireVersion;
pub use negotiation::negotiate;
pub use schema::PayloadCodec;
pub use schema::SchemaAdmission;
pub use schema::SchemaError;
pub use schema::SchemaRegistry;
pub use schema::StaticSchemaAdmission;
pub use stream::StreamWireError;
pub use stream::read_frame;

#[cfg(test)]
mod protocol_tests;
