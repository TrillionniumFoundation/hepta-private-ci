//! Regression tests exercising the actual fenced owner.
use crate::holdout_envelope::HoldoutJournalV2;
use crate::paired_plan::decode_paired_plan;
use crate::paired_plan::encode_paired_plan;
use crate::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use std::cell::RefCell;
use std::rc::Rc;

pub(crate) fn id(s: &str) -> StableId {
    StableId::new(s).expect("fixture id")
}
pub(crate) fn d(s: &str) -> Digest32 {
    Digest32::of_bytes(s.as_bytes())
}
pub(crate) fn fence(generation: u64) -> HoldoutWriterFenceV1 {
    HoldoutWriterFenceV1 {
        owner_id: id("paired-owner"),
        generation,
        lease_digest: d(&generation.to_string()),
    }
}
pub(crate) fn paired(name: &str) -> FrozenPairedPlanV1 {
    freeze_paired_plan_v1(PairedPlanSpecV1 {
        plan_id: id(name),
        candidate_id: id("candidate"),
        baseline_id: id("baseline"),
        holdout_window_id: id(&format!("{name}-window")),
        objective_digest: d("objective"),
        dataset_digest: d("dataset"),
        holdout_digest: d(&format!("{name}-cohort")),
        context_manifest_digest: d("contexts"),
        version_manifest_digest: d("versions"),
        source_bundle_digest: d("source"),
        outcome_bundle_digest: d("outcomes"),
        metric_digest: d("metric"),
        audit_observer_digest: d("audit-b"),
        reward_observer_digest: d("reward-a"),
        estimand_digest: d("estimand"),
        source_cases: 4,
        seeds: 2,
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 2,
        required_modalities: 3,
        minimum_loss_improvement: FixedQ32::ZERO,
        maximum_fact_error_increase: FixedQ32::ZERO,
    })
    .expect("paired fixture")
}
fn ope(name: &str, cohort: Digest32) -> CrossFoldPlanReceiptV1 {
    freeze_cross_fold_plan(CrossFoldPlanV1 {
        plan_id: id(name),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        candidate_id: id("candidate"),
        baseline_id: id("baseline"),
        objective_digest: d("objective"),
        dataset_digest: d("dataset"),
        estimand_digest: d("estimand"),
        metric_contracts: vec![MetricContractV1 {
            metric_id: id("utility"),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: Some(FixedQ32::ZERO),
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: (0..2)
            .map(|i| CrossFoldPartitionV1 {
                fold_id: id(&format!("fold-{i}")),
                training_principals: vec![id(&format!("train-{i}"))],
                training_episodes: vec![id(&format!("train-episode-{i}"))],
                training_windows: vec![id(&format!("train-window-{i}"))],
                holdout_principals: vec![id(&format!("holdout-{i}"))],
                holdout_episodes: vec![id(&format!("episode-{i}"))],
                holdout_windows: vec![id(&format!("{name}-window-{i}"))],
                model_digest: d(&format!("model-{i}")),
                predictions_digest: d(&format!("predictions-{i}")),
            })
            .collect(),
        final_holdout_window_id: id(&format!("{name}-window-1")),
        final_holdout_digest: cohort,
    })
    .expect("actual legacy fold fixture")
}

#[derive(Clone, Default)]
pub(crate) struct MemoryCas {
    pub(crate) state: Rc<RefCell<Option<FinalHoldoutCasRecordV1>>>,
    pub(crate) fault: Rc<RefCell<Option<FinalHoldoutCasStoreError>>>,
}
impl FinalHoldoutCasStoreV1 for MemoryCas {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        let value = self.state.borrow().clone();
        if value.as_ref().is_some_and(|x| x.binding != binding) {
            return Err(FinalHoldoutCasStoreError::Rejected);
        }
        Ok(value)
    }
    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError> {
        if next.binding != binding {
            return Err(FinalHoldoutCasStoreError::Rejected);
        }
        if self.state.borrow().as_ref().map(|x| x.state_digest) != expected {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        let fault = self.fault.borrow_mut().take();
        if let Some(
            error @ (FinalHoldoutCasStoreError::Rejected | FinalHoldoutCasStoreError::Conflict),
        ) = fault
        {
            return Err(error);
        }
        *self.state.borrow_mut() = Some(next.clone());
        fault.map_or(Ok(()), Err)
    }
}

#[test]
fn paired_plan_codec_is_bounded_sealed_and_engineering_only() {
    let plan = paired("p");
    assert!(plan.previously_observed_engineering_only());
    assert!(!plan.authority().grants_any());
    let bytes = encode_paired_plan(&plan).expect("encode");
    assert_eq!(decode_paired_plan(&bytes), Ok(plan.clone()));
    for index in [8, bytes.len() - 1] {
        let mut altered = bytes.clone();
        altered[index] ^= 1;
        assert!(decode_paired_plan(&altered).is_err());
    }
    let mut extra = bytes;
    extra.push(0);
    assert!(decode_paired_plan(&extra).is_err());
    let mut spec = plan.spec().clone();
    spec.source_cases = 4097;
    assert!(freeze_paired_plan_v1(spec).is_err());
    let mut spec = plan.spec().clone();
    spec.audit_observer_digest = spec.reward_observer_digest;
    assert!(freeze_paired_plan_v1(spec).is_err());
}

#[test]
fn old_and_paired_share_one_fenced_cas_and_reuse_registry() {
    let store = MemoryCas::default();
    let mut owner = FencedFinalHoldoutOwnerV1::initialize(store.clone(), d("binding"), fence(1))
        .expect("owner");
    let legacy = ope("legacy", d("old cohort"));
    let receipt = owner.consume(&legacy).expect("legacy");
    let mut pure = FinalHoldoutJournalV1::new();
    assert_eq!(
        receipt,
        pure.consume(Digest32::ZERO, &legacy)
            .expect("legacy unchanged")
    );
    let upgraded =
        HoldoutJournalSnapshotV2::try_from(pure.snapshot()).expect("validated V1 snapshot import");
    assert_eq!(upgraded.head_digest, pure.head_digest());
    assert_eq!(upgraded.records[0].record_digest, receipt.record_digest);
    let mut invalid = pure.snapshot();
    invalid.records[0].record_digest = d("tampered old record");
    assert!(HoldoutJournalSnapshotV2::try_from(invalid).is_err());
    let plan = paired("p");
    let used = owner.consume_paired(&plan).expect("paired");
    assert_eq!(used.sequence, 2);
    used.validate(&plan).expect("seal");
    assert_eq!(owner.anchor().record_count, 2);
    let retry = owner.consume_paired(&plan).expect("same-plan retry");
    assert_eq!(retry.disposition, HoldoutUseDispositionV1::IdempotentReplay);
    assert_eq!(retry.record_digest, used.record_digest);
    assert_eq!(owner.anchor().record_count, 2);
    let mut altered = used;
    altered.sequence += 1;
    assert!(altered.validate(&plan).is_err());
    let mut changed = plan.spec().clone();
    changed.metric_digest = d("new metric");
    assert!(
        owner
            .consume_paired(&freeze_paired_plan_v1(changed).expect("different valid plan"))
            .is_err()
    );
    let mut changed = plan.spec().clone();
    changed.plan_id = id("new-id");
    assert!(
        owner
            .consume_paired(&freeze_paired_plan_v1(changed).expect("new plan id"))
            .is_err()
    );
    assert!(
        owner
            .consume(&ope("cross-profile", plan.spec().holdout_digest))
            .is_err()
    );
    let mut paired_legacy_cohort = paired("other").spec().clone();
    paired_legacy_cohort.holdout_digest = legacy.final_holdout_digest;
    assert!(
        owner
            .consume_paired(&freeze_paired_plan_v1(paired_legacy_cohort).expect("plan"))
            .is_err()
    );
    assert_eq!(
        store
            .state
            .borrow()
            .as_ref()
            .expect("record")
            .journal
            .records
            .len(),
        2
    );
}

#[test]
fn paired_takeover_and_uncertain_cas_keep_existing_fail_closed_semantics() {
    let store = MemoryCas::default();
    let mut first = FencedFinalHoldoutOwnerV1::initialize(store.clone(), d("binding"), fence(1))
        .expect("first");
    let mut second = FencedFinalHoldoutOwnerV1::recover(store.clone(), d("binding"), fence(2))
        .expect("takeover");
    assert_eq!(
        first.consume_paired(&paired("stale")).err(),
        Some(FencedHoldoutError::Conflict)
    );
    assert!(first.is_poisoned());
    *store.fault.borrow_mut() = Some(FinalHoldoutCasStoreError::Rejected);
    assert_eq!(
        second.consume_paired(&paired("p")).err(),
        Some(FencedHoldoutError::Rejected)
    );
    assert_eq!(second.anchor().record_count, 0);
    *store.fault.borrow_mut() = Some(FinalHoldoutCasStoreError::Indeterminate);
    assert_eq!(
        second.consume_paired(&paired("p")).err(),
        Some(FencedHoldoutError::Indeterminate)
    );
    assert!(second.is_poisoned());
    let mut recovered = FencedFinalHoldoutOwnerV1::recover(store, d("binding"), fence(3))
        .expect("recover authoritative write");
    assert_eq!(
        recovered
            .consume_paired(&paired("p"))
            .expect("idempotent")
            .disposition,
        HoldoutUseDispositionV1::IdempotentReplay
    );
    assert_eq!(recovered.anchor().record_count, 1);
}

#[test]
fn mixed_snapshot_rejects_duplicate_omitted_or_changed_entries() {
    let mut journal = HoldoutJournalV2::with_record_limit(10).expect("journal");
    journal
        .consume_paired(Digest32::ZERO, &paired("p"))
        .expect("consume");
    let valid = journal.snapshot();
    assert!(HoldoutJournalV2::from_snapshot_with_record_limit(valid.clone(), 10).is_ok());
    let mut changed = valid.clone();
    changed.records.push(changed.records[0].clone());
    assert!(HoldoutJournalV2::from_snapshot_with_record_limit(changed, 10).is_err());
    let mut changed = valid.clone();
    changed.records.clear();
    assert!(HoldoutJournalV2::from_snapshot_with_record_limit(changed, 10).is_err());
    let mut changed = valid;
    changed.records[0].record_digest = d("changed");
    assert!(HoldoutJournalV2::from_snapshot_with_record_limit(changed, 10).is_err());
}

#[test]
fn actual_locked_file_replays_mixed_profiles_and_retains_rollback_anchor() {
    use std::fs::OpenOptions;
    use std::fs::{self};
    let path = std::env::temp_dir().join(format!("hepta-paired-owner-{}", std::process::id()));
    let open = || {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .expect("open")
    };
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&path)
        .expect("new");
    let store = LockedFileFinalHoldoutCasStoreV1::create(file, d("binding")).expect("store");
    let mut owner =
        FencedFinalHoldoutOwnerV1::initialize(store, d("binding"), fence(1)).expect("owner");
    owner
        .consume(&ope("legacy", d("old cohort")))
        .expect("legacy");
    let backup = fs::read(&path).expect("backup");
    let plan = paired("p");
    let receipt = owner.consume_paired(&plan).expect("paired");
    let anchor = owner.anchor();
    drop(owner);
    let store = LockedFileFinalHoldoutCasStoreV1::recover(open(), d("binding"), Some(anchor))
        .expect("reopen");
    let mut owner =
        FencedFinalHoldoutOwnerV1::recover(store, d("binding"), fence(2)).expect("recover owner");
    assert_eq!(
        owner.consume_paired(&plan).expect("replay").record_digest,
        receipt.record_digest
    );
    assert_eq!(owner.anchor().record_count, 2);
    drop(owner);
    fs::write(&path, backup).expect("restore backup");
    assert_eq!(
        LockedFileFinalHoldoutCasStoreV1::recover(open(), d("binding"), Some(anchor)).err(),
        Some(LockedFileCasErrorV1::Rollback)
    );
    fs::remove_file(path).expect("remove fixture");
}

#[path = "legacy_byte_migration_tests.rs"]
mod legacy_byte_migration_tests;
