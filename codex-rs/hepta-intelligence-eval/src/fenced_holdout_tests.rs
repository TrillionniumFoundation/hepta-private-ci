use super::*;
use crate::CrossFoldPartitionV1;
use crate::CrossFoldPlanV1;
use crate::EvaluationClaimScopeV1;
use crate::EvaluationDirectionV1;
use crate::MetricContractV1;
use crate::freeze_cross_fold_plan;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use std::fs::OpenOptions;
use std::fs::{self};
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Directory(PathBuf);
impl Directory {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "hepta-fenced-holdout-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn create(&self) -> DurableFinalHoldoutJournalV1 {
        let file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(self.0.join("holdout"))
            .unwrap();
        DurableFinalHoldoutJournalV1::create(file, digest("binding")).unwrap()
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[derive(Clone, Copy)]
struct MemoryFence {
    state: HoldoutFenceStateV1,
    fail_commit: bool,
    swaps: u8,
}
impl HoldoutFenceStoreV1 for MemoryFence {
    fn load(&mut self) -> Result<HoldoutFenceStateV1, DurableHoldoutError> {
        Ok(self.state)
    }

    fn compare_and_swap(
        &mut self,
        expected: HoldoutFenceStateV1,
        desired: HoldoutFenceStateV1,
    ) -> Result<bool, DurableHoldoutError> {
        self.swaps = self.swaps.saturating_add(1);
        if self.fail_commit && self.swaps == 2 {
            return Ok(false);
        }
        if self.state != expected {
            return Ok(false);
        }
        self.state = desired;
        Ok(true)
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
fn fenced_owner_reserves_then_commits_monotonic_anchor() {
    let directory = Directory::new();
    let journal = directory.create();
    let fence = MemoryFence {
        state: HoldoutFenceStateV1::committed(10, journal.anchor()),
        fail_commit: false,
        swaps: 0,
    };
    let mut owner = FencedFinalHoldoutOwnerV1::new(journal, fence).unwrap();
    let receipt = owner.consume(&plan("plan-1")).unwrap();
    assert_eq!(receipt.disposition, HoldoutUseDispositionV1::Recorded);
    let expected_anchor = owner.anchor();
    let (_, mut fence) = owner.into_parts();
    let state = fence.load().unwrap();
    assert_eq!(state.epoch, 12);
    assert_eq!(state.committed_anchor, expected_anchor);
    assert!(state.pending_plan_digest.is_zero());
}

#[test]
fn pending_reservation_blocks_another_owner() {
    let directory = Directory::new();
    let journal = directory.create();
    let fence = MemoryFence {
        state: HoldoutFenceStateV1 {
            epoch: 2,
            committed_anchor: journal.anchor(),
            pending_plan_digest: digest("reserved-plan"),
        },
        fail_commit: false,
        swaps: 0,
    };
    assert!(matches!(
        FencedFinalHoldoutOwnerV1::new(journal, fence),
        Err(DurableHoldoutError::Indeterminate)
    ));
}

#[test]
fn lost_commit_acknowledgement_poison_fences_handle() {
    let directory = Directory::new();
    let journal = directory.create();
    let fence = MemoryFence {
        state: HoldoutFenceStateV1::committed(4, journal.anchor()),
        fail_commit: true,
        swaps: 0,
    };
    let mut owner = FencedFinalHoldoutOwnerV1::new(journal, fence).unwrap();
    assert_eq!(
        owner.consume(&plan("plan-1")),
        Err(DurableHoldoutError::Indeterminate)
    );
    assert_eq!(
        owner.consume(&plan("plan-1")),
        Err(DurableHoldoutError::Poisoned)
    );
    let (_, mut fence) = owner.into_parts();
    assert!(!fence.load().unwrap().pending_plan_digest.is_zero());
}

#[test]
fn pending_reservation_reconciles_before_or_after_journal_sync() {
    // Crash after reservation but before journal mutation: reconciliation owns
    // the exact plan, performs the durable consume, then commits the new anchor.
    let before = Directory::new();
    let journal = before.create();
    let frozen = plan("plan-before-sync");
    let reserved = HoldoutFenceStateV1 {
        epoch: 8,
        committed_anchor: journal.anchor(),
        pending_plan_digest: frozen.plan_digest,
    };
    let fence = MemoryFence {
        state: reserved,
        fail_commit: false,
        swaps: 0,
    };
    let owner = FencedFinalHoldoutOwnerV1::reconcile_pending(journal, fence, &frozen).unwrap();
    assert_eq!(owner.anchor().sequence, 1);
    let (journal, mut fence) = owner.into_parts();
    assert_eq!(fence.load().unwrap().committed_anchor, journal.anchor());
    assert!(fence.load().unwrap().pending_plan_digest.is_zero());

    // Crash/lost acknowledgement after journal sync: the replay proves the
    // pending plan is exactly the durable record before the fence advances.
    let after = Directory::new();
    let mut journal = after.create();
    let frozen = plan("plan-after-sync");
    let old = journal.anchor();
    journal.consume(old, &frozen).unwrap();
    let reserved = HoldoutFenceStateV1 {
        epoch: 20,
        committed_anchor: old,
        pending_plan_digest: frozen.plan_digest,
    };
    let fence = MemoryFence {
        state: reserved,
        fail_commit: false,
        swaps: 0,
    };
    let mut owner = FencedFinalHoldoutOwnerV1::reconcile_pending(journal, fence, &frozen).unwrap();
    assert_eq!(
        owner.consume(&frozen).unwrap().disposition,
        HoldoutUseDispositionV1::IdempotentReplay
    );
}
