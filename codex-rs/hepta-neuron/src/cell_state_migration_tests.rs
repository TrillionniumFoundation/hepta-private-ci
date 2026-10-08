use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn child() -> CellStateSplitChildV1 {
    let mut value = CellStateSplitChildV1 {
        parent_cell_id: id("cell.parent"),
        child_cell_id: id("cell.child"),
        child_scope: Digest32::of_bytes(b"scope"),
        parent_generation: Generation::new(1).expect("generation"),
        candidate_generation: Generation::new(2).expect("generation"),
        parent_checkpoint_digest: Digest32::of_bytes(b"parent-checkpoint"),
        parent_config_digest: Digest32::of_bytes(b"config"),
        parent_scope: Digest32::of_bytes(b"parent-scope"),
        objective_digest: Digest32::of_bytes(b"objective"),
        body_digest: Digest32::of_bytes(b"body"),
        sequence: 7,
        temporal_q24: vec![1, 2],
        activation_q24: vec![3, 4],
        activity_q24: vec![5, 6],
        threshold_q24: vec![7, 8],
        eligibility_q24: vec![9, 10],
        state_digest: Digest32::ZERO,
    };
    value.state_digest = Digest32::of_bytes(b"state");
    value
}

#[test]
fn child_state_encoding_is_deterministic_and_payload_bound() {
    let value = child();
    let first = encode_cell_state_v1(&value);
    let second = CellStateMigrationV1::encode_child_state(&value);
    assert_eq!(first, second);
    assert_eq!(
        CellStateMigrationV1::child_payload_digest(&value),
        Digest32::of_bytes(&first)
    );
}

#[test]
fn cas_receipt_digest_binds_parent_anchor_and_fence() {
    let anchor = JournalAnchor {
        sequence: 7,
        checkpoint_digest: Digest32::of_bytes(b"parent-checkpoint"),
    };
    let mut receipt = CellStateCasReceiptV1 {
        operation_id: id("split-operation"),
        child_cell_id: id("cell.child"),
        parent_anchor: anchor,
        payload_digest: Digest32::of_bytes(b"payload"),
        encoded_size_bytes: 11,
        fence_digest: Digest32::of_bytes(b"fence"),
        receipt_digest: Digest32::ZERO,
    };
    receipt.receipt_digest = receipt.content_digest();
    let original = receipt.receipt_digest;
    receipt.parent_anchor.sequence = 8;
    assert_ne!(original, receipt.content_digest());
}
