use super::*;

fn gate() -> CellSplitReceiptGate {
    CellSplitReceiptGate::new("scope:a".into(), "attempt:1".into(), 4, 5).unwrap()
}

fn receipt(step: SplitStep, index: usize) -> VerifiedSplitReceipt {
    VerifiedSplitReceipt {
        operation_id: format!("op:{index}"),
        scope: "scope:a".into(),
        attempt_id: "attempt:1".into(),
        issuing_owner: format!("owner:{index}"),
        issuer_receipt_id: format!("receipt:{index}"),
        generation: if step == SplitStep::PreviousGenerationFenced {
            4
        } else {
            5
        },
        externally_verified: true,
    }
}

#[test]
fn split_requires_all_six_external_receipts_in_order() {
    let mut gate = gate();
    let steps = [
        SplitStep::ArtifactLoaded,
        SplitStep::ChildMigrated,
        SplitStep::ChildBootstrapped,
        SplitStep::FinalUseAuthorized,
        SplitStep::PreviousGenerationFenced,
        SplitStep::RouteCutover,
    ];
    for (index, step) in steps.into_iter().enumerate() {
        assert_eq!(gate.next_step(), Some(step));
        gate.record(step, receipt(step, index)).unwrap();
    }
    assert!(gate.is_complete());
    assert_eq!(gate.next_step(), None);
    assert_eq!(
        gate.record(SplitStep::RouteCutover, receipt(SplitStep::RouteCutover, 7)),
        Err(SplitGateError::Terminal)
    );
}

#[test]
fn cannot_cutover_without_predecessors_or_trust() {
    let mut gate = gate();
    assert_eq!(
        gate.record(SplitStep::RouteCutover, receipt(SplitStep::RouteCutover, 9)),
        Err(SplitGateError::IncorrectStep)
    );
    let mut claimed = receipt(SplitStep::ArtifactLoaded, 0);
    claimed.externally_verified = false;
    assert_eq!(
        gate.record(SplitStep::ArtifactLoaded, claimed),
        Err(SplitGateError::UnverifiedReceipt)
    );
    assert_eq!(gate.next_step(), Some(SplitStep::ArtifactLoaded));
}

#[test]
fn rejects_wrong_scope_generation_and_reused_external_receipt() {
    let mut gate = gate();
    let mut wrong = receipt(SplitStep::ArtifactLoaded, 0);
    wrong.scope = "scope:other".into();
    assert_eq!(
        gate.record(SplitStep::ArtifactLoaded, wrong),
        Err(SplitGateError::InvalidIdentity)
    );
    let mut wrong = receipt(SplitStep::ArtifactLoaded, 0);
    wrong.generation = 4;
    assert_eq!(
        gate.record(SplitStep::ArtifactLoaded, wrong),
        Err(SplitGateError::GenerationMismatch)
    );
    gate.record(
        SplitStep::ArtifactLoaded,
        receipt(SplitStep::ArtifactLoaded, 0),
    )
    .unwrap();
    let mut reused = receipt(SplitStep::ChildMigrated, 1);
    reused.issuing_owner = "owner:0".into();
    reused.issuer_receipt_id = "receipt:0".into();
    assert_eq!(
        gate.record(SplitStep::ChildMigrated, reused),
        Err(SplitGateError::DuplicateReceipt)
    );
}
