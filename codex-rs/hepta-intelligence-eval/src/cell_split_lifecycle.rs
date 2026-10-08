//! Proposal/evaluation/canary/retention lifecycle for a cell split.
//!
//! This journal is an authority-free replayable state boundary. Its events
//! must be persisted by a durable owner before they can be used as evidence.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::CellParentDispositionV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CellSplitLongHorizonEvaluationReceiptV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellSplitEvaluationDispositionV1 {
    EligibleForCanary,
    InsufficientEvidence,
    Quarantine,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitCanaryReceiptV1 {
    pub split_id: StableId,
    pub candidate_generation: Generation,
    pub dispatch_receipt_digest: Digest32,
    pub old_route_fence_digest: Digest32,
    pub child_route_digest: Digest32,
    pub observed_requests: u64,
    pub failed_requests: u64,
    pub rollback_verified: bool,
    pub receipt_digest: Digest32,
}

impl CellSplitCanaryReceiptV1 {
    pub fn new(
        split_id: StableId,
        candidate_generation: Generation,
        dispatch_receipt_digest: Digest32,
        old_route_fence_digest: Digest32,
        child_route_digest: Digest32,
        observed_requests: u64,
        failed_requests: u64,
        rollback_verified: bool,
    ) -> Result<Self, CellSplitLifecycleErrorV1> {
        if split_id.as_str().is_empty()
            || dispatch_receipt_digest.is_zero()
            || old_route_fence_digest.is_zero()
            || child_route_digest.is_zero()
            || failed_requests > observed_requests
        {
            return Err(CellSplitLifecycleErrorV1::InvalidEvidence);
        }
        let mut receipt = Self {
            split_id,
            candidate_generation,
            dispatch_receipt_digest,
            old_route_fence_digest,
            child_route_digest,
            observed_requests,
            failed_requests,
            rollback_verified,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = receipt.digest();
        Ok(receipt)
    }

    pub fn verify_digest(&self) -> Result<(), CellSplitLifecycleErrorV1> {
        if self.receipt_digest != self.digest() {
            return Err(CellSplitLifecycleErrorV1::Digest);
        }
        Ok(())
    }

    fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.learning.cell-split.canary.v1".to_vec();
        push_id(&mut bytes, &self.split_id);
        bytes.extend_from_slice(&self.candidate_generation.get().to_be_bytes());
        for digest in [
            self.dispatch_receipt_digest,
            self.old_route_fence_digest,
            self.child_route_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.observed_requests.to_be_bytes());
        bytes.extend_from_slice(&self.failed_requests.to_be_bytes());
        bytes.push(u8::from(self.rollback_verified));
        Digest32::of_bytes(&bytes)
    }

    fn passes(&self) -> bool {
        self.failed_requests == 0 && self.rollback_verified
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellSplitLifecycleStateV1 {
    Proposed,
    EvaluationPending,
    EvaluationAccepted,
    CanaryRunning,
    Retained,
    Quarantined,
    Retired,
    RolledBack,
}

impl CellSplitLifecycleStateV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Proposed => 0,
            Self::EvaluationPending => 1,
            Self::EvaluationAccepted => 2,
            Self::CanaryRunning => 3,
            Self::Retained => 4,
            Self::Quarantined => 5,
            Self::Retired => 6,
            Self::RolledBack => 7,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitLifecycleEventV1 {
    pub sequence: u64,
    pub from: CellSplitLifecycleStateV1,
    pub to: CellSplitLifecycleStateV1,
    pub evidence_digest: Digest32,
    pub state_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitLifecycleJournalV1 {
    pub split_id: StableId,
    pub current_state: CellSplitLifecycleStateV1,
    pub events: Vec<CellSplitLifecycleEventV1>,
    pub head_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellSplitLifecycleErrorV1 {
    Binding,
    InvalidTransition,
    TerminalState,
    InvalidEvidence,
    Sequence,
    Digest,
}

impl fmt::Display for CellSplitLifecycleErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for CellSplitLifecycleErrorV1 {}

impl CellSplitLifecycleJournalV1 {
    /// Canonical replay payload for a durable ledger owner. This method does
    /// not write bytes or claim fsync/commit status; the caller must persist
    /// the returned payload with its own writer fence and anchor.
    #[must_use]
    pub fn canonical_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.learning.cell-split.lifecycle-journal.v1".to_vec();
        push_id(&mut bytes, &self.split_id);
        bytes.push(self.current_state.tag());
        bytes.extend_from_slice(self.head_digest.as_array());
        bytes.extend_from_slice(&(self.events.len() as u64).to_be_bytes());
        for event in &self.events {
            bytes.extend_from_slice(&event.sequence.to_be_bytes());
            bytes.push(event.from.tag());
            bytes.push(event.to.tag());
            bytes.extend_from_slice(event.evidence_digest.as_array());
            bytes.extend_from_slice(event.state_digest.as_array());
        }
        bytes
    }

    pub fn proposed(split: &CellSplitV1) -> Result<Self, CellSplitLifecycleErrorV1> {
        split
            .validate_plan()
            .map_err(|_| CellSplitLifecycleErrorV1::Binding)?;
        Ok(Self {
            split_id: split.split_id.clone(),
            current_state: CellSplitLifecycleStateV1::Proposed,
            events: Vec::new(),
            head_digest: Digest32::of_bytes(b"hepta.cell-split.lifecycle.genesis.v1"),
        })
    }

    pub fn apply_evaluation(
        &mut self,
        split: &CellSplitV1,
        receipt: &CellSplitLongHorizonEvaluationReceiptV1,
    ) -> Result<(), CellSplitLifecycleErrorV1> {
        if self.split_id != split.split_id
            || receipt.split_id() != &split.split_id
            || receipt.binding().evaluation_id != split.evaluation.evaluation_id
            || receipt.binding().evaluator_id != split.evaluator_id
            || receipt.binding().no_change_baseline_id != split.evaluation.no_change_baseline_id
            || receipt.binding().evaluation_receipt_digest.is_zero()
            || split
                .evaluation_subject_digest()
                .map_err(|_| CellSplitLifecycleErrorV1::Binding)?
                != receipt.subject_digest()
            || receipt.publication_digest().is_zero()
        {
            return Err(CellSplitLifecycleErrorV1::Binding);
        }
        let target = match receipt.disposition() {
            CellSplitEvaluationDispositionV1::EligibleForCanary => {
                CellSplitLifecycleStateV1::EvaluationAccepted
            }
            CellSplitEvaluationDispositionV1::InsufficientEvidence => {
                CellSplitLifecycleStateV1::EvaluationPending
            }
            CellSplitEvaluationDispositionV1::Quarantine => CellSplitLifecycleStateV1::Quarantined,
        };
        self.transition(target, receipt.binding().evaluation_receipt_digest)
    }

    /// Persist the proposal admission before evaluation starts.  This gives a
    /// machine-driven runner a durable restart point between proposal and
    /// evaluation while retaining the existing signed receipt checks.
    pub fn record_proposal(
        &mut self,
        proposal_digest: Digest32,
    ) -> Result<(), CellSplitLifecycleErrorV1> {
        self.transition(
            CellSplitLifecycleStateV1::EvaluationPending,
            proposal_digest,
        )
    }

    pub fn begin_canary(
        &mut self,
        evidence_digest: Digest32,
    ) -> Result<(), CellSplitLifecycleErrorV1> {
        self.transition(CellSplitLifecycleStateV1::CanaryRunning, evidence_digest)
    }

    pub fn finish_canary(
        &mut self,
        receipt: &CellSplitCanaryReceiptV1,
    ) -> Result<(), CellSplitLifecycleErrorV1> {
        receipt.verify_digest()?;
        if receipt.split_id != self.split_id {
            return Err(CellSplitLifecycleErrorV1::Binding);
        }
        self.transition(
            if receipt.passes() {
                CellSplitLifecycleStateV1::Retained
            } else {
                CellSplitLifecycleStateV1::Quarantined
            },
            receipt.receipt_digest,
        )
    }

    /// Record a failed machine-owned stage without manufacturing a canary
    /// receipt.  The evidence digest must identify the failed invocation (or
    /// its provider error record); this keeps the terminal quarantine replayable
    /// while refusing to treat an execution error as successful evaluation.
    pub fn quarantine(
        &mut self,
        evidence_digest: Digest32,
    ) -> Result<(), CellSplitLifecycleErrorV1> {
        self.transition(CellSplitLifecycleStateV1::Quarantined, evidence_digest)
    }

    pub fn retire(&mut self, split: &CellSplitV1) -> Result<(), CellSplitLifecycleErrorV1> {
        if split.split_id != self.split_id {
            return Err(CellSplitLifecycleErrorV1::Binding);
        }
        if split.retirement.disposition != CellParentDispositionV1::Retire {
            return Err(CellSplitLifecycleErrorV1::Binding);
        }
        self.transition(
            CellSplitLifecycleStateV1::Retired,
            split.retirement.tombstone_digest,
        )
    }

    pub fn rollback(
        &mut self,
        split: &CellSplitV1,
        evidence_digest: Digest32,
    ) -> Result<(), CellSplitLifecycleErrorV1> {
        if split.split_id != self.split_id
            || split.rollback_predecessor_digest.is_zero()
            || evidence_digest.is_zero()
        {
            return Err(CellSplitLifecycleErrorV1::Binding);
        }
        let mut bytes = b"hepta.learning.cell-split.rollback.v1".to_vec();
        bytes.extend_from_slice(split.rollback_predecessor_digest.as_array());
        bytes.extend_from_slice(evidence_digest.as_array());
        self.transition(
            CellSplitLifecycleStateV1::RolledBack,
            Digest32::of_bytes(&bytes),
        )
    }

    /// Reopen after a process restart. Retired and rolled-back journals are
    /// terminal, preventing a stale process from resurrecting the parent.
    pub fn replay(
        split_id: StableId,
        events: Vec<CellSplitLifecycleEventV1>,
    ) -> Result<Self, CellSplitLifecycleErrorV1> {
        let mut journal = Self {
            split_id,
            current_state: CellSplitLifecycleStateV1::Proposed,
            events: Vec::new(),
            head_digest: Digest32::of_bytes(b"hepta.cell-split.lifecycle.genesis.v1"),
        };
        for event in events {
            if event.sequence != journal.events.len() as u64
                || event.from != journal.current_state
                || event.evidence_digest.is_zero()
                || event.state_digest.is_zero()
                || !valid_transition(event.from, event.to)
                || lifecycle_digest(
                    journal.head_digest,
                    event.sequence,
                    event.from,
                    event.to,
                    event.evidence_digest,
                ) != event.state_digest
            {
                return Err(CellSplitLifecycleErrorV1::Digest);
            }
            journal.head_digest = event.state_digest;
            journal.current_state = event.to;
            journal.events.push(event);
        }
        Ok(journal)
    }

    fn transition(
        &mut self,
        target: CellSplitLifecycleStateV1,
        evidence_digest: Digest32,
    ) -> Result<(), CellSplitLifecycleErrorV1> {
        if evidence_digest.is_zero() {
            return Err(CellSplitLifecycleErrorV1::InvalidEvidence);
        }
        if !valid_transition(self.current_state, target) {
            if matches!(
                self.current_state,
                CellSplitLifecycleStateV1::Retired | CellSplitLifecycleStateV1::RolledBack
            ) {
                return Err(CellSplitLifecycleErrorV1::TerminalState);
            }
            return Err(CellSplitLifecycleErrorV1::InvalidTransition);
        }
        let sequence = self.events.len() as u64;
        let state_digest = lifecycle_digest(
            self.head_digest,
            sequence,
            self.current_state,
            target,
            evidence_digest,
        );
        self.events.push(CellSplitLifecycleEventV1 {
            sequence,
            from: self.current_state,
            to: target,
            evidence_digest,
            state_digest,
        });
        self.current_state = target;
        self.head_digest = state_digest;
        Ok(())
    }
}

fn valid_transition(from: CellSplitLifecycleStateV1, to: CellSplitLifecycleStateV1) -> bool {
    matches!(
        (from, to),
        (
            CellSplitLifecycleStateV1::Proposed,
            CellSplitLifecycleStateV1::EvaluationPending
        ) | (
            CellSplitLifecycleStateV1::Proposed,
            CellSplitLifecycleStateV1::EvaluationAccepted
        ) | (
            CellSplitLifecycleStateV1::Proposed,
            CellSplitLifecycleStateV1::Quarantined
        ) | (
            CellSplitLifecycleStateV1::EvaluationPending,
            CellSplitLifecycleStateV1::EvaluationAccepted
        ) | (
            CellSplitLifecycleStateV1::EvaluationPending,
            CellSplitLifecycleStateV1::EvaluationPending
        ) | (
            CellSplitLifecycleStateV1::EvaluationPending,
            CellSplitLifecycleStateV1::Quarantined
        ) | (
            CellSplitLifecycleStateV1::EvaluationAccepted,
            CellSplitLifecycleStateV1::CanaryRunning
        ) | (
            CellSplitLifecycleStateV1::CanaryRunning,
            CellSplitLifecycleStateV1::Retained
        ) | (
            CellSplitLifecycleStateV1::CanaryRunning,
            CellSplitLifecycleStateV1::Quarantined
        ) | (
            CellSplitLifecycleStateV1::CanaryRunning,
            CellSplitLifecycleStateV1::RolledBack
        ) | (
            CellSplitLifecycleStateV1::Retained,
            CellSplitLifecycleStateV1::Retired
        ) | (
            CellSplitLifecycleStateV1::Retained,
            CellSplitLifecycleStateV1::RolledBack
        )
    )
}

fn lifecycle_digest(
    predecessor: Digest32,
    sequence: u64,
    from: CellSplitLifecycleStateV1,
    to: CellSplitLifecycleStateV1,
    evidence: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning.cell-split.lifecycle-event.v1".to_vec();
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.push(from.tag());
    bytes.push(to.tag());
    bytes.extend_from_slice(evidence.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let value = id.as_str().as_bytes();
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value);
}
