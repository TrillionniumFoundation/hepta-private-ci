//! Deterministic local wire envelopes for Hepta module ports.
//!
//! V1 remains an immutable payload-digest framing contract. V2 adds a
//! metadata-bound frame digest, explicit version/capability negotiation,
//! schema admission and bounded incremental decoding. None of these values
//! transport authority: consumers must validate an independently issued grant
//! at the effect boundary.
//!
//! Production callers enter through [`HardenedManagedWireSession`] and may
//! convert that unique owner into a [`HardenedRecordStream`]. That path combines
//! direction-separated authentication, terminal lifecycle ownership, frozen
//! registry admission, exact codec binding, canonical re-encoding and bounded
//! streaming. Raw authenticated owners remain available only to tests and the
//! `protocol-tooling` compatibility feature; they are not exported by a
//! production-only build.

#![forbid(unsafe_code)]

mod authentication;
mod bounded_read;
mod codec_binding;
mod directional_session;
mod envelope;
mod envelope_v2;
mod feed;
mod frame;
mod frame_header;
mod hardened_managed_session;
mod hardened_record_stream;
mod hardened_session;
mod managed_session;
mod record_stream;
mod registry;
mod schema;
mod secure_session;
mod session;
mod stream;
mod version;

pub use bounded_read::ReadFrameBudget;
pub use bounded_read::ReadFrameBudgetExceeded;
pub use bounded_read::read_frame;
pub use bounded_read::read_frame_with_budget;
pub use codec_binding::BoundPayloadCodec;
pub use codec_binding::BoundWireSessionError;
pub use codec_binding::CodecBindingError;
pub use codec_binding::PayloadCodecBinding;
pub use codec_binding::verify_codec_binding;
#[cfg(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
))]
pub use directional_session::AuthenticatedWireSession;
#[cfg(not(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
)))]
pub(crate) use directional_session::AuthenticatedWireSession;
pub use directional_session::SessionEndpoint;
pub use directional_session::SessionMacKey;
pub use envelope::MAX_WIRE_PAYLOAD_BYTES;
pub use envelope::WireEnvelope;
pub use envelope::WireError;
pub use envelope_v2::WIRE_V2_VERSION;
pub use envelope_v2::WireEnvelopeV2;
pub use envelope_v2::WireV2Error;
pub use feed::DecodeFeed;
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
pub use hardened_managed_session::HardenedManagedSessionError;
pub use hardened_managed_session::HardenedManagedWireSession;
pub use hardened_record_stream::HardenedRecordStream;
pub use hardened_record_stream::HardenedRecordStreamBatch;
pub use hardened_record_stream::HardenedRecordStreamBudget;
pub use hardened_record_stream::HardenedRecordStreamError;
#[cfg(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
))]
pub use hardened_session::HardenedWireSession;
pub use hardened_session::HardenedWireSessionError;
pub use hardened_session::WireSessionMetadata;
#[cfg(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
))]
pub use managed_session::ManagedAuthenticatedWireSession;
#[cfg(not(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
)))]
pub(crate) use managed_session::ManagedAuthenticatedWireSession;
#[cfg(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
))]
pub use managed_session::ManagedSessionError;
#[cfg(not(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
)))]
pub(crate) use managed_session::ManagedSessionError;
pub use managed_session::SessionLifecycleState;
#[cfg(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
))]
pub use record_stream::ManagedRecordStream;
#[cfg(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
))]
pub use record_stream::RecordStreamBatch;
#[cfg(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
))]
pub use record_stream::RecordStreamBudget;
#[cfg(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
))]
pub use record_stream::RecordStreamError;
pub use record_stream::RecordStreamLimits;
pub use registry::CanonicalizationProfile;
pub use registry::FrozenAdmissionError;
pub use registry::FrozenSchemaRegistry;
pub use registry::FrozenSchemaRegistryBuilder;
pub use registry::GenerationPolicy;
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
pub use secure_session::MAX_AUTHENTICATED_RECORD_BYTES;
pub use secure_session::MAX_CHANNEL_BINDING_BYTES;
pub use secure_session::MIN_CHANNEL_BINDING_BYTES;
#[cfg(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
))]
pub use secure_session::NegotiationTranscript;
#[cfg(not(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
)))]
pub(crate) use secure_session::NegotiationTranscript;
pub use secure_session::SessionErrorContext;
#[cfg(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
))]
pub use secure_session::WireSession;
#[cfg(not(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
)))]
pub(crate) use secure_session::WireSession;
#[cfg(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
))]
pub use secure_session::WireSession as NegotiatedSession;
pub use secure_session::WireSessionError;
pub use session::NegotiatedDecodeBatch;
pub use session::NegotiatedDecodeError;
pub use session::NegotiatedStreamingDecoder;
#[cfg(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
))]
pub use session::WireSessionDecodeBatch;
#[cfg(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
))]
pub use session::WireSessionDecodeError;
#[cfg(any(
    test,
    all(feature = "protocol-tooling", not(feature = "production"))
))]
pub use session::WireSessionDecoder;
pub use stream::MAX_BUFFERED_WIRE_FRAMES;
pub use stream::MAX_WIRE_FRAMES_PER_FEED;
pub use stream::ReadFrameError;
pub use stream::StreamDecodeBatch;
pub use stream::StreamDecodeError;
pub use stream::StreamingDecoder;
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
