//! Canonical data identities shared by the actual freeze owner and Root's
//! independent readback. These functions check no authority and open no owner.

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CellQ24PrivateHeadV1;
use crate::CellQ24SgdRuleV1;

pub(crate) fn original_q24_dataset_preparation_identity_v1(
    initial_head: Digest32,
    ledger_binding: Digest32,
    canonical_payload: &[u8],
    effective_weights: Digest32,
    head: CellQ24PrivateHeadV1,
    rule: CellQ24SgdRuleV1,
) -> Digest32 {
    let (tag, index) = match head {
        CellQ24PrivateHeadV1::Drive { index } => (1_u8, index),
        CellQ24PrivateHeadV1::Prediction { index } => (2_u8, index),
    };
    Digest32::of_parts(&[
        b"hepta.agentd.original-q24-dataset-preparation.v1\0",
        initial_head.as_array(),
        ledger_binding.as_array(),
        Digest32::of_bytes(canonical_payload).as_array(),
        effective_weights.as_array(),
        &[tag],
        &index.to_le_bytes(),
        &rule.epochs.to_le_bytes(),
        &rule.learning_rate_q24.to_le_bytes(),
    ])
}

pub(crate) fn original_q24_dataset_freeze_execution_key_v1(
    operation_id: &StableId,
    preparation_identity: Digest32,
    trust_digest: Digest32,
    signer: &TrustedLearningSignerV1,
    maximum_signature_lifetime_seconds: u64,
) -> ProductEvaluationExecutionKeyV1 {
    ProductEvaluationExecutionKeyV1 {
        plan_id: operation_id.clone(),
        binding_digest: Digest32::of_parts(&[
            b"hepta.agentd.original-q24-dataset-freeze-owner.v1\0",
            preparation_identity.as_array(),
            trust_digest.as_array(),
            signer.principal.principal_id.as_str().as_bytes(),
            &signer.verifying_key,
            &maximum_signature_lifetime_seconds.to_be_bytes(),
        ]),
    }
}
