use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::*;
use crate::CrossFoldPartitionV1;
use crate::CrossFoldPlanV1;
use crate::EvaluationClaimScopeV1;
use crate::EvaluationDirectionV1;
use crate::HoldoutUseDispositionV1;
use crate::MetricContractV1;
use crate::freeze_cross_fold_plan;

#[derive(Clone, Default)]
struct MemoryCas {
    inner: Arc<Mutex<MemoryState>>,
}

#[derive(Default)]
struct MemoryState {
    record: Option<FinalHoldoutCasRecordV1>,
    indeterminate_next: bool,
}

impl MemoryCas {
    fn make_next_write_indeterminate(&self) {
        self.inner.lock().expect("lock").indeterminate_next = true;
    }
}

impl FinalHoldoutCasStoreV1 for MemoryCas {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        let guard = self.inner.lock().map_err(|_| FinalHoldoutCasStoreError::Rejected)?;
        match &guard.record {
            Some(record) if record.binding != binding => Err(FinalHoldoutCasStoreError::Rejected),
            value => Ok(value.clone()),
        }
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
        let mut guard = self.inner.lock().map_err(|_| FinalHoldoutCasStoreError::Rejected)?;
        let actual = match &guard.record {
            Some(record) if record.binding == binding => Some(record.state_digest),
            Some(_) => return Err(FinalHoldoutCasStoreError::Rejected),
            None => None,
        };
        if actual != expected {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        guard.record = Some(next.clone());
        if guard.indeterminate_next {
            guard.indeterminate_next = false;
            return Err(FinalHoldoutCasStoreError::Indeterminate);
        }
        Ok(())
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn fence(owner: &str, generation: u64, lease: &str) -> HoldoutWriterFenceV1 {
    HoldoutWriterFenceV1 {
        owner_id: id(owner),
        generation,
        lease_digest: digest(lease),
    }
}

fn plan(name: &str) -> CrossFoldPlanReceiptV1 {
    freeze_cross_fold_plan(CrossFoldPlanV1 {
        plan_id: id(name),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        candidate_id: id(&format!("candidate-{name}")),
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
                training_principals: vec![id("principal-b")],
                training_episodes: vec![id("episode-b")],
                training_windows: vec![id("train-a")],
                holdout_principals: vec![id("principal-a")],
                holdout_episodes: vec![id("episode-a")],
                holdout_windows: vec![id(&format!("{name}-holdout-a"))],
                model_digest: digest("model-a"),
                predictions_digest: digest("predictions-a"),
            },
            CrossFoldPartitionV1 {
                fold_id: id("fold-b"),
                training_principals: vec![id("principal-a")],
                training_episodes: vec![id("episode-a")],
                training_windows: vec![id("train-b")],
                holdout_principals: vec![id("principal-b")],
                holdout_episodes: vec![id("episode-b")],
                holdout_windows: vec![id(&format!("{name}-holdout-b"))],
                model_digest: digest("model-b"),
                predictions_digest: digest("predictions-b"),
            },
        ],
        final_holdout_window_id: id(&format!("{name}-holdout-b")),
        final_holdout_digest: digest(&format!("{name}-holdout-bytes")),
    })
    .expect("plan freezes")
}

#[test]
fn newer_generation_fences_out_the_old_writer() {
    let binding = digest("production-holdout-scope");
    let store = MemoryCas::default();
    let mut old = FencedFinalHoldoutOwnerV1::initialize(
        store.clone(),
        binding,
        fence("owner-a", 1, "lease-a"),
    )
    .expect("initialize");
    let mut current = FencedFinalHoldoutOwnerV1::recover(
        store.clone(),
        binding,
        fence("owner-b", 2, "lease-b"),
    )
    .expect("take over");

    assert_eq!(old.consume(&plan("stale")), Err(FencedHoldoutError::Conflict));
    let accepted = current.consume(&plan("current")).expect("current owner");
    assert_eq!(accepted.disposition, HoldoutUseDispositionV1::Recorded);
}

#[test]
fn stale_or_same_generation_different_fence_cannot_take_over() {
    let binding = digest("production-holdout-scope");
    let store = MemoryCas::default();
    FencedFinalHoldoutOwnerV1::initialize(
        store.clone(),
        binding,
        fence("owner-a", 3, "lease-a"),
    )
    .expect("initialize");

    assert!(matches!(
        FencedFinalHoldoutOwnerV1::recover(
            store.clone(),
            binding,
            fence("owner-b", 2, "lease-b"),
        ),
        Err(FencedHoldoutError::StaleFence)
    ));
    assert!(matches!(
        FencedFinalHoldoutOwnerV1::recover(
            store,
            binding,
            fence("owner-b", 3, "lease-b"),
        ),
        Err(FencedHoldoutError::StaleFence)
    ));
}

#[test]
fn indeterminate_write_poison_requires_recovery_and_preserves_history() {
    let binding = digest("production-holdout-scope");
    let store = MemoryCas::default();
    let mut owner = FencedFinalHoldoutOwnerV1::initialize(
        store.clone(),
        binding,
        fence("owner-a", 1, "lease-a"),
    )
    .expect("initialize");
    let intended = plan("accepted-unknown");
    store.make_next_write_indeterminate();

    assert_eq!(
        owner.consume(&intended),
        Err(FencedHoldoutError::Indeterminate)
    );
    assert!(owner.is_poisoned());
    assert_eq!(owner.consume(&intended), Err(FencedHoldoutError::Poisoned));

    let mut recovered = FencedFinalHoldoutOwnerV1::recover(
        store,
        binding,
        fence("owner-b", 2, "lease-b"),
    )
    .expect("reconcile accepted unknown");
    let head = recovered.head_digest();
    let retry = recovered.consume(&intended).expect("exact retry");
    assert_eq!(retry.disposition, HoldoutUseDispositionV1::IdempotentReplay);
    assert_eq!(recovered.head_digest(), head);
}

#[test]
fn state_digest_changes_on_fence_takeover_without_rewriting_journal_head() {
    let binding = digest("production-holdout-scope");
    let store = MemoryCas::default();
    let mut first = FencedFinalHoldoutOwnerV1::initialize(
        store.clone(),
        binding,
        fence("owner-a", 1, "lease-a"),
    )
    .expect("initialize");
    first.consume(&plan("recorded")).expect("consume");
    let old_state = first.state_digest();
    let old_head = first.head_digest();

    let second = FencedFinalHoldoutOwnerV1::recover(
        store,
        binding,
        fence("owner-b", 2, "lease-b"),
    )
    .expect("take over");
    assert_ne!(second.state_digest(), old_state);
    assert_eq!(second.head_digest(), old_head);
}
