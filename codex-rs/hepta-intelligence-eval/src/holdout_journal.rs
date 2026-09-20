//! Replayable, predecessor-bound journal for final-holdout consumption.
//!
//! `FinalHoldoutRegistry` remains the pure semantic core. This journal adds an
//! explicit expected-head compare-and-swap contract plus deterministic snapshot
//! replay. A product adapter persists the snapshot under an exclusive writer;
//! the source type itself grants no filesystem or selection authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::CrossFoldPlanReceiptV1;
use crate::EvaluationClosureError;
use crate::FinalHoldoutRegistry;
use crate::HoldoutUseDispositionV1;
use crate::HoldoutUseReceiptV1;

const MAX_JOURNAL_RECORDS: usize = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalHoldoutJournalRecordV1 {
    pub sequence: u64,
    pub predecessor_head_digest: Digest32,
    pub record_digest: Digest32,
    pub plan: CrossFoldPlanReceiptV1,
    pub use_receipt: HoldoutUseReceiptV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalHoldoutJournalSnapshotV1 {
    pub records: Vec<FinalHoldoutJournalRecordV1>,
    pub head_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalHoldoutJournalReceiptV1 {
    pub disposition: HoldoutUseDispositionV1,
    pub sequence: u64,
    pub record_digest: Digest32,
    pub head_digest: Digest32,
    pub use_receipt: HoldoutUseReceiptV1,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug)]
pub struct FinalHoldoutJournalV1 {
    registry: FinalHoldoutRegistry,
    records: Vec<FinalHoldoutJournalRecordV1>,
    head_digest: Digest32,
    record_limit: usize,
}

impl Default for FinalHoldoutJournalV1 {
    fn default() -> Self {
        Self {
            registry: FinalHoldoutRegistry::default(),
            records: Vec::new(),
            head_digest: Digest32::ZERO,
            record_limit: MAX_JOURNAL_RECORDS,
        }
    }
}

impl FinalHoldoutJournalV1 {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Host-selected capacity is admission policy, not part of the journal wire format.
    /// Reopening with the same policy requires `from_snapshot_with_record_limit`.
    pub fn with_record_limit(record_limit: usize) -> Result<Self, FinalHoldoutJournalError> {
        if record_limit == 0 || record_limit > MAX_JOURNAL_RECORDS {
            return Err(FinalHoldoutJournalError::RecordLimit);
        }
        Ok(Self {
            record_limit,
            ..Self::default()
        })
    }

    #[must_use]
    pub fn head_digest(&self) -> Digest32 {
        self.head_digest
    }

    #[must_use]
    pub fn records(&self) -> &[FinalHoldoutJournalRecordV1] {
        &self.records
    }

    pub fn consume(
        &mut self,
        expected_head_digest: Digest32,
        plan: &CrossFoldPlanReceiptV1,
    ) -> Result<FinalHoldoutJournalReceiptV1, FinalHoldoutJournalError> {
        if expected_head_digest != self.head_digest {
            return Err(FinalHoldoutJournalError::HeadMismatch);
        }
        // Check every fallible admission condition before mutating the registry.
        // Existing plans may still be retried when the journal is full.
        if self.records.len() >= self.record_limit
            && !self
                .records
                .iter()
                .any(|record| record.plan.plan_id == plan.plan_id)
        {
            return Err(FinalHoldoutJournalError::RecordLimit);
        }
        let sequence = u64::try_from(self.records.len())
            .map_err(|_| FinalHoldoutJournalError::Arithmetic)?
            .checked_add(1)
            .ok_or(FinalHoldoutJournalError::Arithmetic)?;
        let use_receipt = self.registry.consume(plan)?;
        if use_receipt.disposition == HoldoutUseDispositionV1::IdempotentReplay {
            let existing = self
                .records
                .iter()
                .find(|record| record.plan.plan_id == plan.plan_id)
                .ok_or(FinalHoldoutJournalError::InternalInvariant)?;
            if existing.plan.plan_digest != plan.plan_digest
                || existing.use_receipt.use_digest != use_receipt.use_digest
            {
                return Err(FinalHoldoutJournalError::InternalInvariant);
            }
            return Ok(FinalHoldoutJournalReceiptV1 {
                disposition: HoldoutUseDispositionV1::IdempotentReplay,
                sequence: existing.sequence,
                record_digest: existing.record_digest,
                head_digest: self.head_digest,
                use_receipt,
                authority: AuthorityPosture::DENY_ALL,
            });
        }
        let predecessor_head_digest = self.head_digest;
        let record_digest = digest_record(
            sequence,
            predecessor_head_digest,
            plan.plan_digest,
            use_receipt.use_digest,
        );
        let record = FinalHoldoutJournalRecordV1 {
            sequence,
            predecessor_head_digest,
            record_digest,
            plan: plan.clone(),
            use_receipt: use_receipt.clone(),
        };
        self.records.push(record);
        self.head_digest = record_digest;
        Ok(FinalHoldoutJournalReceiptV1 {
            disposition: HoldoutUseDispositionV1::Recorded,
            sequence,
            record_digest,
            head_digest: self.head_digest,
            use_receipt,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    #[must_use]
    pub fn snapshot(&self) -> FinalHoldoutJournalSnapshotV1 {
        FinalHoldoutJournalSnapshotV1 {
            records: self.records.clone(),
            head_digest: self.head_digest,
        }
    }

    pub fn from_snapshot(
        snapshot: FinalHoldoutJournalSnapshotV1,
    ) -> Result<Self, FinalHoldoutJournalError> {
        Self::from_snapshot_with_record_limit(snapshot, MAX_JOURNAL_RECORDS)
    }

    pub fn from_snapshot_with_record_limit(
        snapshot: FinalHoldoutJournalSnapshotV1,
        record_limit: usize,
    ) -> Result<Self, FinalHoldoutJournalError> {
        let expected_head = snapshot.head_digest;
        let mut journal = Self::with_record_limit(record_limit)?;
        if snapshot.records.len() > record_limit {
            return Err(FinalHoldoutJournalError::RecordLimit);
        }
        for expected in snapshot.records {
            if expected.sequence
                != u64::try_from(journal.records.len())
                    .map_err(|_| FinalHoldoutJournalError::Arithmetic)?
                    .checked_add(1)
                    .ok_or(FinalHoldoutJournalError::Arithmetic)?
                || expected.predecessor_head_digest != journal.head_digest
            {
                return Err(FinalHoldoutJournalError::SnapshotMismatch);
            }
            let receipt = journal.consume(journal.head_digest, &expected.plan)?;
            let actual = journal
                .records
                .last()
                .ok_or(FinalHoldoutJournalError::InternalInvariant)?;
            if receipt.disposition != HoldoutUseDispositionV1::Recorded || actual != &expected {
                return Err(FinalHoldoutJournalError::SnapshotMismatch);
            }
        }
        if journal.head_digest != expected_head {
            return Err(FinalHoldoutJournalError::SnapshotMismatch);
        }
        Ok(journal)
    }
}

fn digest_record(
    sequence: u64,
    predecessor_head_digest: Digest32,
    plan_digest: Digest32,
    use_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.final-holdout-journal.v1".to_vec();
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(predecessor_head_digest.as_array());
    bytes.extend_from_slice(plan_digest.as_array());
    bytes.extend_from_slice(use_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FinalHoldoutJournalError {
    Evaluation(EvaluationClosureError),
    HeadMismatch,
    RecordLimit,
    SnapshotMismatch,
    InternalInvariant,
    Arithmetic,
}

impl fmt::Display for FinalHoldoutJournalError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for FinalHoldoutJournalError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Evaluation(error) => Some(error),
            Self::HeadMismatch
            | Self::RecordLimit
            | Self::SnapshotMismatch
            | Self::InternalInvariant
            | Self::Arithmetic => None,
        }
    }
}

impl From<EvaluationClosureError> for FinalHoldoutJournalError {
    fn from(value: EvaluationClosureError) -> Self {
        Self::Evaluation(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::StableId;
    use pretty_assertions::assert_eq;

    use crate::CrossFoldPartitionV1;
    use crate::CrossFoldPlanV1;
    use crate::EvaluationClaimScopeV1;
    use crate::EvaluationDirectionV1;
    use crate::MetricContractV1;
    use crate::freeze_cross_fold_plan;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid test id")
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
    fn eval_05_holdout_journal_reopens_exactly() {
        let plan = frozen_plan("journal-plan");
        let mut journal = FinalHoldoutJournalV1::new();
        let first = journal
            .consume(Digest32::ZERO, &plan)
            .expect("first consume succeeds");
        let reopened =
            FinalHoldoutJournalV1::from_snapshot(journal.snapshot()).expect("snapshot reopens");
        assert_eq!(reopened.head_digest(), first.head_digest);
        assert_eq!(reopened.records().len(), 1);
    }

    #[test]
    fn eval_05_holdout_journal_rejects_stale_head_and_keeps_retry_idempotent() {
        let plan = frozen_plan("journal-plan");
        let mut journal = FinalHoldoutJournalV1::new();
        let first = journal
            .consume(Digest32::ZERO, &plan)
            .expect("first consume succeeds");
        assert_eq!(
            journal.consume(Digest32::ZERO, &plan),
            Err(FinalHoldoutJournalError::HeadMismatch)
        );
        let retry = journal
            .consume(first.head_digest, &plan)
            .expect("exact retry succeeds");
        assert_eq!(retry.disposition, HoldoutUseDispositionV1::IdempotentReplay);
        assert_eq!(journal.records().len(), 1);
    }
    #[test]
    fn capacity_failure_does_not_consume_holdout_or_break_full_journal_retry() {
        let first_plan = frozen_plan("first-plan");
        let next_plan = frozen_plan("next-plan");
        let mut journal = FinalHoldoutJournalV1::with_record_limit(1).expect("valid capacity");
        journal
            .consume(Digest32::ZERO, &first_plan)
            .expect("first admission");
        let before = journal.snapshot();
        let registry_before = journal.registry.digest();
        assert_eq!(
            journal.consume(journal.head_digest(), &next_plan),
            Err(FinalHoldoutJournalError::RecordLimit)
        );
        assert_eq!(journal.snapshot(), before);
        // Registry state must not contain the failed admission, including its digest.
        assert_eq!(journal.registry.digest(), registry_before);
        let replay = journal
            .consume(journal.head_digest(), &first_plan)
            .expect("retry at capacity");
        assert_eq!(
            replay.disposition,
            HoldoutUseDispositionV1::IdempotentReplay
        );
        assert_eq!(journal.snapshot(), before);
        let mut reopened = FinalHoldoutJournalV1::from_snapshot_with_record_limit(before, 2)
            .expect("host raises capacity");
        assert_eq!(
            reopened
                .consume(reopened.head_digest(), &next_plan)
                .expect("second admission")
                .disposition,
            HoldoutUseDispositionV1::Recorded
        );
    }
}
