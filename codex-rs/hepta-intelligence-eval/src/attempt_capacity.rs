//! Derived, restart-rebuildable reservations and the unresolved-attempt index.
//!
//! Admission reserves the largest remaining lifecycle before irreversible
//! holdout use. Reservations are derived from durable phases, not another store.
use std::collections::BTreeSet;
use std::ops::Bound;

use codex_hepta_types::StableId;

use super::AttemptEvents;
use super::MAX_PAGE;
use super::ProductEvaluationAttemptJournalErrorV1;
use super::ProductEvaluationAttemptPhaseV1;
use super::ProductEvaluationAttemptReceiptV1;
use super::ProductEvaluationAttemptTransitionV1;

const HARD_MAXIMUM_BYTES: u64 = 64 * 1024 * 1024;
const HARD_MAXIMUM_EVENTS: usize = 1_000_000;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(super) struct Reservation {
    pub(super) events: u64,
    pub(super) bytes: u64,
}

pub(super) struct AttemptCapacity {
    reserved: Reservation,
    pub(super) pending: BTreeSet<StableId>,
    maximum_bytes: u64,
    maximum_events: usize,
}

impl Default for AttemptCapacity {
    fn default() -> Self {
        Self::with_limits(HARD_MAXIMUM_BYTES, HARD_MAXIMUM_EVENTS)
    }
}

impl AttemptCapacity {
    pub(super) fn with_limits(maximum_bytes: u64, maximum_events: usize) -> Self {
        Self {
            reserved: Reservation::default(),
            pending: BTreeSet::new(),
            maximum_bytes,
            maximum_events,
        }
    }

    pub(super) fn limits(&self) -> (u64, usize) {
        (self.maximum_bytes, self.maximum_events)
    }

    pub(super) fn reserved(&self) -> Reservation {
        self.reserved
    }

    pub(super) fn project(
        &self,
        previous: Option<ProductEvaluationAttemptPhaseV1>,
        transition: &ProductEvaluationAttemptTransitionV1,
    ) -> Result<Reservation, ProductEvaluationAttemptJournalErrorV1> {
        let before = previous.map_or(0, remaining);
        let after = remaining(transition.phase);
        let frame = 135_u64
            .checked_add(
                u64::try_from(transition.attempt_id.as_str().len())
                    .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Capacity)?,
            )
            .ok_or(ProductEvaluationAttemptJournalErrorV1::Capacity)?;
        let events = self
            .reserved
            .events
            .checked_sub(before)
            .and_then(|value| value.checked_add(after))
            .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
        let bytes = self
            .reserved
            .bytes
            .checked_sub(before * frame)
            .and_then(|value| value.checked_add(after * frame))
            .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)?;
        Ok(Reservation { events, bytes })
    }

    pub(super) fn install(
        &mut self,
        reservation: Reservation,
        transition: &ProductEvaluationAttemptTransitionV1,
    ) {
        self.reserved = reservation;
        if transition.phase.is_terminal() {
            self.pending.remove(&transition.attempt_id);
        } else {
            self.pending.insert(transition.attempt_id.clone());
        }
    }

    pub(super) fn pending_page(
        &self,
        attempts: &AttemptEvents,
        after: Option<&StableId>,
        limit: usize,
    ) -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        if !(1..=MAX_PAGE).contains(&limit) {
            return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
        }
        let lower = after.map_or(Bound::Unbounded, Bound::Excluded);
        self.pending
            .range::<StableId, _>((lower, Bound::Unbounded))
            .take(limit)
            .map(|id| {
                attempts
                    .get(id)
                    .and_then(|events| events.last())
                    .cloned()
                    .filter(|receipt| !receipt.transition.phase.is_terminal())
                    .ok_or(ProductEvaluationAttemptJournalErrorV1::Corrupt)
            })
            .collect()
    }
}

impl Reservation {
    pub(super) fn check(
        self,
        byte_len: u64,
        event_count: usize,
        maximum_bytes: u64,
        maximum_events: usize,
    ) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
        let events = u64::try_from(event_count)
            .ok()
            .and_then(|count| count.checked_add(self.events));
        if byte_len
            .checked_add(self.bytes)
            .is_none_or(|value| value > maximum_bytes)
            || events.is_none_or(|value| value > maximum_events as u64)
        {
            return Err(ProductEvaluationAttemptJournalErrorV1::Capacity);
        }
        Ok(())
    }
}

fn remaining(phase: ProductEvaluationAttemptPhaseV1) -> u64 {
    use ProductEvaluationAttemptPhaseV1 as Phase;
    match phase {
        Phase::IntentPersisted => 6,
        Phase::HoldoutConsumed => 5,
        Phase::ComparisonSealed => 4,
        Phase::QualificationArtifactsPersisted => 3,
        Phase::QualificationDecided => 2,
        Phase::PublicationPending => 1,
        Phase::Failed | Phase::RejectedBeforeHoldout | Phase::Published => 0,
    }
}

#[cfg(test)]
#[path = "attempt_capacity_tests.rs"]
mod tests;
