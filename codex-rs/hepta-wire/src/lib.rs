//! Deterministic local wire envelopes for Hepta module ports.
//!
//! The format is deliberately small, length-delimited and strict. It does not
//! transport authority: consumers must validate an independently issued grant
//! at the effect boundary.

#![forbid(unsafe_code)]

mod envelope;
mod envelope_v2;
mod version;

pub use envelope::MAX_WIRE_PAYLOAD_BYTES;
pub use envelope::WireEnvelope;
pub use envelope::WireError;
pub use envelope_v2::WireEnvelopeV2;
pub use envelope_v2::WireV2Error;
pub use version::MAX_NEGOTIATION_VERSIONS;
pub use version::MAX_REQUIRED_CAPABILITIES;
pub use version::NegotiatedVersion;
pub use version::NegotiationError;
pub use version::WireCapability;
pub use version::WireVersion;
pub use version::negotiate;
