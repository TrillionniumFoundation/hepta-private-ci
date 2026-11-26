//! Durable, replayable lifecycle of a product evaluation attempt.
//!
//! Legacy consumed-first records remain readable. The recorded product facade
//! starts with IntentPersisted and never re-executes an existing attempt. A
//! comparison is not publication: pending publication remains discoverable until
//! a read-verified Published transition. Receipts confer no authority.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::io;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[path = "attempt_journal_anchor.rs"]
mod anchor;
#[path = "attempt_journal_file.rs"]
mod file;
pub use anchor::AnchoredProductEvaluationAttemptJournalV1;
pub use anchor::ProductEvaluationAttemptAnchorStoreV1;
pub use file::LockedFileProductEvaluationAttemptJournalV1;

const MAX_EVENTS: usize = 1_000_000;
const MAX_PAGE: usize = 1024;
type AttemptEvents = BTreeMap<StableId, Vec<ProductEvaluationAttemptReceiptV1>>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductEvaluationAttemptPhaseV1 {
    HoldoutConsumed,
    ComparisonSealed,
    Failed,
    IntentPersisted,
    RejectedBeforeHoldout,
    QualificationDecided,
    PublicationPending,
    Published,
    /// Exact typed archive bytes are durable and anchored before qualification.
    QualificationArtifactsPersisted,
}

impl ProductEvaluationAttemptPhaseV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::HoldoutConsumed => 0,
            Self::ComparisonSealed => 1,
            Self::Failed => 2,
            Self::IntentPersisted => 3,
            Self::RejectedBeforeHoldout => 4,
            Self::QualificationDecided => 5,
            Self::PublicationPending => 6,
            Self::Published => 7,
            Self::QualificationArtifactsPersisted => 8,
        }
    }

    fn from_tag(tag: u8) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        match tag {
            0 => Ok(Self::HoldoutConsumed),
            1 => Ok(Self::ComparisonSealed),
            2 => Ok(Self::Failed),
            3 => Ok(Self::IntentPersisted),
            4 => Ok(Self::RejectedBeforeHoldout),
            5 => Ok(Self::QualificationDecided),
            6 => Ok(Self::PublicationPending),
            7 => Ok(Self::Published),
            8 => Ok(Self::QualificationArtifactsPersisted),
            _ => Err(ProductEvaluationAttemptJournalErrorV1::Corrupt),
        }
    }

    #[must_use]
    pub const fn is_terminal(self) -> bool {
        matches!(
            self,
            Self::Failed | Self::RejectedBeforeHoldout | Self::Published
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductEvaluationAttemptTransitionV1 {
    pub attempt_id: StableId,
    pub plan_digest: Digest32,
    pub phase: ProductEvaluationAttemptPhaseV1,
    /// Owner namespace for IntentPersisted/RejectedBeforeHoldout; consumed
    /// record digest for all later phases. The intent remains in history.
    pub holdout_record_digest: Digest32,
    /// Phase-bound payload: pre-consumption owner state for IntentPersisted;
    /// zero for HoldoutConsumed; execution for ComparisonSealed; failure for
    /// Failed/RejectedBeforeHoldout; exact archive for QualificationArtifactsPersisted;
    /// request for QualificationDecided/PublicationPending; publication for Published.
    pub terminal_digest: Digest32,
}

impl ProductEvaluationAttemptTransitionV1 {
    pub fn intent(
        attempt_id: StableId,
        plan_digest: Digest32,
        owner_namespace: Digest32,
        owner_state: Digest32,
    ) -> Self {
        Self {
            attempt_id,
            plan_digest,
            phase: ProductEvaluationAttemptPhaseV1::IntentPersisted,
            holdout_record_digest: owner_namespace,
            terminal_digest: owner_state,
        }
    }

    pub fn holdout_consumed(
        attempt_id: StableId,
        plan_digest: Digest32,
        holdout_record_digest: Digest32,
    ) -> Self {
        Self {
            attempt_id,
            plan_digest,
            phase: ProductEvaluationAttemptPhaseV1::HoldoutConsumed,
            holdout_record_digest,
            terminal_digest: Digest32::ZERO,
        }
    }

    pub fn comparison_sealed(
        attempt_id: StableId,
        plan_digest: Digest32,
        holdout_record_digest: Digest32,
        execution_digest: Digest32,
    ) -> Self {
        Self {
            attempt_id,
            plan_digest,
            phase: ProductEvaluationAttemptPhaseV1::ComparisonSealed,
            holdout_record_digest,
            terminal_digest: execution_digest,
        }
    }

    pub fn failed(
        attempt_id: StableId,
        plan_digest: Digest32,
        holdout_record_digest: Digest32,
        failure_digest: Digest32,
    ) -> Self {
        Self {
            attempt_id,
            plan_digest,
            phase: ProductEvaluationAttemptPhaseV1::Failed,
            holdout_record_digest,
            terminal_digest: failure_digest,
        }
    }

    fn validate(&self) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
        use ProductEvaluationAttemptPhaseV1 as Phase;
        if self.plan_digest.is_zero() {
            return Err(ProductEvaluationAttemptJournalErrorV1::Binding);
        }
        let valid = match self.phase {
            Phase::IntentPersisted | Phase::RejectedBeforeHoldout => {
                !self.holdout_record_digest.is_zero() && !self.terminal_digest.is_zero()
            }
            Phase::HoldoutConsumed => {
                !self.holdout_record_digest.is_zero() && self.terminal_digest.is_zero()
            }
            Phase::ComparisonSealed
            | Phase::Failed
            | Phase::QualificationArtifactsPersisted
            | Phase::QualificationDecided
            | Phase::PublicationPending
            | Phase::Published => {
                !self.holdout_record_digest.is_zero() && !self.terminal_digest.is_zero()
            }
        };
        if !valid {
            return Err(ProductEvaluationAttemptJournalErrorV1::Binding);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductEvaluationAttemptReceiptV1 {
    pub transition: ProductEvaluationAttemptTransitionV1,
    pub sequence: u64,
    pub predecessor_digest: Digest32,
    pub event_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl ProductEvaluationAttemptReceiptV1 {
    pub fn validate_integrity(&self) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
        self.transition.validate()?;
        if self.sequence == 0
            || self.event_digest.is_zero()
            || self.authority.grants_any()
            || self.event_digest
                != event_digest(&self.transition, self.sequence, self.predecessor_digest)
        {
            return Err(ProductEvaluationAttemptJournalErrorV1::Corrupt);
        }
        Ok(())
    }
}

/// Retain outside the journal's rollback/backup failure domain. A checksum in the
/// journal is not an independently retained anchor.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProductEvaluationAttemptAnchorV1 {
    pub binding: Digest32,
    pub event_count: u64,
    pub state_digest: Digest32,
}

/// An append acknowledgement is durable for the selected storage topology.
/// Unknown writes must poison the handle. Recovery uses authoritative stores;
/// `pending` is a bounded, lexicographically paginated inventory, not a retry queue.
pub trait ProductEvaluationAttemptJournalV1 {
    fn append(
        &mut self,
        transition: ProductEvaluationAttemptTransitionV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, ProductEvaluationAttemptJournalErrorV1>;
    fn latest(
        &mut self,
        attempt_id: &StableId,
    ) -> Result<Option<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>;

    fn history(
        &mut self,
        _attempt_id: &StableId,
    ) -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        Err(ProductEvaluationAttemptJournalErrorV1::Binding)
    }

    fn pending(
        &mut self,
        _after: Option<&StableId>,
        _limit: usize,
    ) -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        Err(ProductEvaluationAttemptJournalErrorV1::Binding)
    }
}

#[derive(Clone, Debug, Default)]
pub struct InMemoryProductEvaluationAttemptJournalV1 {
    attempts: AttemptEvents,
    plan_owners: BTreeMap<[u8; 32], StableId>,
}

impl ProductEvaluationAttemptJournalV1 for InMemoryProductEvaluationAttemptJournalV1 {
    fn append(
        &mut self,
        transition: ProductEvaluationAttemptTransitionV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, ProductEvaluationAttemptJournalErrorV1> {
        let (receipt, appended) =
            preview_transition(&self.attempts, &self.plan_owners, transition)?;
        if appended {
            install_transition(&mut self.attempts, &mut self.plan_owners, &receipt);
        }
        Ok(receipt)
    }

    fn latest(
        &mut self,
        attempt_id: &StableId,
    ) -> Result<Option<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        Ok(self
            .attempts
            .get(attempt_id)
            .and_then(|events| events.last())
            .cloned())
    }

    fn history(
        &mut self,
        attempt_id: &StableId,
    ) -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        Ok(self.attempts.get(attempt_id).cloned().unwrap_or_default())
    }

    fn pending(
        &mut self,
        after: Option<&StableId>,
        limit: usize,
    ) -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        pending_page(&self.attempts, after, limit)
    }
}

fn preview_transition(
    attempts: &AttemptEvents,
    plan_owners: &BTreeMap<[u8; 32], StableId>,
    transition: ProductEvaluationAttemptTransitionV1,
) -> Result<(ProductEvaluationAttemptReceiptV1, bool), ProductEvaluationAttemptJournalErrorV1> {
    use ProductEvaluationAttemptPhaseV1 as Phase;
    transition.validate()?;
    if plan_owners
        .get(transition.plan_digest.as_array())
        .is_some_and(|owner| owner != &transition.attempt_id)
    {
        return Err(ProductEvaluationAttemptJournalErrorV1::Conflict);
    }
    let events = attempts
        .get(&transition.attempt_id)
        .map_or(&[][..], Vec::as_slice);
    if let Some(existing) = events
        .iter()
        .find(|receipt| receipt.transition == transition)
    {
        return Ok((existing.clone(), false));
    }
    if let Some(previous) = events.last() {
        let before = &previous.transition;
        if before.plan_digest != transition.plan_digest {
            return Err(ProductEvaluationAttemptJournalErrorV1::Conflict);
        }
        let legal = match (before.phase, transition.phase) {
            (Phase::IntentPersisted, Phase::HoldoutConsumed) => true,
            (Phase::IntentPersisted, Phase::RejectedBeforeHoldout) => {
                before.holdout_record_digest == transition.holdout_record_digest
            }
            (Phase::HoldoutConsumed, Phase::ComparisonSealed | Phase::Failed)
            | (
                Phase::ComparisonSealed,
                Phase::QualificationArtifactsPersisted
                | Phase::QualificationDecided
                | Phase::Failed,
            )
            | (
                Phase::QualificationArtifactsPersisted,
                Phase::QualificationDecided | Phase::Failed,
            )
            | (Phase::PublicationPending, Phase::Published) => {
                before.holdout_record_digest == transition.holdout_record_digest
            }
            (Phase::QualificationDecided, Phase::PublicationPending) => {
                before.holdout_record_digest == transition.holdout_record_digest
                    && before.terminal_digest == transition.terminal_digest
            }
            _ => false,
        };
        if !legal {
            return Err(ProductEvaluationAttemptJournalErrorV1::Conflict);
        }
    } else if !matches!(
        transition.phase,
        Phase::IntentPersisted | Phase::HoldoutConsumed
    ) {
        return Err(ProductEvaluationAttemptJournalErrorV1::MissingConsumption);
    }
    let sequence = u64::try_from(events.len() + 1)
        .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Capacity)?;
    let predecessor_digest = events
        .last()
        .map_or(Digest32::ZERO, |receipt| receipt.event_digest);
    let receipt = ProductEvaluationAttemptReceiptV1 {
        event_digest: event_digest(&transition, sequence, predecessor_digest),
        transition,
        sequence,
        predecessor_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.validate_integrity()?;
    Ok((receipt, true))
}

fn install_transition(
    attempts: &mut AttemptEvents,
    plan_owners: &mut BTreeMap<[u8; 32], StableId>,
    receipt: &ProductEvaluationAttemptReceiptV1,
) {
    plan_owners.insert(
        *receipt.transition.plan_digest.as_array(),
        receipt.transition.attempt_id.clone(),
    );
    attempts
        .entry(receipt.transition.attempt_id.clone())
        .or_default()
        .push(receipt.clone());
}

fn pending_page(
    attempts: &AttemptEvents,
    after: Option<&StableId>,
    limit: usize,
) -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1> {
    use std::ops::Bound;
    if !(1..=MAX_PAGE).contains(&limit) {
        return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
    }
    let lower = after.map_or(Bound::Unbounded, Bound::Excluded);
    Ok(attempts
        .range::<StableId, _>((lower, Bound::Unbounded))
        .filter_map(|(_, events)| events.last())
        .filter(|receipt| !receipt.transition.phase.is_terminal())
        .take(limit)
        .cloned()
        .collect())
}

fn event_digest(
    transition: &ProductEvaluationAttemptTransitionV1,
    sequence: u64,
    predecessor_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.attempt-event.v1".to_vec();
    bytes.extend_from_slice(&(transition.attempt_id.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(transition.attempt_id.as_str().as_bytes());
    bytes.extend_from_slice(transition.plan_digest.as_array());
    bytes.push(transition.phase.tag());
    bytes.extend_from_slice(transition.holdout_record_digest.as_array());
    bytes.extend_from_slice(transition.terminal_digest.as_array());
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(predecessor_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductEvaluationAttemptJournalErrorV1 {
    Binding,
    NotRegular,
    Busy,
    AlreadyInitialized,
    Corrupt,
    Conflict,
    MissingConsumption,
    Capacity,
    Indeterminate,
    Io(io::ErrorKind),
}

impl fmt::Display for ProductEvaluationAttemptJournalErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProductEvaluationAttemptJournalErrorV1 {}

#[cfg(test)]
#[path = "attempt_journal_tests.rs"]
mod tests;
