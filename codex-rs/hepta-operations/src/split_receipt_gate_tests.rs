use super::*;

fn receipt(stage: SplitStageV1) -> SplitStageReceiptV1 {
    SplitStageReceiptV1 {
        operation_id: StableId::new("split:operation:1").expect("id"),
        parent_generation: 4,
        stage,
        receipt_digest: Digest32::of_bytes(format!("{stage:?}").as_bytes()),
    }
}

fn gate() -> SplitReceiptGateV1 {
    SplitReceiptGateV1::new(StableId::new("split:operation:1").expect("id"), 4)
}

#[test]
fn strictly_orders_independently_verified_effects() {
    let mut gate = gate();
    assert_eq!(
        gate.record_verified(&receipt(SplitStageV1::RouteCutover), |_| true),
        Err(SplitReceiptErrorV1::OutOfOrder)
    );
    for stage in [
        SplitStageV1::ArtifactLoaded,
        SplitStageV1::ChildStateCommitted,
        SplitStageV1::ShadowAccepted,
        SplitStageV1::FinalUseAuthorized,
        SplitStageV1::GenerationFenced,
        SplitStageV1::RouteCutover,
    ] {
        gate.record_verified(&receipt(stage), |_| true)
            .expect("verified");
    }
    assert!(gate.completed());
    assert_eq!(gate.next_stage(), None);
}

#[test]
fn rejects_unverified_and_generation_mismatch() {
    let mut gate = gate();
    let first = receipt(SplitStageV1::ArtifactLoaded);
    assert_eq!(
        gate.record_verified(&first, |_| false),
        Err(SplitReceiptErrorV1::InvalidReceipt)
    );
    let mut stale = first.clone();
    stale.parent_generation = 3;
    assert_eq!(
        gate.record_verified(&stale, |_| true),
        Err(SplitReceiptErrorV1::WrongGeneration)
    );
    assert_eq!(gate.next_stage(), Some(SplitStageV1::ArtifactLoaded));
}

#[test]
fn replay_requires_exact_receipt_identity_and_reverification() {
    let mut gate = gate();
    let first = receipt(SplitStageV1::ArtifactLoaded);
    gate.record_verified(&first, |_| true).expect("first");
    gate.record_verified(&first, |_| true).expect("idempotent");
    assert_eq!(
        gate.record_verified(&first, |_| false),
        Err(SplitReceiptErrorV1::InvalidReceipt)
    );
    let mut conflict = first.clone();
    conflict.receipt_digest = Digest32::of_bytes(b"different-issuer-receipt");
    assert_eq!(
        gate.record_verified(&conflict, |_| true),
        Err(SplitReceiptErrorV1::ConflictingReplay)
    );
}
