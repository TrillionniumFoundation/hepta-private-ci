use super::*;

use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::FixedQ32;

use crate::CrossFoldPartitionV1;
use crate::CrossFoldPlanV1;
use crate::EvaluationClaimScopeV1;
use crate::EvaluationDirectionV1;
use crate::FencedFinalHoldoutOwnerV1;
use crate::HoldoutFenceIssuerV1;
use crate::MetricContractV1;
use crate::freeze_cross_fold_plan;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn id(value: &str) -> StableId {
    match StableId::new(value) {
        Ok(value) => value,
        Err(error) => panic!("invalid test id {value}: {error}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct TempFile {
    path: PathBuf,
}

impl TempFile {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "hepta-fenced-cas-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        Self { path }
    }

    fn create(&self) -> File {
        match OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&self.path)
        {
            Ok(file) => file,
            Err(error) => panic!("create temp store: {error}"),
        }
    }

    fn open(&self) -> File {
        match OpenOptions::new().read(true).write(true).open(&self.path) {
            Ok(file) => file,
            Err(error) => panic!("open temp store: {error}"),
        }
    }
}

impl Drop for TempFile {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}

fn recover_after_local_release(
    temp: &TempFile,
    minimum: Option<FinalHoldoutCasAnchorV1>,
) -> Result<LockedFileFinalHoldoutCasStoreV1, LockedFileCasErrorV1> {
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        let result =
            LockedFileFinalHoldoutCasStoreV1::recover(temp.open(), digest("binding"), minimum);
        if !matches!(result, Err(LockedFileCasErrorV1::Busy)) || Instant::now() >= deadline {
            return result;
        }
        thread::sleep(Duration::from_millis(10));
    }
}

fn plan(name: &str) -> crate::CrossFoldPlanReceiptV1 {
    match freeze_cross_fold_plan(CrossFoldPlanV1 {
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
        folds: vec![
            CrossFoldPartitionV1 {
                fold_id: id("fold-a"),
                training_principals: vec![id("train-a")],
                training_episodes: vec![id("train-episode-a")],
                training_windows: vec![id("train-window-a")],
                holdout_principals: vec![id("holdout-a")],
                holdout_episodes: vec![id("holdout-episode-a")],
                holdout_windows: vec![id("holdout-window-a")],
                model_digest: digest("model-a"),
                predictions_digest: digest("predictions-a"),
            },
            CrossFoldPartitionV1 {
                fold_id: id("fold-b"),
                training_principals: vec![id("train-b")],
                training_episodes: vec![id("train-episode-b")],
                training_windows: vec![id("train-window-b")],
                holdout_principals: vec![id("holdout-b")],
                holdout_episodes: vec![id("holdout-episode-b")],
                holdout_windows: vec![id(&format!("{name}-final-window"))],
                model_digest: digest("model-b"),
                predictions_digest: digest("predictions-b"),
            },
        ],
        final_holdout_window_id: id(&format!("{name}-final-window")),
        final_holdout_digest: digest(&format!("{name}-final-holdout")),
    }) {
        Ok(value) => value,
        Err(error) => panic!("freeze plan: {error}"),
    }
}

fn owner(
    store: LockedFileFinalHoldoutCasStoreV1,
    minimum: Option<FinalHoldoutCasAnchorV1>,
) -> FencedFinalHoldoutOwnerV1<LockedFileFinalHoldoutCasStoreV1> {
    let mut issuer =
        match HoldoutFenceIssuerV1::resume(id("eval-owner"), digest("fence-authority"), minimum) {
            Ok(value) => value,
            Err(error) => panic!("resume fence issuer: {error}"),
        };
    let fence = match issuer.issue(digest("lease")) {
        Ok(value) => value,
        Err(error) => panic!("issue fence: {error}"),
    };
    match minimum {
        None => match FencedFinalHoldoutOwnerV1::initialize(store, digest("binding"), fence) {
            Ok(value) => value,
            Err(error) => panic!("initialize owner: {error}"),
        },
        Some(_) => match FencedFinalHoldoutOwnerV1::recover(store, digest("binding"), fence) {
            Ok(value) => value,
            Err(error) => panic!("recover owner: {error}"),
        },
    }
}

#[test]
fn locked_file_store_replays_takeover_and_rejects_backup_rollback() {
    let temp = TempFile::new();
    let store = match LockedFileFinalHoldoutCasStoreV1::create(temp.create(), digest("binding")) {
        Ok(value) => value,
        Err(error) => panic!("create store: {error}"),
    };
    let first = owner(store, None);
    let first_anchor = first.anchor();
    let store = first.into_store();
    drop(store);

    let backup = match fs::read(&temp.path) {
        Ok(value) => value,
        Err(error) => panic!("read backup: {error}"),
    };
    let store = match recover_after_local_release(&temp, Some(first_anchor)) {
        Ok(value) => value,
        Err(error) => panic!("recover store: {error}"),
    };
    let mut second = owner(store, Some(first_anchor));
    if let Err(error) = second.consume(&plan("plan-1")) {
        panic!("consume: {error}");
    }
    let committed = second.anchor();
    assert!(committed.record_count > first_anchor.record_count);
    let store = second.into_store();
    drop(store);

    if let Err(error) = fs::write(&temp.path, &backup) {
        panic!("restore backup: {error}");
    }
    assert_eq!(
        recover_after_local_release(&temp, Some(committed)).err(),
        Some(LockedFileCasErrorV1::Rollback)
    );
}

#[test]
fn child_process_observes_lock_then_recovers_after_owner_exit() {
    if let Ok(path) = std::env::var("HEPTA_FENCED_CAS_CHILD") {
        let file = match OpenOptions::new().read(true).write(true).open(path) {
            Ok(file) => file,
            Err(error) => panic!("child open: {error}"),
        };
        let result = LockedFileFinalHoldoutCasStoreV1::recover(file, digest("binding"), None);
        let expect_busy = std::env::var("HEPTA_FENCED_CAS_EXPECT_BUSY").is_ok();
        if expect_busy {
            assert_eq!(result.err(), Some(LockedFileCasErrorV1::Busy));
        } else if let Err(error) = result {
            panic!("child failover recovery: {error}");
        }
        return;
    }

    let temp = TempFile::new();
    let store = match LockedFileFinalHoldoutCasStoreV1::create(temp.create(), digest("binding")) {
        Ok(value) => value,
        Err(error) => panic!("create store: {error}"),
    };
    let first = owner(store, None);

    let exe = match std::env::current_exe() {
        Ok(value) => value,
        Err(error) => panic!("current test executable: {error}"),
    };
    let busy = match Command::new(&exe)
        .args([
            "--exact",
            "fenced_holdout_file::tests::child_process_observes_lock_then_recovers_after_owner_exit",
        ])
        .env("HEPTA_FENCED_CAS_CHILD", &temp.path)
        .env("HEPTA_FENCED_CAS_EXPECT_BUSY", "1")
        .status()
    {
        Ok(value) => value,
        Err(error) => panic!("spawn busy child: {error}"),
    };
    assert!(busy.success());

    let store = first.into_store();
    drop(store);
    let recovered = match Command::new(&exe)
        .args([
            "--exact",
            "fenced_holdout_file::tests::child_process_observes_lock_then_recovers_after_owner_exit",
        ])
        .env("HEPTA_FENCED_CAS_CHILD", &temp.path)
        .status()
    {
        Ok(value) => value,
        Err(error) => panic!("spawn failover child: {error}"),
    };
    assert!(recovered.success());
}

#[test]
fn longer_divergent_history_cannot_skip_the_retained_minimum_prefix() {
    let temp = TempFile::new();
    let store = LockedFileFinalHoldoutCasStoreV1::create(temp.create(), digest("binding"))
        .unwrap_or_else(|error| panic!("create store: {error}"));
    let first = owner(store, None);
    let fence = first.fence().clone();
    let store = first.into_store();
    drop(store);
    let pre_minimum =
        fs::read(&temp.path).unwrap_or_else(|error| panic!("read pre-minimum backup: {error}"));

    let store = recover_after_local_release(&temp, None)
        .unwrap_or_else(|error| panic!("recover store: {error}"));
    let mut canonical = FencedFinalHoldoutOwnerV1::recover(store, digest("binding"), fence.clone())
        .unwrap_or_else(|error| panic!("recover canonical owner: {error}"));
    canonical
        .consume(&plan("canonical-plan"))
        .unwrap_or_else(|error| panic!("consume canonical plan: {error}"));
    let retained = canonical.anchor();
    let store = canonical.into_store();
    drop(store);

    fs::write(&temp.path, pre_minimum)
        .unwrap_or_else(|error| panic!("restore pre-minimum backup: {error}"));
    let store = recover_after_local_release(&temp, None)
        .unwrap_or_else(|error| panic!("recover divergent base: {error}"));
    let mut divergent = FencedFinalHoldoutOwnerV1::recover(store, digest("binding"), fence)
        .unwrap_or_else(|error| panic!("recover divergent owner: {error}"));
    divergent
        .consume(&plan("divergent-plan-a"))
        .unwrap_or_else(|error| panic!("consume divergent a: {error}"));
    divergent
        .consume(&plan("divergent-plan-b"))
        .unwrap_or_else(|error| panic!("consume divergent b: {error}"));
    let store = divergent.into_store();
    drop(store);

    assert_eq!(
        recover_after_local_release(&temp, Some(retained)).err(),
        Some(LockedFileCasErrorV1::Rollback)
    );
}
