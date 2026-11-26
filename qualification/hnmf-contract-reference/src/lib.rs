#![forbid(unsafe_code)]

//! Qualification shim for the canonical cognitive contract owner.
//!
//! Contract structure is intentionally NOT redefined in this package. The
//! single canonical Rust source is `codex-rs/hepta-cognitive-types`; this
//! qualification crate exists only to make the ownership boundary executable
//! and to fail if somebody tries to turn the reference package into a second
//! authority or contract spine.

pub use codex_hepta_cognitive_types::hnmf::CrossModalBindingV1;
pub use codex_hepta_cognitive_types::hnmf::MemoryEventV1;
pub use codex_hepta_cognitive_types::hnmf::ModalitySpanRefV1;
pub use codex_hepta_cognitive_types::hnmf_learning::EngramNodeV1;
pub use codex_hepta_cognitive_types::hnmf_learning::ForgetPropagationReceiptV1;
pub use codex_hepta_cognitive_types::hnmf_learning::MemoryCueV1;
pub use codex_hepta_cognitive_types::hnmf_learning::OutcomeSignalV1;
pub use codex_hepta_cognitive_types::hnmf_learning::PlasticityBatchV1;
pub use codex_hepta_cognitive_types::hnmf_learning::RecallPacketV1;
pub use codex_hepta_cognitive_types::hnmf_learning::ReplaySelectionReceiptV1;
pub use codex_hepta_cognitive_types::hnmf_learning::SynapseV1;
pub use codex_hepta_cognitive_types::hnmf_learning::TopologyProposalV1;
pub use codex_hepta_cognitive_types::wire::canonical_contract_digest_v1;
pub use codex_hepta_cognitive_types::wire::decode_wire_v1;
pub use codex_hepta_cognitive_types::wire::encode_wire_v1;

pub const CANONICAL_CRATE_PATH: &str = "../../codex-rs/hepta-cognitive-types";
pub const CANONICAL_CONTRACT_MODULES: [&str; 3] =
    ["src/hnmf.rs", "src/hnmf_learning.rs", "src/wire.rs"];

pub const CURRENT_RUN_MUTATION_ALLOWED: bool = false;
pub const ONLINE_TOPOLOGY_ACTIVATION_ALLOWED: bool = false;
pub const PRODUCTION_AUTHORITY: bool = false;
pub const EXTERNAL_EFFECTS_ALLOWED: bool = false;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn qualification_contract_reference_is_non_authoritative() {
        assert_eq!(
            [
                CURRENT_RUN_MUTATION_ALLOWED,
                ONLINE_TOPOLOGY_ACTIVATION_ALLOWED,
                PRODUCTION_AUTHORITY,
                EXTERNAL_EFFECTS_ALLOWED,
            ],
            [false; 4]
        );
        // Actual Rust type identity must remain the canonical owner's identity.
        // Display names, file paths and source declaration spelling are not proof.
        fn same_type<Reference: 'static, Canonical: 'static>() {
            assert_eq!(
                std::any::TypeId::of::<Reference>(),
                std::any::TypeId::of::<Canonical>()
            );
        }
        same_type::<ModalitySpanRefV1, codex_hepta_cognitive_types::hnmf::ModalitySpanRefV1>();
        same_type::<MemoryEventV1, codex_hepta_cognitive_types::hnmf::MemoryEventV1>();
        same_type::<CrossModalBindingV1, codex_hepta_cognitive_types::hnmf::CrossModalBindingV1>();
        same_type::<EngramNodeV1, codex_hepta_cognitive_types::hnmf_learning::EngramNodeV1>();
        same_type::<SynapseV1, codex_hepta_cognitive_types::hnmf_learning::SynapseV1>();
        same_type::<MemoryCueV1, codex_hepta_cognitive_types::hnmf_learning::MemoryCueV1>();
        same_type::<RecallPacketV1, codex_hepta_cognitive_types::hnmf_learning::RecallPacketV1>();
        same_type::<OutcomeSignalV1, codex_hepta_cognitive_types::hnmf_learning::OutcomeSignalV1>();
        same_type::<
            ReplaySelectionReceiptV1,
            codex_hepta_cognitive_types::hnmf_learning::ReplaySelectionReceiptV1,
        >();
        same_type::<PlasticityBatchV1, codex_hepta_cognitive_types::hnmf_learning::PlasticityBatchV1>(
        );
        same_type::<
            TopologyProposalV1,
            codex_hepta_cognitive_types::hnmf_learning::TopologyProposalV1,
        >();
        same_type::<
            ForgetPropagationReceiptV1,
            codex_hepta_cognitive_types::hnmf_learning::ForgetPropagationReceiptV1,
        >();
    }
}
