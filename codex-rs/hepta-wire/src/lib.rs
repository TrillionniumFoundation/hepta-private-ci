//! Deterministic local wire envelopes for Hepta module ports.
//!
//! V1 remains an immutable payload-digest framing contract. V2 adds a
//! metadata-bound frame digest, explicit version/capability negotiation,
//! schema admission and bounded incremental decoding. None of these values
//! transport authority: consumers must validate an independently issued grant
//! at the effect boundary.

#![forbid(unsafe_code)]

mod envelope;
mod envelope_v2;
mod frame;
mod schema;
mod stream;
mod version;

pub use envelope::MAX_WIRE_PAYLOAD_BYTES;
pub use envelope::WireEnvelope;
pub use envelope::WireError;
pub use envelope_v2::WIRE_V2_VERSION;
pub use envelope_v2::WireEnvelopeV2;
pub use envelope_v2::WireV2Error;
pub use frame::DecodeFrameError;
pub use frame::DecodedEnvelope;
pub use frame::decode_frame;
pub use schema::PayloadCodec;
pub use schema::SchemaAdmissionError;
pub use schema::SchemaCodecError;
pub use schema::SchemaDescriptor;
pub use schema::SchemaRegistry;
pub use schema::decode_typed;
pub use schema::encode_typed;
pub use stream::MAX_BUFFERED_WIRE_FRAMES;
pub use stream::MAX_WIRE_FRAME_BYTES;
pub use stream::StreamDecodeError;
pub use stream::StreamingDecoder;
pub use stream::WIRE_HEADER_BYTES;
pub use version::MAX_NEGOTIATION_VERSIONS;
pub use version::NegotiatedWire;
pub use version::NegotiationError;
pub use version::NegotiationOffer;
pub use version::WireCapabilities;
pub use version::WireVersion;
pub use version::negotiate;

#[cfg(test)]
#[path = "property_tests.rs"]
mod property_tests;
