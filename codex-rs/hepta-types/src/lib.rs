//! Stable, authority-free primitives shared by Hepta modules.
//!
//! These values carry identity, bounds, generations and deterministic numeric
//! representations. They deliberately contain no runtime handle, credential,
//! ambient authority or product writer.

#![forbid(unsafe_code)]

mod bounded;
mod digest;
mod fixed;
mod identity;
mod numeric_conversion;
mod numeric_profile;

pub use bounded::BoundedBytes;
pub use bounded::BoundedText;
pub use bounded::BoundedValueError;
pub use digest::Digest32;
pub use digest::DigestParseError;
pub use fixed::FixedQ32;
pub use fixed::FixedQ32Error;
pub use fixed::ProbabilityQ32;
pub use identity::AuthorityPosture;
pub use identity::Generation;
pub use identity::LogicalSequence;
pub use identity::Revision;
pub use identity::StableId;
pub use numeric_conversion::NumericConversionReceiptV1;
pub use numeric_conversion::NumericErrorBoundV1;
pub use numeric_conversion::NumericSignalV1;
pub use numeric_conversion::rescale_signal;
pub use numeric_profile::NumericConversionError;
pub use numeric_profile::NumericProfileV1;
pub use numeric_profile::NumericRoundingV1;
pub use numeric_profile::NumericSignalSchemaV1;
pub use numeric_profile::SignalUnitV1;
