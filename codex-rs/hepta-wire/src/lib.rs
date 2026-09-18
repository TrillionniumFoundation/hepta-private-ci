//! Deterministic wire formats and protocol serialization for Hepta module ports.
//!
//! V1 remains the immutable payload-digest-only compatibility format. V2 adds
//! full semantic frame integrity. Negotiation, schema admission, typed payload
//! codecs and bounded stream readers are transport-neutral library surfaces;
//! none of them transport authority or imply effect acknowledgement.

#![forbid(unsafe_code)]

mod envelope;
mod negotiation;
mod protocol;
mod schema;
mod stream;
mod v2;

pub use envelope::MAX_WIRE_PAYLOAD_BYTES;
pub use envelope::WIRE_VERSION_V1;
pub use envelope::WireEnvelope;
pub use envelope::WireError;
pub use negotiation::NegotiatedWire;
pub use negotiation::NegotiationError;
pub use negotiation::WireCapability;
pub use negotiation::WireVersion;
pub use negotiation::negotiate;
pub use protocol::EnvelopeView;
pub use protocol::WireFrame;
pub use schema::AdmittedPayload;
pub use schema::PayloadCodec;
pub use schema::PayloadCodecError;
pub use schema::SchemaAdmissionError;
pub use schema::SchemaDefinition;
pub use schema::SchemaRegistrationError;
pub use schema::SchemaRegistry;
pub use schema::SchemaValidationError;
pub use schema::SchemaValidator;
pub use schema::TypedEncodeError;
pub use schema::TypedPayloadError;
pub use schema::encode_typed_v2;
pub use stream::MAX_STREAM_BUFFER_BYTES;
pub use stream::MAX_WIRE_FRAME_BYTES;
pub use stream::StreamDecodeError;
pub use stream::WireReadError;
pub use stream::WireStreamDecoder;
pub use stream::read_frame;
pub use stream::read_frame_for;
pub use v2::WIRE_VERSION_V2;
pub use v2::WireEnvelopeV2;
