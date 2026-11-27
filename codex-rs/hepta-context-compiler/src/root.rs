//! Source-aware context compiler.
//!
//! The compatibility API remains available at the crate root. The
//! provider_bound module exposes its distinct canonical-bundle contract;
//! names unique to that contract are also re-exported here.

#![forbid(unsafe_code)]

#[path = "lib.rs"]
mod compatibility;

pub use compatibility::*;

pub mod provider_bound;

pub use provider_bound::CanonicalContextBundleV2;
pub use provider_bound::CanonicalContextFramingV2;
pub use provider_bound::CanonicalContextSerializerV2;
pub use provider_bound::MAX_TOKENIZER_VERSION_BYTES_V2;
pub use provider_bound::ProviderBoundErrorV2;
pub use provider_bound::ProviderTokenizerDescriptorV2;
pub use provider_bound::observe_provider_bound_delivery_v2;
pub use provider_bound::prepare_delivery_with_successor_v2;
pub use provider_bound::tokenize_provider_final_request_v2;
