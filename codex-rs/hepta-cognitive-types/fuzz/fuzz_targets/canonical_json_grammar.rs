#![no_main]

mod support;

use codex_hepta_cognitive_types::hnmf::{
    CrossModalBindingV1, MemoryEventV1, ModalitySpanRefV1,
};
use codex_hepta_cognitive_types::hnmf_learning::{
    EngramNodeV1, ForgetPropagationReceiptV1, MemoryCueV1, OutcomeSignalV1,
    PlasticityBatchV1, RecallPacketV1, ReplaySelectionReceiptV1, SynapseV1,
    TopologyProposalV1,
};
use codex_hepta_cognitive_types::shared_experience::{
    SharedExperiencePublicationV2, SharedExperienceRevocationReceiptV2,
    SharedExperienceSnapshotV2, SharedExperienceUseReceiptV2,
};
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    support::exercise::<ModalitySpanRefV1>(data);
    support::exercise::<MemoryEventV1>(data);
    support::exercise::<CrossModalBindingV1>(data);
    support::exercise::<EngramNodeV1>(data);
    support::exercise::<SynapseV1>(data);
    support::exercise::<MemoryCueV1>(data);
    support::exercise::<RecallPacketV1>(data);
    support::exercise::<OutcomeSignalV1>(data);
    support::exercise::<ReplaySelectionReceiptV1>(data);
    support::exercise::<PlasticityBatchV1>(data);
    support::exercise::<TopologyProposalV1>(data);
    support::exercise::<ForgetPropagationReceiptV1>(data);
    support::exercise::<SharedExperiencePublicationV2>(data);
    support::exercise::<SharedExperienceSnapshotV2>(data);
    support::exercise::<SharedExperienceUseReceiptV2>(data);
    support::exercise::<SharedExperienceRevocationReceiptV2>(data);
});
