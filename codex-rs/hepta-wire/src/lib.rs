//! Deterministic, bounded wire envelopes and protocol admission for Hepta module ports.
//!
//! HPTA V1 remains byte-for-byte immutable. HPTA V2 adds a domain-separated digest
//! over protocol metadata and payload. Negotiation, schema admission, typed payload
//! codecs and incremental framing remain transport-neutral and carry no authority.

#![forbid(unsafe_code)]

mod envelope;
mod negotiation;
mod schema;
mod stream;
mod v2;

pub use envelope::MAX_WIRE_PAYLOAD_BYTES;
pub use envelope::WireEnvelope;
pub use envelope::WireError;
pub use negotiation::NegotiatedWire;
pub use negotiation::NegotiationError;
pub use negotiation::WireFeature;
pub use negotiation::WireOffer;
pub use negotiation::WireVersion;
pub use negotiation::negotiate;
pub use schema::AdmittedPayload;
pub use schema::MAX_REGISTERED_WIRE_SCHEMAS;
pub use schema::SchemaAdmissionError;
pub use schema::SchemaRegistry;
pub use schema::SchemaRule;
pub use schema::SchemaValidationError;
pub use schema::TypedCodecError;
pub use schema::TypedPayload;
pub use schema::decode_typed_v1;
pub use schema::decode_typed_v2;
pub use schema::encode_typed_v1;
pub use schema::encode_typed_v2;
pub use stream::DecodedEnvelope;
pub use stream::MAX_WIRE_FRAME_BYTES;
pub use stream::StreamDecodeError;
pub use stream::StreamProgress;
pub use stream::WireStreamDecoder;
pub use v2::WireEnvelopeV2;
pub use v2::WireV2Error;

#[cfg(test)]
#[path = "property_tests.rs"]
mod property_tests;
