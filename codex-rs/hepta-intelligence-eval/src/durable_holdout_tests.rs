use super::*;
use crate::CrossFoldPartitionV1;
use crate::CrossFoldPlanV1;
use crate::EvaluationClaimScopeV1;
use crate::EvaluationDirectionV1;
use crate::MetricContractV1;
use crate::freeze_cross_fold_plan;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use std::fs::OpenOptions;
use std::fs::{self};
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);
struct Directory(PathBuf);
impl Directory {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "hepta-holdout-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn path(&self) -> PathBuf {
        self.0.join("holdout")
    }
    fn file(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.path())
            .unwrap()
    }
    fn create(&self) -> DurableFinalHoldoutJournalV1 {
        let file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(self.path())
            .unwrap();
        DurableFinalHoldoutJournalV1::create(file, digest("binding")).unwrap()
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn plan(name: &str) -> CrossFoldPlanReceiptV1 {
    freeze_cross_fold_plan(CrossFoldPlanV1 {
        plan_id: id(name),
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
        folds: (0..2)
            .map(|n| CrossFoldPartitionV1 {
                fold_id: id(&format!("fold-{n}")),
                training_principals: vec![id("train")],
                training_episodes: vec![id("train-episode")],
                training_windows: vec![id("train-window")],
                holdout_principals: vec![id(&format!("holdout-{n}"))],
                holdout_episodes: vec![id(&format!("held-episode-{n}"))],
                holdout_windows: vec![id(&format!("held-window-{n}"))],
                model_digest: digest("model"),
                predictions_digest: digest("predictions"),
            })
            .collect(),
        final_holdout_window_id: id("held-window-1"),
        final_holdout_digest: digest("holdout"),
    })
    .unwrap()
}

#[test]
fn durable_reopen_prevents_holdout_reuse() {
    // The same test is also launched in a distinct process by the test below.
    let owned;
    let (path, anchor) = if let Some(path) = std::env::var_os("HEPTA_HOLDOUT_REOPEN_PATH") {
        let head = std::env::var("HEPTA_HOLDOUT_REOPEN_HEAD")
            .unwrap()
            .parse()
            .unwrap();
        (PathBuf::from(path), HoldoutAnchorV1 { sequence: 1, head })
    } else {
        owned = Directory::new();
        let mut store = owned.create();
        store.consume(store.anchor(), &plan("plan-1")).unwrap();
        (owned.path(), store.anchor())
    };
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .unwrap();
    let mut store = DurableFinalHoldoutJournalV1::recover(file, digest("binding"), anchor).unwrap();
    assert_eq!(store.anchor(), anchor);
    assert_eq!(
        store.consume(anchor, &plan("plan-2")),
        Err(DurableHoldoutError::Semantic)
    );
    assert_eq!(
        store.consume(anchor, &plan("plan-1")).unwrap().disposition,
        HoldoutUseDispositionV1::IdempotentReplay
    );
}

#[test]
fn consumption_survives_a_distinct_process() {
    let directory = Directory::new();
    let mut store = directory.create();
    store.consume(store.anchor(), &plan("plan-1")).unwrap();
    let anchor = store.anchor();
    drop(store);
    let output = Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "durable_holdout::tests::durable_reopen_prevents_holdout_reuse",
            "--nocapture",
        ])
        .env("HEPTA_HOLDOUT_REOPEN_PATH", directory.path())
        .env("HEPTA_HOLDOUT_REOPEN_HEAD", anchor.head.to_string())
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(String::from_utf8_lossy(&output.stdout).contains("1 passed"));
}

#[test]
fn independent_anchor_rejects_old_backup_and_partial_tail() {
    let directory = Directory::new();
    let mut store = directory.create();
    let old = fs::read(directory.path()).unwrap();
    store.consume(store.anchor(), &plan("plan-1")).unwrap();
    let anchor = store.anchor();
    drop(store);
    let current = fs::read(directory.path()).unwrap();
    fs::write(directory.path(), &old).unwrap();
    assert!(matches!(
        DurableFinalHoldoutJournalV1::recover(directory.file(), digest("binding"), anchor),
        Err(DurableHoldoutError::MissingAcknowledgedHistory)
    ));
    fs::write(directory.path(), &current[..current.len() - 1]).unwrap();
    assert!(matches!(
        DurableFinalHoldoutJournalV1::recover(directory.file(), digest("binding"), anchor),
        Err(DurableHoldoutError::Corrupt)
    ));
    assert_eq!(
        fs::read(directory.path()).unwrap(),
        current[..current.len() - 1]
    );
}

#[test]
fn lock_binding_cas_and_invalid_plan_do_not_mutate_storage() {
    let directory = Directory::new();
    let mut store = directory.create();
    assert!(matches!(
        DurableFinalHoldoutJournalV1::recover(directory.file(), digest("binding"), store.anchor()),
        Err(DurableHoldoutError::Busy)
    ));
    let before = fs::read(directory.path()).unwrap();
    assert_eq!(
        store.consume(
            HoldoutAnchorV1 {
                sequence: 1,
                head: digest("wrong")
            },
            &plan("plan-1")
        ),
        Err(DurableHoldoutError::Conflict)
    );
    let mut invalid = plan("plan-1");
    invalid.candidate_id = id("mutated");
    assert_eq!(
        store.consume(store.anchor(), &invalid),
        Err(DurableHoldoutError::Semantic)
    );
    assert_eq!(fs::read(directory.path()).unwrap(), before);
    let anchor = store.anchor();
    drop(store);
    assert!(matches!(
        DurableFinalHoldoutJournalV1::recover(directory.file(), digest("different-store"), anchor),
        Err(DurableHoldoutError::Corrupt)
    ));
}

#[test]
fn idempotent_retry_does_not_append_and_byte_corruption_rejects() {
    let directory = Directory::new();
    let mut store = directory.create();
    store.consume(store.anchor(), &plan("plan-1")).unwrap();
    let anchor = store.anchor();
    let before = fs::read(directory.path()).unwrap();
    store.consume(anchor, &plan("plan-1")).unwrap();
    assert_eq!(fs::read(directory.path()).unwrap(), before);
    drop(store);
    let mut bad = before;
    bad[HEADER + 8] ^= 1;
    fs::write(directory.path(), bad).unwrap();
    assert!(matches!(
        DurableFinalHoldoutJournalV1::recover(directory.file(), digest("binding"), anchor),
        Err(DurableHoldoutError::Corrupt)
    ));
}

#[cfg(unix)]
#[test]
fn ambiguous_write_fences_the_handle() {
    let directory = Directory::new();
    let store = directory.create();
    let anchor = store.anchor();
    drop(store);
    let mut store = DurableFinalHoldoutJournalV1::recover(
        File::open(directory.path()).unwrap(),
        digest("binding"),
        anchor,
    )
    .unwrap();
    assert_eq!(
        store.consume(anchor, &plan("plan-1")),
        Err(DurableHoldoutError::Indeterminate)
    );
    assert_eq!(
        store.consume(anchor, &plan("plan-1")),
        Err(DurableHoldoutError::Poisoned)
    );
    assert_eq!(store.anchor(), anchor);
}
