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
mod frame_header;
mod registry;
mod schema;
mod secure_session;
mod session;
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
pub use frame_header::FrameHeader;
pub use frame_header::FrameHeaderParseError;
pub use frame_header::FrameHeaderValidationError;
pub use frame_header::HeaderIdentityField;
pub use frame_header::MAX_WIRE_FRAME_BYTES;
pub use frame_header::MAX_WIRE_IDENTITY_BYTES;
pub use frame_header::ValidatedFrameHeader;
pub use frame_header::WIRE_HEADER_BYTES;
pub use frame_header::WIRE_MAGIC;
pub use registry::FrozenAdmissionError;
pub use registry::FrozenSchemaRegistry;
pub use registry::FrozenSchemaRegistryBuilder;
pub use registry::MAX_FROZEN_SCHEMA_ENTRIES;
pub use registry::MAX_POLICY_SUBJECTS;
pub use registry::RegistryBuildError;
pub use registry::SchemaPolicy;
pub use schema::PayloadCodec;
pub use schema::SchemaAdmissionError;
pub use schema::SchemaCodecError;
pub use schema::SchemaDescriptor;
pub use schema::SchemaRegistry;
pub use schema::decode_typed;
pub use schema::encode_typed;
pub use secure_session::AuthenticatedSessionError;
pub use secure_session::AuthenticatedWireSession;
pub use secure_session::MAX_AUTHENTICATED_RECORD_BYTES;
pub use secure_session::MAX_CHANNEL_BINDING_BYTES;
pub use secure_session::MIN_CHANNEL_BINDING_BYTES;
pub use secure_session::NegotiationTranscript;
pub use secure_session::SessionErrorContext;
pub use secure_session::SessionMacKey;
pub use secure_session::WireSession;
pub use secure_session::WireSessionError;
pub use session::NegotiatedDecodeBatch;
pub use session::NegotiatedDecodeError;
pub use session::NegotiatedStreamingDecoder;
pub use session::WireSessionDecodeBatch;
pub use session::WireSessionDecodeError;
pub use session::WireSessionDecoder;
pub use stream::MAX_BUFFERED_WIRE_FRAMES;
pub use stream::MAX_WIRE_FRAMES_PER_FEED;
pub use stream::ReadFrameError;
pub use stream::StreamDecodeBatch;
pub use stream::StreamDecodeError;
pub use stream::StreamingDecoder;
pub use stream::read_frame;
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
