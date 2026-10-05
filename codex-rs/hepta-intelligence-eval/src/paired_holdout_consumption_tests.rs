//! Real files and the original CAS semantic owner; only task/signature fixtures
//! are synthetic. These tests neither open production custody nor release gold.
use super::*;
use crate::FencedFinalHoldoutOwnerV1;
use crate::NamedTempFile;
use crate::freeze_paired_supervised_plan_v1;
use crate::paired_supervised_test_support::digest;
use crate::paired_supervised_test_support::id;
use crate::paired_supervised_test_support::inputs;
use pretty_assertions::assert_eq;

fn setup() -> (
    NamedTempFile,
    FencedFinalHoldoutOwnerV1<LockedFileFinalHoldoutCasStoreV1>,
    HeldPairedConsumptionV1,
    CrossFoldPlanReceiptV1,
) {
    let temp = NamedTempFile::new().unwrap();
    let binding = digest("paired-original-cas");
    let store = LockedFileFinalHoldoutCasStoreV1::create(temp.reopen().unwrap(), binding).unwrap();
    let reader = HeldPairedConsumptionV1 {
        file: store.file.try_clone().unwrap(),
        binding,
        minimum: store.anchor(),
    };
    let owner = FencedFinalHoldoutOwnerV1::initialize(
        store,
        binding,
        HoldoutWriterFenceV1 {
            owner_id: id("original-custody-owner"),
            generation: 1,
            lease_digest: digest("original-lease"),
        },
    )
    .unwrap();
    let plan = freeze_paired_supervised_plan_v1(inputs(8))
        .unwrap()
        .frozen_plan()
        .clone();
    (temp, owner, reader, plan)
}

#[test]
fn caller_receipt_cannot_release_before_original_cas_commit() {
    let (_temp, mut owner, reader, plan) = setup();
    let forged = FinalHoldoutJournalV1::new()
        .consume(Digest32::ZERO, &plan)
        .unwrap();
    assert_eq!(
        reader.verify(&plan, &forged),
        Err(LockedFileCasErrorV1::Binding)
    );
    let original = owner.consume(&plan).unwrap();
    assert_eq!(reader.verify(&plan, &original), Ok(()));
    assert_eq!(original, forged);
}

#[test]
fn complete_original_plan_and_receipt_are_required() {
    let (_temp, mut owner, reader, plan) = setup();
    let receipt = owner.consume(&plan).unwrap();
    let mut wrong = receipt.clone();
    wrong.record_digest = digest("caller-record");
    assert_eq!(
        reader.verify(&plan, &wrong),
        Err(LockedFileCasErrorV1::Binding)
    );
    let mut different_plan = plan.clone();
    different_plan.objective_digest = digest("caller-objective");
    assert_eq!(
        reader.verify(&different_plan, &receipt),
        Err(LockedFileCasErrorV1::Binding)
    );
    let replay = owner.consume(&plan).unwrap();
    assert_eq!(
        reader.verify(&plan, &replay),
        Err(LockedFileCasErrorV1::Binding)
    );
}

#[test]
fn held_read_preserves_writer_cursor_and_physical_lock_until_close() {
    let (temp, mut owner, reader, plan) = setup();
    let receipt = owner.consume(&plan).unwrap();
    reader.verify(&plan, &receipt).unwrap();
    let mut next_inputs = inputs(8);
    next_inputs.base_plan.plan_id = id("next-original-plan");
    next_inputs.base_plan.final_holdout_digest = digest("different-cohort");
    next_inputs.base_plan.final_holdout_window_id = id("next-window");
    let final_fold = next_inputs.folds.last_mut().unwrap();
    final_fold.holdout_windows = vec![id("next-window")];
    let next = freeze_paired_supervised_plan_v1(next_inputs).unwrap();
    let next_receipt = owner.consume(next.frozen_plan()).unwrap();
    assert_eq!(reader.verify(next.frozen_plan(), &next_receipt), Ok(()));
    assert_eq!(
        reader.verify(&plan, &receipt),
        Err(LockedFileCasErrorV1::Binding)
    );
    drop(owner);
    let contender = temp.reopen().unwrap();
    assert!(matches!(
        contender.try_lock(),
        Err(TryLockError::WouldBlock)
    ));
    drop(reader);
    contender.try_lock().unwrap();
}

#[test]
fn truncated_committed_frame_is_closed_without_repair_or_new_use() {
    let (temp, mut owner, reader, plan) = setup();
    let receipt = owner.consume(&plan).unwrap();
    let file = temp.reopen().unwrap();
    let length = file.metadata().unwrap().len();
    file.set_len(length - 1).unwrap();
    file.sync_all().unwrap();
    assert_eq!(
        reader.verify(&plan, &receipt),
        Err(LockedFileCasErrorV1::Corrupt)
    );
    assert_eq!(file.metadata().unwrap().len(), length - 1);
    assert!(owner.consume(&plan).is_err());
}
