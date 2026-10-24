//! Shared journal envelope for the existing fenced owner.
//! Legacy OPE plans keep their own validation, receipt and exact record hashes.
//! Paired and OPE plans share plan/window/cohort reuse checks and one CAS head.

use crate::CrossFoldPlanReceiptV1;
use crate::EvaluationClosureError;
use crate::FinalHoldoutJournalError;
use crate::FinalHoldoutJournalReceiptV1;
use crate::FinalHoldoutJournalSnapshotV1;
use crate::FinalHoldoutJournalV1;
use crate::FinalHoldoutRegistry;
use crate::HoldoutUseDispositionV1;
use crate::HoldoutUseReceiptV1;
use crate::paired_plan::FrozenPairedPlanV1;
use crate::paired_plan::seal;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum HoldoutPlanEnvelopeV2 {
    CrossFold(Box<CrossFoldPlanReceiptV1>),
    Paired(Box<FrozenPairedPlanV1>),
}
impl HoldoutPlanEnvelopeV2 {
    fn identity(&self) -> (&StableId, &StableId, Digest32) {
        match self {
            Self::CrossFold(p) => (
                &p.plan_id,
                &p.final_holdout_window_id,
                p.final_holdout_digest,
            ),
            Self::Paired(p) => (
                &p.spec().plan_id,
                &p.spec().holdout_window_id,
                p.spec().holdout_digest,
            ),
        }
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum HoldoutUseEnvelopeV2 {
    CrossFold(Box<HoldoutUseReceiptV1>),
    Paired(Digest32),
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HoldoutJournalRecordV2 {
    pub sequence: u64,
    pub predecessor_head_digest: Digest32,
    pub record_digest: Digest32,
    pub plan: HoldoutPlanEnvelopeV2,
    pub use_receipt: HoldoutUseEnvelopeV2,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HoldoutJournalSnapshotV2 {
    pub records: Vec<HoldoutJournalRecordV2>,
    pub head_digest: Digest32,
}
impl TryFrom<FinalHoldoutJournalSnapshotV1> for HoldoutJournalSnapshotV2 {
    type Error = FinalHoldoutJournalError;
    fn try_from(snapshot: FinalHoldoutJournalSnapshotV1) -> Result<Self, Self::Error> {
        // Validate the original V1 semantics before wrapping; no old hashes or
        // receipts are reinterpreted as paired observations.
        let legacy = FinalHoldoutJournalV1::from_snapshot(snapshot)?;
        let records = legacy
            .records()
            .iter()
            .map(|r| HoldoutJournalRecordV2 {
                sequence: r.sequence,
                predecessor_head_digest: r.predecessor_head_digest,
                record_digest: r.record_digest,
                plan: HoldoutPlanEnvelopeV2::CrossFold(Box::new(r.plan.clone())),
                use_receipt: HoldoutUseEnvelopeV2::CrossFold(Box::new(r.use_receipt.clone())),
            })
            .collect();
        let upgraded = Self {
            records,
            head_digest: legacy.head_digest(),
        };
        Ok(HoldoutJournalV2::from_snapshot_with_record_limit(upgraded, 1_000_000)?.snapshot())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedHoldoutJournalReceiptV1 {
    pub disposition: HoldoutUseDispositionV1,
    pub sequence: u64,
    pub record_digest: Digest32,
    pub head_digest: Digest32,
    pub plan: FrozenPairedPlanV1,
    pub authority: AuthorityPosture,
    receipt_seal: Digest32,
}
impl PairedHoldoutJournalReceiptV1 {
    pub fn validate(&self, plan: &FrozenPairedPlanV1) -> Result<(), FinalHoldoutJournalError> {
        plan.validate()
            .map_err(|_| FinalHoldoutJournalError::SnapshotMismatch)?;
        if &self.plan != plan
            || self.sequence == 0
            || self.record_digest.is_zero()
            || self.head_digest.is_zero()
            || self.authority.grants_any()
            || self.receipt_seal != paired_receipt_seal(self)
        {
            return Err(FinalHoldoutJournalError::SnapshotMismatch);
        }
        Ok(())
    }
}

fn paired_receipt_seal(r: &PairedHoldoutJournalReceiptV1) -> Digest32 {
    let tag = match r.disposition {
        HoldoutUseDispositionV1::Recorded => 0,
        HoldoutUseDispositionV1::IdempotentReplay => 1,
    };
    let count = Digest32::of_bytes(&[r.sequence.to_be_bytes().as_slice(), &[tag]].concat());
    seal(
        b"hepta.paired-full-information.consumption.v1",
        &[r.plan.plan_digest(), count, r.record_digest, r.head_digest],
    )
}

#[derive(Clone, Debug)]
pub(crate) struct HoldoutJournalV2 {
    legacy: FinalHoldoutRegistry,
    records: Vec<HoldoutJournalRecordV2>,
    head: Digest32,
    limit: usize,
}
impl HoldoutJournalV2 {
    pub(crate) fn with_record_limit(limit: usize) -> Result<Self, FinalHoldoutJournalError> {
        if !(1..=1_000_000).contains(&limit) {
            return Err(FinalHoldoutJournalError::RecordLimit);
        }
        Ok(Self {
            legacy: FinalHoldoutRegistry::new(),
            records: Vec::new(),
            head: Digest32::ZERO,
            limit,
        })
    }
    pub(crate) fn head_digest(&self) -> Digest32 {
        self.head
    }
    pub(crate) fn records(&self) -> &[HoldoutJournalRecordV2] {
        &self.records
    }
    pub(crate) fn snapshot(&self) -> HoldoutJournalSnapshotV2 {
        HoldoutJournalSnapshotV2 {
            records: self.records.clone(),
            head_digest: self.head,
        }
    }
    fn preflight(
        &self,
        expected: Digest32,
        plan: &HoldoutPlanEnvelopeV2,
    ) -> Result<Option<usize>, FinalHoldoutJournalError> {
        if expected != self.head {
            return Err(FinalHoldoutJournalError::HeadMismatch);
        }
        let (id, window, cohort) = plan.identity();
        for (index, record) in self.records.iter().enumerate() {
            let (old_id, old_window, old_cohort) = record.plan.identity();
            if id == old_id {
                if plan != &record.plan {
                    return Err(EvaluationClosureError::FinalHoldoutIdentityConflict(
                        id.to_string(),
                    )
                    .into());
                }
                return Ok(Some(index));
            }
            if window == old_window || cohort == old_cohort {
                return Err(EvaluationClosureError::FinalHoldoutReused.into());
            }
        }
        if self.records.len() >= self.limit {
            return Err(FinalHoldoutJournalError::RecordLimit);
        }
        Ok(None)
    }
    pub(crate) fn consume(
        &mut self,
        expected: Digest32,
        plan: &CrossFoldPlanReceiptV1,
    ) -> Result<FinalHoldoutJournalReceiptV1, FinalHoldoutJournalError> {
        let envelope = HoldoutPlanEnvelopeV2::CrossFold(Box::new(plan.clone()));
        let existing = self.preflight(expected, &envelope)?;
        let use_receipt = self.legacy.consume(plan)?;
        let (index, disposition) = if let Some(index) = existing {
            (index, HoldoutUseDispositionV1::IdempotentReplay)
        } else {
            let sequence = self.records.len() as u64 + 1;
            let digest = record_digest(
                b"hepta.intelligence-eval.final-holdout-journal.v1",
                sequence,
                self.head,
                plan.plan_digest,
                use_receipt.use_digest,
            );
            self.records.push(HoldoutJournalRecordV2 {
                sequence,
                predecessor_head_digest: self.head,
                record_digest: digest,
                plan: envelope,
                use_receipt: HoldoutUseEnvelopeV2::CrossFold(Box::new(use_receipt.clone())),
            });
            self.head = digest;
            (self.records.len() - 1, HoldoutUseDispositionV1::Recorded)
        };
        let stored = &self.records[index];
        Ok(FinalHoldoutJournalReceiptV1 {
            disposition,
            sequence: stored.sequence,
            record_digest: stored.record_digest,
            head_digest: self.head,
            use_receipt,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
    pub(crate) fn consume_paired(
        &mut self,
        expected: Digest32,
        plan: &FrozenPairedPlanV1,
    ) -> Result<PairedHoldoutJournalReceiptV1, FinalHoldoutJournalError> {
        plan.validate()
            .map_err(|_| FinalHoldoutJournalError::SnapshotMismatch)?;
        let envelope = HoldoutPlanEnvelopeV2::Paired(Box::new(plan.clone()));
        let (index, disposition) = if let Some(index) = self.preflight(expected, &envelope)? {
            (index, HoldoutUseDispositionV1::IdempotentReplay)
        } else {
            let sequence = self.records.len() as u64 + 1;
            let use_digest = seal(
                b"hepta.paired-full-information.use.v1",
                &[plan.plan_digest(), self.head],
            );
            let digest = record_digest(
                b"hepta.paired-full-information.journal.v1",
                sequence,
                self.head,
                plan.plan_digest(),
                use_digest,
            );
            self.records.push(HoldoutJournalRecordV2 {
                sequence,
                predecessor_head_digest: self.head,
                record_digest: digest,
                plan: envelope,
                use_receipt: HoldoutUseEnvelopeV2::Paired(use_digest),
            });
            self.head = digest;
            (self.records.len() - 1, HoldoutUseDispositionV1::Recorded)
        };
        let stored = &self.records[index];
        let mut receipt = PairedHoldoutJournalReceiptV1 {
            disposition,
            sequence: stored.sequence,
            record_digest: stored.record_digest,
            head_digest: self.head,
            plan: plan.clone(),
            authority: AuthorityPosture::DENY_ALL,
            receipt_seal: Digest32::ZERO,
        };
        receipt.receipt_seal = paired_receipt_seal(&receipt);
        Ok(receipt)
    }
    pub(crate) fn from_snapshot_with_record_limit(
        snapshot: HoldoutJournalSnapshotV2,
        limit: usize,
    ) -> Result<Self, FinalHoldoutJournalError> {
        if snapshot.records.len() > limit {
            return Err(FinalHoldoutJournalError::RecordLimit);
        }
        let mut result = Self::with_record_limit(limit)?;
        for expected in snapshot.records {
            if expected.sequence != result.records.len() as u64 + 1
                || expected.predecessor_head_digest != result.head
            {
                return Err(FinalHoldoutJournalError::SnapshotMismatch);
            }
            let before = result.records.len();
            match &expected.plan {
                HoldoutPlanEnvelopeV2::CrossFold(plan) => {
                    result.consume(result.head, plan)?;
                }
                HoldoutPlanEnvelopeV2::Paired(plan) => {
                    result.consume_paired(result.head, plan)?;
                }
            }
            if result.records.len() != before + 1 || result.records.last() != Some(&expected) {
                return Err(FinalHoldoutJournalError::SnapshotMismatch);
            }
        }
        if result.head != snapshot.head_digest {
            return Err(FinalHoldoutJournalError::SnapshotMismatch);
        }
        Ok(result)
    }
}

fn record_digest(
    domain: &[u8],
    sequence: u64,
    predecessor: Digest32,
    plan: Digest32,
    used: Digest32,
) -> Digest32 {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(&sequence.to_be_bytes());
    for value in [predecessor, plan, used] {
        bytes.extend_from_slice(value.as_array());
    }
    Digest32::of_bytes(&bytes)
}
