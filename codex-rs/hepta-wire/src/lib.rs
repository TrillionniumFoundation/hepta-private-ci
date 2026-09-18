//! Deterministic local wire envelopes for Hepta module ports.
//!
//! The format is deliberately small, length-delimited and strict. It does not
//! transport authority: consumers must validate an independently issued grant
//! at the effect boundary.

#![forbid(unsafe_code)]

mod envelope;
mod envelope_v2;
mod framed;
mod version;

pub use envelope::MAX_WIRE_PAYLOAD_BYTES;
pub use envelope::WireEnvelope;
pub use envelope::WireError;
pub use envelope_v2::WireEnvelopeV2;
pub use envelope_v2::WireV2Error;
pub use framed::DecodedEnvelope;
pub use framed::EnvelopeDecodeError;
pub use framed::MAX_WIRE_FRAME_BYTES;
pub use framed::MAX_WIRE_ID_BYTES;
pub use framed::StreamDecodeError;
pub use framed::WIRE_HEADER_BYTES;
pub use framed::decode_envelope;
pub use framed::read_envelope;
pub use version::MAX_NEGOTIATION_VERSIONS;
pub use version::MAX_REQUIRED_CAPABILITIES;
pub use version::NegotiatedVersion;
pub use version::NegotiationError;
pub use version::WireCapability;
pub use version::WireVersion;
pub use version::negotiate;

#[cfg(test)]
#[path = "property_tests.rs"]
mod property_tests;
