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
mod numeric_conversion;
mod numeric_profile;
mod registry;

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
pub use digest::Digest32;
pub use digest::DigestParseError;
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
pub use identity::Revision;
pub use identity::StableId;
pub use identity::validate_id;
pub use numeric_conversion::NumericConversionReceiptV1;
pub use numeric_conversion::NumericErrorBoundV1;
pub use numeric_conversion::NumericSignalV1;
pub use numeric_conversion::rescale_signal;
pub use numeric_conversion::rescale_signal_registered;
pub use numeric_profile::NumericConversionError;
pub use numeric_profile::NumericProfileV1;
pub use numeric_profile::NumericRoundingV1;
pub use numeric_profile::NumericSignalSchemaV1;
pub use numeric_profile::SignalUnitV1;
pub use registry::ContractRegistryV1;
pub use registry::MAX_REGISTRY_DEFINITION_BYTES_V1;
pub use registry::MAX_REGISTRY_ENTRIES_V1;
pub use registry::RegistryDefinitionV1;
pub use registry::RegistryError;
pub use registry::RegistryKindV1;
