//! Multi-host ownership contract for final-holdout consumption.
//!
//! The semantic journal already provides an expected-head compare-and-swap
//! contract. This adapter adds the missing deployment boundary: an external
//! store must atomically fence owners and persist journal snapshots. A backend
//! implementation may use a transactional database, consensus KV, or a
//! dedicated holdout service. The local-file adapter is intentionally not an
//! implementation of this trait because filesystem locks only serialize
//! cooperating handles on one host.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::CrossFoldPlanReceiptV1;
use crate::FinalHoldoutJournalError;
use crate::FinalHoldoutJournalReceiptV1;
use crate::FinalHoldoutJournalSnapshotV1;
use crate::FinalHoldoutJournalV1;
use crate::HoldoutUseDispositionV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FencedHoldoutStateV1 {
    pub generation: u64,
    pub fencing_token: u64,
    pub snapshot: FinalHoldoutJournalSnapshotV1,
}

impl FencedHoldoutStateV1 {
    #[must_use]
    pub fn empty() -> Self {
        Self {
            generation: 0,
            fencing_token: 0,
            snapshot: FinalHoldoutJournalSnapshotV1 {
                records: Vec::new(),
                head_digest: Digest32::ZERO,
            },
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FencedFinalHoldoutReceiptV1 {
    pub journal_receipt: FinalHoldoutJournalReceiptV1,
    pub generation: u64,
    pub fencing_token: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FencedHoldoutStoreError {
    Binding,
    StaleFence,
    Conflict,
    Corrupt,
    Backend,
}

impl fmt::Display for FencedHoldoutStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for FencedHoldoutStoreError {}

/// Durable store contract required for multi-host final-holdout ownership.
///
/// `claim_fence` must atomically reject fencing tokens that are not newer than
/// the active token for `binding`. `validate_fence` must atomically reject a
/// stale owner without changing state. `compare_and_swap` must atomically
/// require all of `expected_generation`, `expected_head_digest`, and
/// `fencing_token` before replacing the snapshot. Backends must durably commit
/// the replacement before returning success.
pub trait FencedFinalHoldoutStoreV1 {
    fn load(&mut self, binding: Digest32) -> Result<FencedHoldoutStateV1, FencedHoldoutStoreError>;

    fn claim_fence(
        &mut self,
        binding: Digest32,
        expected_generation: u64,
        expected_head_digest: Digest32,
        fencing_token: u64,
    ) -> Result<FencedHoldoutStateV1, FencedHoldoutStoreError>;

    fn validate_fence(
        &mut self,
        binding: Digest32,
        expected_generation: u64,
        expected_head_digest: Digest32,
        fencing_token: u64,
    ) -> Result<FencedHoldoutStateV1, FencedHoldoutStoreError>;

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected_generation: u64,
        expected_head_digest: Digest32,
        fencing_token: u64,
        replacement: &FinalHoldoutJournalSnapshotV1,
    ) -> Result<FencedHoldoutStateV1, FencedHoldoutStoreError>;
}

#[derive(Debug)]
pub enum FencedHoldoutOwnerError {
    Store(FencedHoldoutStoreError),
    Journal(FinalHoldoutJournalError),
    Protocol,
}

impl fmt::Display for FencedHoldoutOwnerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for FencedHoldoutOwnerError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Store(error) => Some(error),
            Self::Journal(error) => Some(error),
            Self::Protocol => None,
        }
    }
}

impl From<FencedHoldoutStoreError> for FencedHoldoutOwnerError {
    fn from(value: FencedHoldoutStoreError) -> Self {
        Self::Store(value)
    }
}

impl From<FinalHoldoutJournalError> for FencedHoldoutOwnerError {
    fn from(value: FinalHoldoutJournalError) -> Self {
        Self::Journal(value)
    }
}

/// Single active owner over a store that provides atomic fencing and CAS.
pub struct FencedFinalHoldoutOwnerV1<S> {
    store: S,
    binding: Digest32,
    generation: u64,
    fencing_token: u64,
    journal: FinalHoldoutJournalV1,
}

impl<S: FencedFinalHoldoutStoreV1> FencedFinalHoldoutOwnerV1<S> {
    pub fn open(
        mut store: S,
        binding: Digest32,
        fencing_token: u64,
    ) -> Result<Self, FencedHoldoutOwnerError> {
        if binding.is_zero() || fencing_token == 0 {
            return Err(FencedHoldoutStoreError::Binding.into());
        }
        let loaded = store.load(binding)?;
        let loaded_journal = FinalHoldoutJournalV1::from_snapshot(loaded.snapshot.clone())?;
        if loaded_journal.head_digest() != loaded.snapshot.head_digest {
            return Err(FencedHoldoutOwnerError::Protocol);
        }
        let claimed = store.claim_fence(
            binding,
            loaded.generation,
            loaded.snapshot.head_digest,
            fencing_token,
        )?;
        if claimed.generation != loaded.generation
            || claimed.fencing_token != fencing_token
            || claimed.snapshot != loaded.snapshot
        {
            return Err(FencedHoldoutOwnerError::Protocol);
        }
        Ok(Self {
            store,
            binding,
            generation: claimed.generation,
            fencing_token,
            journal: loaded_journal,
        })
    }

    #[must_use]
    pub fn generation(&self) -> u64 {
        self.generation
    }

    #[must_use]
    pub fn fencing_token(&self) -> u64 {
        self.fencing_token
    }

    #[must_use]
    pub fn head_digest(&self) -> Digest32 {
        self.journal.head_digest()
    }

    pub fn consume(
        &mut self,
        plan: &CrossFoldPlanReceiptV1,
    ) -> Result<FencedFinalHoldoutReceiptV1, FencedHoldoutOwnerError> {
        let expected_head = self.journal.head_digest();
        let mut candidate = self.journal.clone();
        let receipt = candidate.consume(expected_head, plan)?;
        if receipt.disposition == HoldoutUseDispositionV1::IdempotentReplay {
            let current = self.store.validate_fence(
                self.binding,
                self.generation,
                expected_head,
                self.fencing_token,
            )?;
            if current.generation != self.generation
                || current.fencing_token != self.fencing_token
                || current.snapshot != self.journal.snapshot()
            {
                return Err(FencedHoldoutOwnerError::Protocol);
            }
            return Ok(FencedFinalHoldoutReceiptV1 {
                journal_receipt: receipt,
                generation: self.generation,
                fencing_token: self.fencing_token,
            });
        }
        let replacement = candidate.snapshot();
        let committed = self.store.compare_and_swap(
            self.binding,
            self.generation,
            expected_head,
            self.fencing_token,
            &replacement,
        )?;
        let expected_generation = self
            .generation
            .checked_add(1)
            .ok_or(FencedHoldoutOwnerError::Protocol)?;
        if committed.generation != expected_generation
            || committed.fencing_token != self.fencing_token
            || committed.snapshot != replacement
        {
            return Err(FencedHoldoutOwnerError::Protocol);
        }
        self.generation = committed.generation;
        self.journal = candidate;
        Ok(FencedFinalHoldoutReceiptV1 {
            journal_receipt: receipt,
            generation: self.generation,
            fencing_token: self.fencing_token,
        })
    }

    #[must_use]
    pub fn into_store(self) -> S {
        self.store
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;
    use std::sync::Mutex;

    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::StableId;

    use super::*;
    use crate::CrossFoldPartitionV1;
    use crate::CrossFoldPlanV1;
    use crate::EvaluationClaimScopeV1;
    use crate::EvaluationDirectionV1;
    use crate::MetricContractV1;
    use crate::freeze_cross_fold_plan;

    #[derive(Clone)]
    struct MemoryStore {
        inner: Arc<Mutex<MemoryState>>,
    }

    struct MemoryState {
        binding: Option<Digest32>,
        state: FencedHoldoutStateV1,
    }

    impl MemoryStore {
        fn new() -> Self {
            Self {
                inner: Arc::new(Mutex::new(MemoryState {
                    binding: None,
                    state: FencedHoldoutStateV1::empty(),
                })),
            }
        }
    }

    impl FencedFinalHoldoutStoreV1 for MemoryStore {
        fn load(
            &mut self,
            binding: Digest32,
        ) -> Result<FencedHoldoutStateV1, FencedHoldoutStoreError> {
            if binding.is_zero() {
                return Err(FencedHoldoutStoreError::Binding);
            }
            let state = self.inner.lock().map_err(|_| FencedHoldoutStoreError::Backend)?;
            if state.binding.is_some_and(|bound| bound != binding) {
                return Err(FencedHoldoutStoreError::Binding);
            }
            Ok(state.state.clone())
        }

        fn claim_fence(
            &mut self,
            binding: Digest32,
            expected_generation: u64,
            expected_head_digest: Digest32,
            fencing_token: u64,
        ) -> Result<FencedHoldoutStateV1, FencedHoldoutStoreError> {
            let mut state = self.inner.lock().map_err(|_| FencedHoldoutStoreError::Backend)?;
            if state.binding.is_some_and(|bound| bound != binding) {
                return Err(FencedHoldoutStoreError::Binding);
            }
            if state.state.generation != expected_generation
                || state.state.snapshot.head_digest != expected_head_digest
            {
                return Err(FencedHoldoutStoreError::Conflict);
            }
            if fencing_token <= state.state.fencing_token {
                return Err(FencedHoldoutStoreError::StaleFence);
            }
            state.binding = Some(binding);
            state.state.fencing_token = fencing_token;
            Ok(state.state.clone())
        }

        fn validate_fence(
            &mut self,
            binding: Digest32,
            expected_generation: u64,
            expected_head_digest: Digest32,
            fencing_token: u64,
        ) -> Result<FencedHoldoutStateV1, FencedHoldoutStoreError> {
            let state = self.inner.lock().map_err(|_| FencedHoldoutStoreError::Backend)?;
            if state.binding != Some(binding) {
                return Err(FencedHoldoutStoreError::Binding);
            }
            if state.state.fencing_token != fencing_token {
                return Err(FencedHoldoutStoreError::StaleFence);
            }
            if state.state.generation != expected_generation
                || state.state.snapshot.head_digest != expected_head_digest
            {
                return Err(FencedHoldoutStoreError::Conflict);
            }
            Ok(state.state.clone())
        }

        fn compare_and_swap(
            &mut self,
            binding: Digest32,
            expected_generation: u64,
            expected_head_digest: Digest32,
            fencing_token: u64,
            replacement: &FinalHoldoutJournalSnapshotV1,
        ) -> Result<FencedHoldoutStateV1, FencedHoldoutStoreError> {
            let mut state = self.inner.lock().map_err(|_| FencedHoldoutStoreError::Backend)?;
            if state.binding != Some(binding) {
                return Err(FencedHoldoutStoreError::Binding);
            }
            if fencing_token != state.state.fencing_token {
                return Err(FencedHoldoutStoreError::StaleFence);
            }
            if state.state.generation != expected_generation
                || state.state.snapshot.head_digest != expected_head_digest
            {
                return Err(FencedHoldoutStoreError::Conflict);
            }
            FinalHoldoutJournalV1::from_snapshot(replacement.clone())
                .map_err(|_| FencedHoldoutStoreError::Corrupt)?;
            state.state.generation = state
                .state
                .generation
                .checked_add(1)
                .ok_or(FencedHoldoutStoreError::Backend)?;
            state.state.snapshot = replacement.clone();
            Ok(state.state.clone())
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn frozen_plan(name: &str) -> CrossFoldPlanReceiptV1 {
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
            folds: vec![
                CrossFoldPartitionV1 {
                    fold_id: id("fold-a"),
                    training_principals: vec![id("principal-b")],
                    training_episodes: vec![id("episode-b")],
                    training_windows: vec![id("train-a")],
                    holdout_principals: vec![id("principal-a")],
                    holdout_episodes: vec![id("episode-a")],
                    holdout_windows: vec![id("holdout-a")],
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
                    holdout_windows: vec![id(name)],
                    model_digest: digest("model-b"),
                    predictions_digest: digest("predictions-b"),
                },
            ],
            final_holdout_window_id: id(name),
            final_holdout_digest: digest(name),
        })
        .expect("plan freezes")
    }

    #[test]
    fn newer_owner_fences_stale_multi_host_writer() {
        let store = MemoryStore::new();
        let binding = digest("distributed-holdout");
        let mut stale = FencedFinalHoldoutOwnerV1::open(store.clone(), binding, 1)
            .expect("first owner claims fence");
        let mut active = FencedFinalHoldoutOwnerV1::open(store.clone(), binding, 2)
            .expect("new owner advances fence");
        assert!(matches!(
            stale.consume(&frozen_plan("stale-plan")),
            Err(FencedHoldoutOwnerError::Store(
                FencedHoldoutStoreError::StaleFence
            ))
        ));
        let receipt = active
            .consume(&frozen_plan("active-plan"))
            .expect("active owner commits");
        assert_eq!(
            receipt.journal_receipt.disposition,
            HoldoutUseDispositionV1::Recorded
        );
        assert_eq!(receipt.fencing_token, 2);
        assert_eq!(active.generation(), 1);
    }

    #[test]
    fn failed_store_cas_does_not_advance_local_journal() {
        let store = MemoryStore::new();
        let binding = digest("cas-holdout");
        let mut owner = FencedFinalHoldoutOwnerV1::open(store.clone(), binding, 7)
            .expect("owner claims fence");
        let _newer = FencedFinalHoldoutOwnerV1::open(store, binding, 8)
            .expect("newer owner claims fence");
        let before = owner.head_digest();
        assert!(owner.consume(&frozen_plan("blocked-plan")).is_err());
        assert_eq!(owner.head_digest(), before);
        assert_eq!(owner.generation(), 0);
    }

    #[test]
    fn stale_owner_cannot_return_idempotent_replay_after_fence_takeover() {
        let store = MemoryStore::new();
        let binding = digest("replay-holdout");
        let mut stale = FencedFinalHoldoutOwnerV1::open(store.clone(), binding, 10)
            .expect("first owner claims fence");
        let plan = frozen_plan("plan-1");
        let recorded = stale.consume(&plan).expect("first consume");
        assert_eq!(recorded.generation, 1);
        let mut active = FencedFinalHoldoutOwnerV1::open(store, binding, 11)
            .expect("new owner advances fence");
        assert!(matches!(
            stale.consume(&plan),
            Err(FencedHoldoutOwnerError::Store(
                FencedHoldoutStoreError::StaleFence
            ))
        ));
        let replay = active.consume(&plan).expect("active replay");
        assert_eq!(
            replay.journal_receipt.disposition,
            HoldoutUseDispositionV1::IdempotentReplay
        );
        assert_eq!(replay.fencing_token, 11);
        assert_eq!(replay.generation, 1);
    }
}
