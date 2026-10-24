use codex_hepta_intelligence_eval::*;
use codex_hepta_types::{Digest32, FixedQ32, StableId};
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


#[test]
fn write_legacy_golden_fixture() {
    use std::fs::{self, OpenOptions};
    let dir = std::path::PathBuf::from(std::env::var("HEPTA_GOLDEN_DIRECTORY").expect("explicit fixture output"));
    fs::create_dir(&dir).expect("fresh output directory");
    let path = dir.join("legacy.journal");
    let file = OpenOptions::new().read(true).write(true).create_new(true).open(&path).expect("fresh journal");
    let store = LockedFileFinalHoldoutCasStoreV1::create(file, d("binding")).expect("old store");
    let mut owner = FencedFinalHoldoutOwnerV1::initialize(store, d("binding"), fence(1)).expect("old owner");
    let receipt = owner.consume(&ope("legacy", d("old cohort"))).expect("old consume");
    let anchor = owner.anchor();
    let witness = format!("anchor={anchor:?}\nreceipt={receipt:?}\nhead={:?}\n", owner.head_digest());
    fs::write(dir.join("witness.txt"), witness).expect("witness");
    drop(owner);
    let bytes = fs::read(&path).expect("read written bytes");
    let hex: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
    fs::write(dir.join("legacy.hex"), hex).expect("golden bytes");
    println!("legacy_bytes={} anchor={anchor:?}", bytes.len());
}
