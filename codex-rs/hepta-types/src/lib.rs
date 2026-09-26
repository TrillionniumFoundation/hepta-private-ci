//! Stable, authority-free primitives shared by Hepta modules.
//!
//! These values carry identity, bounds, generations and deterministic numeric
//! representations. They deliberately contain no runtime handle, credential,
//! ambient authority or product writer.

#![forbid(unsafe_code)]

mod bounded;
mod canonical_digest;
mod digest;
mod fixed;
mod identity;
mod manifests;
mod numeric_conversion;
mod numeric_profile;
mod prompt_delivery;
mod registry;
mod topology;

pub use bounded::BoundedBytes;
pub use bounded::BoundedText;
pub use bounded::BoundedValueError;
pub use canonical_digest::CanonicalDigestError;
pub use canonical_digest::CanonicalFieldV1;
pub use canonical_digest::CanonicalMapEntryV1;
pub use canonical_digest::CanonicalValueV1;
pub use canonical_digest::MAX_CANONICAL_BYTES_V1;
pub use canonical_digest::MAX_CANONICAL_CONTAINER_ITEMS_V1;
pub use canonical_digest::MAX_CANONICAL_DEPTH_V1;
pub use canonical_digest::canonical_digest_v1;
pub use canonical_digest::canonical_encode_v1;
pub use canonical_digest::canonical_validate_v1;
pub use digest::Digest32;
pub use digest::DigestParseError;
pub use fixed::FIXED_Q32_ARITHMETIC_PROFILE_V1;
pub use fixed::FixedQ32;
pub use fixed::FixedQ32Error;
pub use fixed::ProbabilityQ32;
pub use identity::AuthorityFlagsV1;
pub use identity::AuthorityPosture;
pub use identity::AuthorityPostureError;
pub use identity::Generation;
pub use identity::IdNamespaceV1;
pub use identity::IdProfileV1;
pub use identity::IdentityError;
pub use identity::LogicalSequence;
pub use identity::NonAuthorizingPosture;
pub use identity::Revision;
pub use identity::StableId;
pub use identity::validate_id;
pub use manifests::ExternalSystemClassV1;
pub use manifests::ExternalSystemManifestV1;
pub use manifests::MAX_CLOCK_DOMAIN_BYTES_V1;
pub use manifests::MAX_CONFIDENCE_PPM_V1;
pub use manifests::MAX_MANIFEST_ENUM_BYTES_V1;
pub use manifests::MAX_MANIFEST_TIMESTAMP_BYTES_V1;
pub use manifests::MAX_MANIFEST_VERSION_BYTES_V1;
pub use manifests::MAX_OPERATING_UNIT_BYTES_V1;
pub use manifests::ManifestContractErrorV1;
pub use manifests::RandomStreamManifestV1;
pub use manifests::SensorCalibrationManifestV1;
pub use manifests::SensorClassV1;
pub use manifests::SensorFailurePolicyV1;
pub use manifests::SensorOperatingRangeV1;
pub use manifests::SensorUncertaintyProfileV1;
pub use manifests::UncertaintyDistributionV1;
pub use manifests::UtcTimestampV1;
pub use numeric_conversion::NumericConversionReceiptV1;
pub use numeric_conversion::NumericErrorBoundV1;
pub use numeric_conversion::NumericSignalV1;
pub use numeric_conversion::RegisteredNumericConversionReceiptV1;
pub use numeric_conversion::rescale_signal;
pub use numeric_conversion::rescale_signal_registered;
pub use numeric_profile::NUMERIC_PROFILE_DEFINITION_VERSION_V1;
pub use numeric_profile::NumericConversionError;
pub use numeric_profile::NumericProfileDefinitionError;
pub use numeric_profile::NumericProfileDefinitionV1;
pub use numeric_profile::NumericProfileV1;
pub use numeric_profile::NumericRoundingV1;
pub use numeric_profile::NumericSignalSchemaV1;
pub use numeric_profile::SignalUnitV1;
pub use prompt_delivery::MAX_PROMPT_REJECTION_REASON_BYTES_V1;
pub use prompt_delivery::MAX_PROMPT_TOKEN_POSITIONS_V1;
pub use prompt_delivery::PromptDeliveryErrorV1;
pub use prompt_delivery::PromptDeliveryObservationV1;
pub use prompt_delivery::PromptDeliveryRejectReasonV1;
pub use registry::ContractRegistryV1;
pub use registry::MAX_REGISTRY_AGGREGATE_DEFINITION_BYTES_V1;
pub use registry::MAX_REGISTRY_DEFINITION_BYTES_V1;
pub use registry::MAX_REGISTRY_ENTRIES_V1;
pub use registry::RegistryDefinitionV1;
pub use registry::RegistryError;
pub use registry::RegistryKindV1;

pub use topology::RuntimeTopologyCandidateV1;
pub use topology::RuntimeTopologyContractErrorV1;
pub use topology::RuntimeTopologyDeltaV1;
pub use topology::RuntimeTopologyOperationV1;
