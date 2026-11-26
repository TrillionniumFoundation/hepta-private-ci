use super::*;

fn id(value: &str) -> codex_hepta_types::StableId {
    codex_hepta_types::StableId::new(value).expect("id")
}

fn digest(seed: u8) -> codex_hepta_types::Digest32 {
    codex_hepta_types::Digest32::from_array([seed; 32])
}

#[test]
fn canary_receipt_binds_dispatch_fence_generation_and_rollback() {
    let receipt = CellSplitCanaryReceiptV1::new(
        id("split.1"),
        codex_hepta_types::Generation::new(8).expect("generation"),
        digest(1),
        digest(2),
        digest(3),
        10,
        0,
        true,
    )
    .expect("receipt");
    receipt.verify_digest().expect("digest");
    let mut tampered = receipt;
    tampered.observed_requests = 11;
    assert_eq!(
        tampered.verify_digest(),
        Err(CellSplitLifecycleErrorV1::Digest)
    );
}

#[test]
fn canary_rejects_failed_count_above_observed() {
    assert_eq!(
        CellSplitCanaryReceiptV1::new(
            id("split.2"),
            codex_hepta_types::Generation::new(2).expect("generation"),
            digest(1),
            digest(2),
            digest(3),
            1,
            2,
            false,
        ),
        Err(CellSplitLifecycleErrorV1::InvalidEvidence)
    );
}
