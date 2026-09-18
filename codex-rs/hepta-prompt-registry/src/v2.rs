//! Exact-profile prompt realization registry views and payload resolution.

#[path = "v2_registry.rs"]
mod registry_impl;
#[path = "v2_types.rs"]
mod types;

pub(crate) use registry_impl::validate_active_uniqueness;
pub use types::CompatibleRealizationSetV2;
pub use types::MAX_COMPATIBLE_REALIZATIONS_V2;
pub use types::MAX_REALIZATION_PAYLOAD_BYTES;
pub use types::MAX_TOTAL_REALIZATION_PAYLOAD_BYTES;
pub use types::PromptModelTupleV2;
pub use types::PromptPayloadResolutionV2;
pub use types::PromptRealizationBindingV2;
pub use types::PromptRegistrySnapshotV2;
pub use types::PromptRegistryV2Error;
pub use types::PromptRoleV2;

#[cfg(test)]
#[path = "v2_tests.rs"]
mod tests;
