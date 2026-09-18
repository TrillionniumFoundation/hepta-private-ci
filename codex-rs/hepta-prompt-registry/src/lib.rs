//! Governed prompt-factor and realization registry.
//!
//! The registry owns bounded semantic factors, model-specific realizations,
//! admission lineage, immutable lifecycle history, and content-addressed prompt
//! payloads. Admission is fail-closed unless an independently verified
//! `VerifiedUseToken` is consumed. Durable hosting lives in [`DurablePromptRegistry`].

#![forbid(unsafe_code)]

mod model;
mod protocol;
mod registry;
mod registry_integrity;
mod registry_mutation;
mod store;
mod v2;

pub use model::AdmissionRequest;
pub use model::Error;
pub use model::FactorAdmissionRecord;
pub use model::FactorSource;
pub use model::Lifecycle;
pub use model::LifecycleEvent;
pub use model::LifecycleEventKind;
pub use model::MutationDisposition;
pub use model::PromptFactor;
pub use model::PromptRealization;
pub use model::RegistryReceipt;
pub use protocol::PromptFactorV1;
pub use protocol::PromptProtocolError;
pub use protocol::PromptRealizationV1;
pub use protocol::decode_prompt_factor_v1;
pub use protocol::decode_prompt_realization_v1;
pub use protocol::encode_prompt_factor_v1;
pub use protocol::encode_prompt_realization_v1;
pub(crate) use registry::MAX_RECORDS;
pub use registry::PromptRegistry;
pub use store::DurablePromptRegistry;
pub use store::PromptRegistryStoreError;
pub use v2::CompatibleRealizationSetV2;
pub use v2::MAX_COMPATIBLE_REALIZATIONS_V2;
pub use v2::MAX_REALIZATION_PAYLOAD_BYTES;
pub use v2::MAX_TOTAL_REALIZATION_PAYLOAD_BYTES;
pub use v2::PromptModelTupleV2;
pub use v2::PromptPayloadResolutionV2;
pub use v2::PromptRealizationBindingV2;
pub use v2::PromptRegistrySnapshotV2;
pub use v2::PromptRegistryV2Error;
pub use v2::PromptRoleV2;

#[cfg(test)]
mod test_support;

#[cfg(test)]
#[path = "integration_tests.rs"]
mod integration_tests;

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
