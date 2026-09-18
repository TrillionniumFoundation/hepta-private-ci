#![forbid(unsafe_code)]

//! Compatibility façade for historical HNMF qualification callers.
//!
//! Canonical cognitive/memory contracts are owned only by
//! `codex-hepta-cognitive-types::hnmf_v1`. This crate intentionally defines no
//! independent event/span/wire structures.

pub use codex_hepta_cognitive_types::hnmf_v1::AlignmentKindV1 as AlignmentKind;
pub use codex_hepta_cognitive_types::hnmf_v1::AuthorityPostureV1;
pub use codex_hepta_cognitive_types::hnmf_v1::CanonicalJsonV1;
pub use codex_hepta_cognitive_types::hnmf_v1::CrossModalBindingV1 as CrossModalBinding;
pub use codex_hepta_cognitive_types::hnmf_v1::EpisodeIdV1 as EpisodeId;
pub use codex_hepta_cognitive_types::hnmf_v1::EventIdV1 as EventId;
pub use codex_hepta_cognitive_types::hnmf_v1::HnmfContractError as ContractError;
pub use codex_hepta_cognitive_types::hnmf_v1::MemoryEventV1 as MemoryEvent;
pub use codex_hepta_cognitive_types::hnmf_v1::MemoryLifecycleV1 as MemoryLifecycle;
pub use codex_hepta_cognitive_types::hnmf_v1::MemoryScopeV1 as MemoryScope;
pub use codex_hepta_cognitive_types::hnmf_v1::MemoryVerificationStateV1;
pub use codex_hepta_cognitive_types::hnmf_v1::ModalityKindV1 as ModalityKind;
pub use codex_hepta_cognitive_types::hnmf_v1::ModalitySpanRefV1 as ModalitySpanRef;
pub use codex_hepta_cognitive_types::hnmf_v1::PrivacyClassV1 as PrivacyClass;
pub use codex_hepta_cognitive_types::hnmf_v1::ProvenanceRefV1 as ProvenanceRef;
pub use codex_hepta_cognitive_types::hnmf_v1::RetentionPolicyV1;
pub use codex_hepta_cognitive_types::hnmf_v1::Sha256DigestV1 as Digest32;
pub use codex_hepta_cognitive_types::hnmf_v1::SpanIdV1 as SpanId;
pub use codex_hepta_cognitive_types::hnmf_v1::SpanRangeV1 as SpanRange;
pub use codex_hepta_cognitive_types::hnmf_v1::TimeIntervalV1 as TimeInterval;

pub const CURRENT_RUN_MUTATION_ALLOWED: bool = false;
pub const ONLINE_TOPOLOGY_ACTIVATION_ALLOWED: bool = false;
pub const PRODUCTION_AUTHORITY: bool = false;
pub const EXTERNAL_EFFECTS_ALLOWED: bool = false;

#[cfg(test)]
mod tests;
