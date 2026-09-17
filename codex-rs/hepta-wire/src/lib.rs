//! Deterministic wire envelopes and protocol admission for Hepta module ports.
//!
//! HPTA V1 remains an immutable compatibility codec. HPTA V2 adds full-frame
//! integrity coverage. Version/capability negotiation, schema admission and
//! incremental decoding are separate layers so unknown versions and schemas
//! continue to fail closed. The wire layer never transports authority:
//! consumers must validate an independently issued grant at the effect boundary.

#![forbid(unsafe_code)]

mod envelope;
mod negotiation;
mod schema;
mod stream;
mod v2;

pub use envelope::MAX_WIRE_PAYLOAD_BYTES;
pub use envelope::WireEnvelope;
pub use envelope::WireError;
pub use negotiation::CapabilitySet;
pub use negotiation::NegotiatedWire;
pub use negotiation::NegotiationError;
pub use negotiation::NegotiationOffer;
pub use negotiation::VersionOffer;
pub use negotiation::WireVersion;
pub use negotiation::negotiate;
pub use schema::PayloadCodecError;
pub use schema::SchemaError;
pub use schema::SchemaRegistry;
pub use schema::SchemaValidator;
pub use schema::WirePayload;
pub use stream::DecodeProgress;
pub use stream::DecodedFrame;
pub use stream::FrameDecodeError;
pub use stream::MAX_WIRE_FRAME_BYTES;
pub use stream::WireFrameDecoder;
pub use v2::V2_WIRE_VERSION;
pub use v2::WireEnvelopeV2;
pub use v2::WireV2Error;

#[cfg(test)]
mod property_tests;
