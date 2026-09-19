//! Deterministic, bounded wire envelopes and protocol admission for Hepta module ports.
//!
//! HPTA V1 remains byte-for-byte immutable. HPTA V2 adds a complete semantic
//! frame digest that can be bound by an authenticated transport/session.
//! Neither wire version transports authority: consumers must validate an
//! independently issued grant at the effect boundary.

#![forbid(unsafe_code)]

mod envelope;
mod negotiation;
mod schema;
mod stream;
mod v2;

pub use envelope::MAX_WIRE_PAYLOAD_BYTES;
pub use envelope::WireEnvelope;
pub use envelope::WireError;
pub use negotiation::CAP_FRAME_DIGEST_V2;
pub use negotiation::CAP_SCHEMA_ADMISSION_V1;
pub use negotiation::CAP_STREAMING_FRAMES_V1;
pub use negotiation::HPTA_V1;
pub use negotiation::HPTA_V2;
pub use negotiation::NegotiatedProtocol;
pub use negotiation::NegotiationError;
pub use negotiation::capabilities_for;
pub use negotiation::negotiate;
pub use schema::AdmissionError;
pub use schema::AdmittedPayload;
pub use schema::MAX_JSON_NESTING;
pub use schema::MAX_REGISTERED_SCHEMAS;
pub use schema::MAX_SCHEMA_FIELDS;
pub use schema::SchemaDefinition;
pub use schema::SchemaError;
pub use schema::SchemaRegistry;
pub use schema::TypedPayloadError;
pub use schema::TypedWirePayload;
pub use schema::UnknownFieldPolicy;
pub use stream::FramedReader;
pub use stream::FramedWriter;
pub use stream::MAX_WIRE_FRAME_BYTES;
pub use stream::StreamError;
pub use stream::VersionedEnvelope;
pub use v2::HPTA_V2_HEADER_BYTES;
pub use v2::WireEnvelopeV2;
pub use v2::WireV2Error;

#[cfg(test)]
#[path = "protocol_tests.rs"]
mod protocol_tests;
