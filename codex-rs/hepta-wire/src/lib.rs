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
mod platform_manifest_json;
mod platform_types_json;
mod schema;
mod stream;
mod strict_json;
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
pub use platform_manifest_json::MAX_CANONICAL_I64_DECIMAL_BYTES_V1;
pub use platform_manifest_json::PlatformManifestWireError;
pub use platform_manifest_json::decode_external_system_manifest_v1_json;
pub use platform_manifest_json::decode_random_stream_manifest_v1_json;
pub use platform_manifest_json::decode_sensor_calibration_manifest_v1_json;
pub use platform_manifest_json::encode_external_system_manifest_v1_json;
pub use platform_manifest_json::encode_random_stream_manifest_v1_json;
pub use platform_manifest_json::encode_sensor_calibration_manifest_v1_json;
pub use platform_types_json::MAX_CANONICAL_U64_DECIMAL_BYTES_V1;
pub use platform_types_json::MAX_PLATFORM_TYPES_JSON_BYTES_V1;
pub use platform_types_json::MAX_PLATFORM_TYPES_JSON_DEPTH_V1;
pub use platform_types_json::PlatformTypesWireError;
pub use platform_types_json::ValidatedRuntimeTopologyCandidateV1;
pub use platform_types_json::decode_prompt_delivery_v2_json;
pub use platform_types_json::decode_runtime_topology_candidate_v1_json;
pub use platform_types_json::encode_prompt_delivery_v2_json;
pub use platform_types_json::encode_runtime_topology_candidate_v1_json;
pub use schema::PayloadCodec;
pub use schema::SchemaAdmissionError;
pub use schema::SchemaCodecError;
pub use schema::SchemaDescriptor;
pub use schema::SchemaRegistry;
pub use schema::decode_typed;
pub use schema::encode_typed;
pub use stream::MAX_BUFFERED_WIRE_FRAMES;
pub use stream::MAX_WIRE_FRAME_BYTES;
pub use stream::ReadFrameError;
pub use stream::StreamDecodeError;
pub use stream::StreamingDecoder;
pub use stream::WIRE_HEADER_BYTES;
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
