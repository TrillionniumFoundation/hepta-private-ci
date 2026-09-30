use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_intelligence_eval::CrossFoldPartitionV1;
use codex_hepta_intelligence_eval::CrossFoldPlanV1;
use codex_hepta_intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_intelligence_eval::EvaluationDirectionV1;
use codex_hepta_intelligence_eval::FencedFinalHoldoutOwnerV1;
use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::HoldoutWriterFenceV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::MetricContractV1;
use codex_hepta_intelligence_eval::freeze_cross_fold_plan;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

struct TempFile {
    path: PathBuf,
}

impl TempFile {
    fn new(label: &str) -> Self {
        let path = std::env::temp_dir().join(format!(
            "hepta-learning-eval-{label}-{}-{}",
            std::process::id(),
            NEXT_TEMP.fetch_add(1, Ordering::Relaxed)
        ));
        OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&path)
            .expect("create temporary file");
        Self { path }
    }

    fn reopen(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&self.path)
            .expect("reopen temporary file")
    }
}

impl Drop for TempFile {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn frozen_plan() -> codex_hepta_intelligence_eval::CrossFoldPlanReceiptV1 {
    freeze_cross_fold_plan(CrossFoldPlanV1 {
        plan_id: id("compaction-plan"),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        candidate_id: id("candidate"),
        baseline_id: id("baseline"),
        objective_digest: digest("objective"),
        dataset_digest: digest("dataset"),
        estimand_digest: digest("estimand"),
        metric_contracts: vec![MetricContractV1 {
            metric_id: id("utility"),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: Some(FixedQ32::ZERO),
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: vec![
            CrossFoldPartitionV1 {
                fold_id: id("fold-a"),
                training_principals: vec![id("train-principal-a")],
                training_episodes: vec![id("train-episode-a")],
                training_windows: vec![id("train-window-a")],
                holdout_principals: vec![id("holdout-principal-a")],
                holdout_episodes: vec![id("holdout-episode-a")],
                holdout_windows: vec![id("holdout-window-a")],
                model_digest: digest("model-a"),
                predictions_digest: digest("predictions-a"),
            },
            CrossFoldPartitionV1 {
                fold_id: id("fold-b"),
                training_principals: vec![id("train-principal-b")],
                training_episodes: vec![id("train-episode-b")],
                training_windows: vec![id("train-window-b")],
                holdout_principals: vec![id("holdout-principal-b")],
                holdout_episodes: vec![id("holdout-episode-b")],
                holdout_windows: vec![id("final-window")],
                model_digest: digest("model-b"),
                predictions_digest: digest("predictions-b"),
            },
        ],
        final_holdout_window_id: id("final-window"),
        final_holdout_digest: digest("final-holdout"),
    })
    .expect("freeze plan")
}

#[test]
fn compaction_replays_nonempty_holdout_journal_without_semantic_drift() {
    let source_file = TempFile::new("source");
    let compacted_file = TempFile::new("compacted");
    let binding = digest("compaction-binding-with-record");
    let store = LockedFileFinalHoldoutCasStoreV1::create(source_file.reopen(), binding)
        .expect("create source store");
    let fence = HoldoutWriterFenceV1 {
        owner_id: id("owner"),
        generation: 1,
        lease_digest: digest("lease"),
    };
    let mut owner =
        FencedFinalHoldoutOwnerV1::initialize(store, binding, fence).expect("initialize owner");
    let use_receipt = owner.consume(&frozen_plan()).expect("consume holdout plan");
    assert!(!use_receipt.record_digest.is_zero());
    let source_anchor = owner.anchor();
    assert_eq!(source_anchor.record_count, 1);

    let mut source_store = owner.into_store();
    let source_state = source_store
        .load(binding)
        .expect("load source state")
        .expect("source state exists");
    let (mut compacted, compaction_receipt) = source_store
        .compact_into(compacted_file.reopen())
        .expect("compact source");
    compaction_receipt
        .validate_integrity()
        .expect("compaction receipt integrity");
    assert_eq!(compaction_receipt.record_count, 1);
    assert_eq!(compaction_receipt.state_digest, source_state.state_digest);
    assert_eq!(compacted.anchor(), Some(source_anchor));
    assert_eq!(
        compacted.load(binding).expect("load compacted state"),
        Some(source_state.clone())
    );
    drop(compacted);

    let mut recovered = LockedFileFinalHoldoutCasStoreV1::recover(
        compacted_file.reopen(),
        binding,
        Some(source_anchor),
    )
    .expect("recover compacted target");
    assert_eq!(recovered.anchor(), Some(source_anchor));
    assert_eq!(
        recovered.load(binding).expect("load recovered state"),
        Some(source_state)
    );
}
