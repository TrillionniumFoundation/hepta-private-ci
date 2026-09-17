//! Host composition for durable final-holdout use.
//!
//! The journal fsyncs semantic consumption; this owner additionally requires an
//! independently retained compare-and-store anchor before a successful receipt
//! is returned. A host may back the anchor store with a separate database,
//! quorum, transparency log, or other durability domain. The trait cannot prove
//! that independence by itself, so qualification must still authenticate the
//! concrete store and its currentness.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;

use codex_hepta_types::Digest32;

use crate::closure::CrossFoldPlanReceiptV1;
use crate::durable_holdout::DurableFinalHoldoutJournalV1;
use crate::durable_holdout::DurableHoldoutError;
use crate::durable_holdout::HoldoutAnchorV1;
use crate::holdout_journal::FinalHoldoutJournalReceiptV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HoldoutAnchorStoreErrorV1 {
    Conflict,
    Unavailable,
    Indeterminate,
}

impl fmt::Display for HoldoutAnchorStoreErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for HoldoutAnchorStoreErrorV1 {}

/// Independently retained current-head state for final-holdout consumption.
///
/// `compare_and_store` must be durable before it returns `Ok(())`. It must only
/// replace `expected` with `next` when the currently retained value equals
/// `expected`; implementations must not silently perform last-write-wins.
pub trait HoldoutAnchorStoreV1 {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<HoldoutAnchorV1>, HoldoutAnchorStoreErrorV1>;

    fn compare_and_store(
        &mut self,
        binding: Digest32,
        expected: Option<HoldoutAnchorV1>,
        next: HoldoutAnchorV1,
    ) -> Result<(), HoldoutAnchorStoreErrorV1>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableHoldoutOwnerErrorV1 {
    Binding,
    MissingIndependentAnchor,
    AnchorMismatch,
    AnchorStore(HoldoutAnchorStoreErrorV1),
    AnchorCommit(HoldoutAnchorStoreErrorV1),
    Journal(DurableHoldoutError),
    Poisoned,
}

impl fmt::Display for DurableHoldoutOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for DurableHoldoutOwnerErrorV1 {}
impl From<DurableHoldoutError> for DurableHoldoutOwnerErrorV1 {
    fn from(error: DurableHoldoutError) -> Self {
        Self::Journal(error)
    }
}

/// Product-facing owner that couples the synced journal to an independently
/// durable anchor store. This type still grants no selection or release power.
pub struct DurableFinalHoldoutOwnerV1<S: HoldoutAnchorStoreV1> {
    binding: Digest32,
    journal: DurableFinalHoldoutJournalV1,
    anchors: S,
    poisoned: bool,
}

impl<S: HoldoutAnchorStoreV1> DurableFinalHoldoutOwnerV1<S> {
    /// Initialize both durability domains. A failed anchor commit leaves the
    /// journal initialized but does not return a usable owner; `recover` is the
    /// only valid follow-up.
    pub fn create(
        file: File,
        binding: Digest32,
        mut anchors: S,
    ) -> Result<Self, DurableHoldoutOwnerErrorV1> {
        if binding.is_zero() {
            return Err(DurableHoldoutOwnerErrorV1::Binding);
        }
        if anchors
            .load(binding)
            .map_err(DurableHoldoutOwnerErrorV1::AnchorStore)?
            .is_some()
        {
            return Err(DurableHoldoutOwnerErrorV1::AnchorMismatch);
        }
        let journal = DurableFinalHoldoutJournalV1::create(file, binding)?;
        let current = journal.anchor();
        anchors
            .compare_and_store(binding, None, current)
            .map_err(DurableHoldoutOwnerErrorV1::AnchorCommit)?;
        Ok(Self {
            binding,
            journal,
            anchors,
            poisoned: false,
        })
    }

    /// Recover against the independently retained minimum anchor. If a crash
    /// happened after journal fsync but before anchor acknowledgement, replay
    /// proves the retained anchor is a prefix and this method atomically advances
    /// the external anchor before returning a usable owner.
    pub fn recover(
        file: File,
        binding: Digest32,
        mut anchors: S,
    ) -> Result<Self, DurableHoldoutOwnerErrorV1> {
        if binding.is_zero() {
            return Err(DurableHoldoutOwnerErrorV1::Binding);
        }
        let acknowledged = anchors
            .load(binding)
            .map_err(DurableHoldoutOwnerErrorV1::AnchorStore)?;
        let minimum = acknowledged.unwrap_or(HoldoutAnchorV1 {
            sequence: 0,
            head: Digest32::ZERO,
        });
        let journal = DurableFinalHoldoutJournalV1::recover(file, binding, minimum)?;
        let current = journal.anchor();
        match acknowledged {
            None if current.sequence != 0 => {
                return Err(DurableHoldoutOwnerErrorV1::MissingIndependentAnchor);
            }
            None => anchors
                .compare_and_store(binding, None, current)
                .map_err(DurableHoldoutOwnerErrorV1::AnchorCommit)?,
            Some(anchor) if anchor != current => anchors
                .compare_and_store(binding, Some(anchor), current)
                .map_err(DurableHoldoutOwnerErrorV1::AnchorCommit)?,
            Some(_) => {}
        }
        Ok(Self {
            binding,
            journal,
            anchors,
            poisoned: false,
        })
    }

    /// Consume a frozen plan and durably advance the independent anchor before
    /// exposing a successful receipt. If the second durability domain is
    /// uncertain after journal fsync, this handle is fenced and the caller must
    /// reopen through `recover` before any confirmatory label is released.
    pub fn consume(
        &mut self,
        plan: &CrossFoldPlanReceiptV1,
    ) -> Result<FinalHoldoutJournalReceiptV1, DurableHoldoutOwnerErrorV1> {
        if self.poisoned {
            return Err(DurableHoldoutOwnerErrorV1::Poisoned);
        }
        let expected = self.journal.anchor();
        let acknowledged = self
            .anchors
            .load(self.binding)
            .map_err(DurableHoldoutOwnerErrorV1::AnchorStore)?;
        if acknowledged != Some(expected) {
            self.poisoned = true;
            return Err(DurableHoldoutOwnerErrorV1::AnchorMismatch);
        }
        let receipt = self.journal.consume(expected, plan)?;
        let next = self.journal.anchor();
        if next != expected
            && let Err(error) = self.anchors.compare_and_store(
                self.binding,
                Some(expected),
                next,
            )
        {
            self.poisoned = true;
            return Err(DurableHoldoutOwnerErrorV1::AnchorCommit(error));
        }
        Ok(receipt)
    }

    pub fn anchor(&self) -> HoldoutAnchorV1 {
        self.journal.anchor()
    }
}

#[cfg(test)]
mod tests {
    use std::fs::OpenOptions;
    use std::fs::{self};
    use std::path::PathBuf;
    use std::sync::Arc;
    use std::sync::Mutex;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

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

    static NEXT: AtomicU64 = AtomicU64::new(0);

    struct Directory(PathBuf);
    impl Directory {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "hepta-owned-holdout-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir(&path).unwrap();
            Self(path)
        }

        fn path(&self) -> PathBuf {
            self.0.join("holdout")
        }

        fn create_file(&self) -> File {
            OpenOptions::new()
                .create_new(true)
                .read(true)
                .write(true)
                .open(self.path())
                .unwrap()
        }

        fn file(&self) -> File {
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(self.path())
                .unwrap()
        }
    }
    impl Drop for Directory {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[derive(Clone, Default)]
    struct MemoryAnchors(Arc<Mutex<AnchorState>>);
    #[derive(Default)]
    struct AnchorState {
        binding: Option<Digest32>,
        anchor: Option<HoldoutAnchorV1>,
        fail_next_commit: bool,
    }
    impl MemoryAnchors {
        fn anchor(&self) -> Option<HoldoutAnchorV1> {
            self.0.lock().unwrap().anchor
        }

        fn fail_next_commit(&self) {
            self.0.lock().unwrap().fail_next_commit = true;
        }
    }
    impl HoldoutAnchorStoreV1 for MemoryAnchors {
        fn load(
            &mut self,
            binding: Digest32,
        ) -> Result<Option<HoldoutAnchorV1>, HoldoutAnchorStoreErrorV1> {
            let state = self.0.lock().unwrap();
            if state.binding.is_some_and(|stored| stored != binding) {
                return Err(HoldoutAnchorStoreErrorV1::Conflict);
            }
            Ok(state.anchor)
        }

        fn compare_and_store(
            &mut self,
            binding: Digest32,
            expected: Option<HoldoutAnchorV1>,
            next: HoldoutAnchorV1,
        ) -> Result<(), HoldoutAnchorStoreErrorV1> {
            let mut state = self.0.lock().unwrap();
            if state.binding.is_some_and(|stored| stored != binding) || state.anchor != expected {
                return Err(HoldoutAnchorStoreErrorV1::Conflict);
            }
            if state.fail_next_commit {
                state.fail_next_commit = false;
                return Err(HoldoutAnchorStoreErrorV1::Indeterminate);
            }
            state.binding = Some(binding);
            state.anchor = Some(next);
            Ok(())
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
    fn owner_commits_anchor_before_returning_receipt_and_retry_is_read_only() {
        let directory = Directory::new();
        let anchors = MemoryAnchors::default();
        let mut owner = DurableFinalHoldoutOwnerV1::create(
            directory.create_file(),
            digest("binding"),
            anchors.clone(),
        )
        .unwrap();
        assert_eq!(anchors.anchor(), Some(owner.anchor()));
        let receipt = owner.consume(&plan("plan-1")).unwrap();
        assert_eq!(receipt.disposition, HoldoutUseDispositionV1::Recorded);
        let committed = owner.anchor();
        assert_eq!(anchors.anchor(), Some(committed));
        let retry = owner.consume(&plan("plan-1")).unwrap();
        assert_eq!(retry.disposition, HoldoutUseDispositionV1::IdempotentReplay);
        assert_eq!(owner.anchor(), committed);
        assert_eq!(anchors.anchor(), Some(committed));
    }

    #[test]
    fn failed_anchor_commit_fences_owner_and_recovery_fast_forwards_prefix() {
        let directory = Directory::new();
        let anchors = MemoryAnchors::default();
        let mut owner = DurableFinalHoldoutOwnerV1::create(
            directory.create_file(),
            digest("binding"),
            anchors.clone(),
        )
        .unwrap();
        let old = owner.anchor();
        anchors.fail_next_commit();
        assert_eq!(
            owner.consume(&plan("plan-1")),
            Err(DurableHoldoutOwnerErrorV1::AnchorCommit(
                HoldoutAnchorStoreErrorV1::Indeterminate
            ))
        );
        assert_eq!(anchors.anchor(), Some(old));
        assert_eq!(
            owner.consume(&plan("plan-1")),
            Err(DurableHoldoutOwnerErrorV1::Poisoned)
        );
        drop(owner);

        let mut recovered = DurableFinalHoldoutOwnerV1::recover(
            directory.file(),
            digest("binding"),
            anchors.clone(),
        )
        .unwrap();
        assert_eq!(anchors.anchor(), Some(recovered.anchor()));
        assert_ne!(recovered.anchor(), old);
        assert!(matches!(
            recovered.consume(&plan("plan-2")),
            Err(DurableHoldoutOwnerErrorV1::Journal(
                DurableHoldoutError::Semantic
            ))
        ));
    }

    #[test]
    fn nonempty_journal_without_independent_anchor_is_not_adopted() {
        let directory = Directory::new();
        let mut journal = DurableFinalHoldoutJournalV1::create(
            directory.create_file(),
            digest("binding"),
        )
        .unwrap();
        journal.consume(journal.anchor(), &plan("plan-1")).unwrap();
        drop(journal);
        assert!(matches!(
            DurableFinalHoldoutOwnerV1::recover(
                directory.file(),
                digest("binding"),
                MemoryAnchors::default()
            ),
            Err(DurableHoldoutOwnerErrorV1::MissingIndependentAnchor)
        ));
    }
}
