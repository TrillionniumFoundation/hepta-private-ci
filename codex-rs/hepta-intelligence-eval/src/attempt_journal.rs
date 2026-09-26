//! Durable-CAS state machine for product evaluation attempts.
//!
//! The journal makes the post-holdout failure window explicit. Once a final
//! holdout advances—or its commit status becomes unknown—its plan and attempt are
//! retry-forbidden and require operator reconciliation rather than silent reuse.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_EVENTS: usize = 100_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EvaluationAttemptPhaseV1 {
    Started,
    RejectedBeforeHoldout,
    HoldoutConsumedWithoutTerminalReceipt,
    TemporalEvaluated,
    QualificationRejected,
    PublicationIndeterminate,
    Published,
    /// The holdout CAS may have committed, but the owner could not determine the
    /// authoritative state. Recovery must reconcile the store before reuse.
    HoldoutConsumptionIndeterminate,
}

impl EvaluationAttemptPhaseV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Started => 0,
            Self::RejectedBeforeHoldout => 1,
            Self::HoldoutConsumedWithoutTerminalReceipt => 2,
            Self::TemporalEvaluated => 3,
            Self::QualificationRejected => 4,
            Self::PublicationIndeterminate => 5,
            Self::Published => 6,
            Self::HoldoutConsumptionIndeterminate => 7,
        }
    }

    #[must_use]
    pub const fn retry_forbidden(self) -> bool {
        matches!(
            self,
            Self::HoldoutConsumedWithoutTerminalReceipt
                | Self::HoldoutConsumptionIndeterminate
                | Self::TemporalEvaluated
                | Self::QualificationRejected
                | Self::PublicationIndeterminate
                | Self::Published
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvaluationAttemptEventV1 {
    pub attempt_id: StableId,
    pub plan_digest: Digest32,
    pub phase: EvaluationAttemptPhaseV1,
    pub holdout_before: Digest32,
    pub holdout_after: Digest32,
    pub execution_digest: Digest32,
    pub publication_digest: Digest32,
    pub failure_digest: Digest32,
    pub sequence: u64,
    pub previous_digest: Digest32,
    pub event_digest: Digest32,
}

impl EvaluationAttemptEventV1 {
    #[allow(clippy::too_many_arguments)]
    fn new(
        attempt_id: StableId,
        plan_digest: Digest32,
        phase: EvaluationAttemptPhaseV1,
        holdout_before: Digest32,
        holdout_after: Digest32,
        execution_digest: Digest32,
        publication_digest: Digest32,
        failure_digest: Digest32,
        sequence: u64,
        previous_digest: Digest32,
    ) -> Result<Self, EvaluationAttemptErrorV1> {
        if plan_digest.is_zero() || holdout_before.is_zero() || sequence == 0 {
            return Err(EvaluationAttemptErrorV1::Binding);
        }
        let mut event = Self {
            attempt_id,
            plan_digest,
            phase,
            holdout_before,
            holdout_after,
            execution_digest,
            publication_digest,
            failure_digest,
            sequence,
            previous_digest,
            event_digest: Digest32::ZERO,
        };
        validate_phase_fields(&event)?;
        event.event_digest = digest_event(&event);
        Ok(event)
    }

    fn validate(&self) -> Result<(), EvaluationAttemptErrorV1> {
        if self.sequence == 0
            || self.plan_digest.is_zero()
            || self.holdout_before.is_zero()
            || self.event_digest != digest_event(self)
        {
            return Err(EvaluationAttemptErrorV1::Corrupt);
        }
        validate_phase_fields(self)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvaluationAttemptSnapshotV1 {
    pub events: Vec<EvaluationAttemptEventV1>,
    pub head_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvaluationAttemptCasRecordV1 {
    pub binding: Digest32,
    pub snapshot: EvaluationAttemptSnapshotV1,
    pub state_digest: Digest32,
}

impl EvaluationAttemptCasRecordV1 {
    fn new(
        binding: Digest32,
        snapshot: EvaluationAttemptSnapshotV1,
    ) -> Result<Self, EvaluationAttemptErrorV1> {
        if binding.is_zero() || snapshot.events.len() > MAX_EVENTS {
            return Err(EvaluationAttemptErrorV1::Binding);
        }
        validate_snapshot(&snapshot)?;
        let state_digest = digest_state(binding, &snapshot);
        Ok(Self {
            binding,
            snapshot,
            state_digest,
        })
    }

    fn validate(&self, binding: Digest32) -> Result<(), EvaluationAttemptErrorV1> {
        if self.binding != binding || self.state_digest != digest_state(binding, &self.snapshot) {
            return Err(EvaluationAttemptErrorV1::Corrupt);
        }
        validate_snapshot(&self.snapshot)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EvaluationAttemptCasStoreErrorV1 {
    Conflict,
    Rejected,
    Indeterminate,
}

impl fmt::Display for EvaluationAttemptCasStoreErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for EvaluationAttemptCasStoreErrorV1 {}

/// Host-provided authoritative attempt-state store. CAS must be linearizable
/// across every process participating in the same binding. An uncertain commit
/// must return `Indeterminate`.
pub trait EvaluationAttemptCasStoreV1 {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<EvaluationAttemptCasRecordV1>, EvaluationAttemptCasStoreErrorV1>;

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &EvaluationAttemptCasRecordV1,
    ) -> Result<(), EvaluationAttemptCasStoreErrorV1>;
}

pub struct EvaluationAttemptJournalV1<S> {
    store: S,
    binding: Digest32,
    snapshot: EvaluationAttemptSnapshotV1,
    state_digest: Digest32,
    poisoned: bool,
}

impl<S: EvaluationAttemptCasStoreV1> EvaluationAttemptJournalV1<S> {
    pub fn initialize(
        mut store: S,
        binding: Digest32,
    ) -> Result<Self, EvaluationAttemptErrorV1> {
        if binding.is_zero() || store.load(binding)?.is_some() {
            return Err(EvaluationAttemptErrorV1::Conflict);
        }
        let snapshot = EvaluationAttemptSnapshotV1 {
            events: Vec::new(),
            head_digest: Digest32::ZERO,
        };
        let record = EvaluationAttemptCasRecordV1::new(binding, snapshot.clone())?;
        apply_cas(&mut store, binding, None, &record)?;
        Ok(Self {
            store,
            binding,
            snapshot,
            state_digest: record.state_digest,
            poisoned: false,
        })
    }

    pub fn recover(
        mut store: S,
        binding: Digest32,
    ) -> Result<Self, EvaluationAttemptErrorV1> {
        let record = store
            .load(binding)?
            .ok_or(EvaluationAttemptErrorV1::Missing)?;
        record.validate(binding)?;
        Ok(Self {
            store,
            binding,
            snapshot: record.snapshot,
            state_digest: record.state_digest,
            poisoned: false,
        })
    }

    pub fn begin(
        &mut self,
        attempt_id: StableId,
        plan_digest: Digest32,
        holdout_before: Digest32,
    ) -> Result<EvaluationAttemptEventV1, EvaluationAttemptErrorV1> {
        if let Some(latest) = self.latest(&attempt_id) {
            if latest.phase == EvaluationAttemptPhaseV1::Started
                && latest.plan_digest == plan_digest
                && latest.holdout_before == holdout_before
            {
                return Ok(latest.clone());
            }
            return Err(EvaluationAttemptErrorV1::RetryForbidden);
        }
        if self
            .snapshot
            .events
            .iter()
            .any(|event| event.plan_digest == plan_digest)
        {
            return Err(EvaluationAttemptErrorV1::RetryForbidden);
        }
        self.append(
            attempt_id,
            plan_digest,
            EvaluationAttemptPhaseV1::Started,
            holdout_before,
            holdout_before,
            Digest32::ZERO,
            Digest32::ZERO,
            Digest32::ZERO,
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub fn transition(
        &mut self,
        attempt_id: StableId,
        plan_digest: Digest32,
        phase: EvaluationAttemptPhaseV1,
        holdout_before: Digest32,
        holdout_after: Digest32,
        execution_digest: Digest32,
        publication_digest: Digest32,
        failure_digest: Digest32,
    ) -> Result<EvaluationAttemptEventV1, EvaluationAttemptErrorV1> {
        let previous = self
            .latest(&attempt_id)
            .ok_or(EvaluationAttemptErrorV1::Missing)?;
        if previous.plan_digest != plan_digest
            || previous.holdout_before != holdout_before
            || !valid_transition(previous.phase, phase)
        {
            return Err(EvaluationAttemptErrorV1::Transition);
        }
        self.append(
            attempt_id,
            plan_digest,
            phase,
            holdout_before,
            holdout_after,
            execution_digest,
            publication_digest,
            failure_digest,
        )
    }

    #[must_use]
    pub fn latest(&self, attempt_id: &StableId) -> Option<&EvaluationAttemptEventV1> {
        self.snapshot
            .events
            .iter()
            .rev()
            .find(|event| &event.attempt_id == attempt_id)
    }

    #[must_use]
    pub fn state_digest(&self) -> Digest32 {
        self.state_digest
    }

    #[must_use]
    pub fn is_poisoned(&self) -> bool {
        self.poisoned
    }

    #[must_use]
    pub fn into_store(self) -> S {
        self.store
    }

    #[allow(clippy::too_many_arguments)]
    fn append(
        &mut self,
        attempt_id: StableId,
        plan_digest: Digest32,
        phase: EvaluationAttemptPhaseV1,
        holdout_before: Digest32,
        holdout_after: Digest32,
        execution_digest: Digest32,
        publication_digest: Digest32,
        failure_digest: Digest32,
    ) -> Result<EvaluationAttemptEventV1, EvaluationAttemptErrorV1> {
        if self.poisoned {
            return Err(EvaluationAttemptErrorV1::Poisoned);
        }
        if self.snapshot.events.len() >= MAX_EVENTS {
            return Err(EvaluationAttemptErrorV1::Capacity);
        }
        let sequence = (self.snapshot.events.len() as u64)
            .checked_add(1)
            .ok_or(EvaluationAttemptErrorV1::Capacity)?;
        let event = EvaluationAttemptEventV1::new(
            attempt_id,
            plan_digest,
            phase,
            holdout_before,
            holdout_after,
            execution_digest,
            publication_digest,
            failure_digest,
            sequence,
            self.snapshot.head_digest,
        )?;
        let mut next_snapshot = self.snapshot.clone();
        next_snapshot.events.push(event.clone());
        next_snapshot.head_digest = event.event_digest;
        let next = EvaluationAttemptCasRecordV1::new(self.binding, next_snapshot.clone())?;
        match self
            .store
            .compare_and_swap(self.binding, Some(self.state_digest), &next)
        {
            Ok(()) => {
                self.snapshot = next_snapshot;
                self.state_digest = next.state_digest;
                Ok(event)
            }
            Err(EvaluationAttemptCasStoreErrorV1::Conflict) => {
                self.poisoned = true;
                Err(EvaluationAttemptErrorV1::Conflict)
            }
            Err(EvaluationAttemptCasStoreErrorV1::Rejected) => {
                Err(EvaluationAttemptErrorV1::Rejected)
            }
            Err(EvaluationAttemptCasStoreErrorV1::Indeterminate) => {
                self.poisoned = true;
                Err(EvaluationAttemptErrorV1::Indeterminate)
            }
        }
    }
}

fn validate_snapshot(snapshot: &EvaluationAttemptSnapshotV1) -> Result<(), EvaluationAttemptErrorV1> {
    if snapshot.events.len() > MAX_EVENTS {
        return Err(EvaluationAttemptErrorV1::Capacity);
    }
    let mut previous = Digest32::ZERO;
    let mut latest: BTreeMap<&StableId, &EvaluationAttemptEventV1> = BTreeMap::new();
    let mut plan_owners: BTreeMap<[u8; 32], &StableId> = BTreeMap::new();
    for (index, event) in snapshot.events.iter().enumerate() {
        event.validate()?;
        if event.sequence != index as u64 + 1 || event.previous_digest != previous {
            return Err(EvaluationAttemptErrorV1::Corrupt);
        }
        let plan_key = *event.plan_digest.as_array();
        if let Some(owner) = plan_owners.get(&plan_key) {
            if *owner != &event.attempt_id {
                return Err(EvaluationAttemptErrorV1::Corrupt);
            }
        } else {
            plan_owners.insert(plan_key, &event.attempt_id);
        }
        if let Some(prior) = latest.get(&event.attempt_id) {
            if prior.plan_digest != event.plan_digest
                || prior.holdout_before != event.holdout_before
                || !valid_transition(prior.phase, event.phase)
            {
                return Err(EvaluationAttemptErrorV1::Corrupt);
            }
        } else if event.phase != EvaluationAttemptPhaseV1::Started {
            return Err(EvaluationAttemptErrorV1::Corrupt);
        }
        latest.insert(&event.attempt_id, event);
        previous = event.event_digest;
    }
    if snapshot.head_digest != previous {
        return Err(EvaluationAttemptErrorV1::Corrupt);
    }
    Ok(())
}

fn validate_phase_fields(event: &EvaluationAttemptEventV1) -> Result<(), EvaluationAttemptErrorV1> {
    let holdout_advanced = event.holdout_after != event.holdout_before;
    let valid = match event.phase {
        EvaluationAttemptPhaseV1::Started => {
            !holdout_advanced
                && event.execution_digest.is_zero()
                && event.publication_digest.is_zero()
                && event.failure_digest.is_zero()
        }
        EvaluationAttemptPhaseV1::RejectedBeforeHoldout => {
            !holdout_advanced
                && event.execution_digest.is_zero()
                && event.publication_digest.is_zero()
                && !event.failure_digest.is_zero()
        }
        EvaluationAttemptPhaseV1::HoldoutConsumedWithoutTerminalReceipt => {
            holdout_advanced
                && event.execution_digest.is_zero()
                && event.publication_digest.is_zero()
                && !event.failure_digest.is_zero()
        }
        EvaluationAttemptPhaseV1::HoldoutConsumptionIndeterminate => {
            !holdout_advanced
                && event.execution_digest.is_zero()
                && event.publication_digest.is_zero()
                && !event.failure_digest.is_zero()
        }
        EvaluationAttemptPhaseV1::TemporalEvaluated => {
            holdout_advanced
                && !event.execution_digest.is_zero()
                && event.publication_digest.is_zero()
                && event.failure_digest.is_zero()
        }
        EvaluationAttemptPhaseV1::QualificationRejected => {
            holdout_advanced
                && !event.execution_digest.is_zero()
                && event.publication_digest.is_zero()
                && !event.failure_digest.is_zero()
        }
        EvaluationAttemptPhaseV1::PublicationIndeterminate => {
            holdout_advanced
                && !event.execution_digest.is_zero()
                && event.publication_digest.is_zero()
                && !event.failure_digest.is_zero()
        }
        EvaluationAttemptPhaseV1::Published => {
            holdout_advanced
                && !event.execution_digest.is_zero()
                && !event.publication_digest.is_zero()
                && event.failure_digest.is_zero()
        }
    };
    if valid {
        Ok(())
    } else {
        Err(EvaluationAttemptErrorV1::Binding)
    }
}

const fn valid_transition(
    previous: EvaluationAttemptPhaseV1,
    next: EvaluationAttemptPhaseV1,
) -> bool {
    matches!(
        (previous, next),
        (
            EvaluationAttemptPhaseV1::Started,
            EvaluationAttemptPhaseV1::RejectedBeforeHoldout
                | EvaluationAttemptPhaseV1::HoldoutConsumedWithoutTerminalReceipt
                | EvaluationAttemptPhaseV1::HoldoutConsumptionIndeterminate
                | EvaluationAttemptPhaseV1::TemporalEvaluated
        ) | (
            EvaluationAttemptPhaseV1::TemporalEvaluated,
            EvaluationAttemptPhaseV1::QualificationRejected
                | EvaluationAttemptPhaseV1::PublicationIndeterminate
                | EvaluationAttemptPhaseV1::Published
        ) | (
            EvaluationAttemptPhaseV1::PublicationIndeterminate,
            EvaluationAttemptPhaseV1::Published
        )
    )
}

fn digest_event(event: &EvaluationAttemptEventV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.attempt-event.v1\0".to_vec();
    push_id(&mut bytes, &event.attempt_id);
    bytes.extend_from_slice(event.plan_digest.as_array());
    bytes.push(event.phase.tag());
    for digest in [
        event.holdout_before,
        event.holdout_after,
        event.execution_digest,
        event.publication_digest,
        event.failure_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&event.sequence.to_be_bytes());
    bytes.extend_from_slice(event.previous_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_state(binding: Digest32, snapshot: &EvaluationAttemptSnapshotV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.attempt-state.v1\0".to_vec();
    bytes.extend_from_slice(binding.as_array());
    bytes.extend_from_slice(&(snapshot.events.len() as u64).to_be_bytes());
    bytes.extend_from_slice(snapshot.head_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn apply_cas<S: EvaluationAttemptCasStoreV1>(
    store: &mut S,
    binding: Digest32,
    expected: Option<Digest32>,
    next: &EvaluationAttemptCasRecordV1,
) -> Result<(), EvaluationAttemptErrorV1> {
    match store.compare_and_swap(binding, expected, next) {
        Ok(()) => Ok(()),
        Err(EvaluationAttemptCasStoreErrorV1::Conflict) => {
            Err(EvaluationAttemptErrorV1::Conflict)
        }
        Err(EvaluationAttemptCasStoreErrorV1::Rejected) => {
            Err(EvaluationAttemptErrorV1::Rejected)
        }
        Err(EvaluationAttemptCasStoreErrorV1::Indeterminate) => {
            Err(EvaluationAttemptErrorV1::Indeterminate)
        }
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EvaluationAttemptErrorV1 {
    Binding,
    Missing,
    Corrupt,
    Capacity,
    Transition,
    RetryForbidden,
    Conflict,
    Rejected,
    Indeterminate,
    Poisoned,
    Store(EvaluationAttemptCasStoreErrorV1),
}

impl fmt::Display for EvaluationAttemptErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for EvaluationAttemptErrorV1 {}

impl From<EvaluationAttemptCasStoreErrorV1> for EvaluationAttemptErrorV1 {
    fn from(value: EvaluationAttemptCasStoreErrorV1) -> Self {
        Self::Store(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Clone, Default)]
    struct MemoryStore {
        record: Option<EvaluationAttemptCasRecordV1>,
        next_error: Option<EvaluationAttemptCasStoreErrorV1>,
        commit_before_error: bool,
    }

    impl EvaluationAttemptCasStoreV1 for MemoryStore {
        fn load(
            &mut self,
            binding: Digest32,
        ) -> Result<Option<EvaluationAttemptCasRecordV1>, EvaluationAttemptCasStoreErrorV1>
        {
            if self
                .record
                .as_ref()
                .is_some_and(|record| record.binding != binding)
            {
                return Err(EvaluationAttemptCasStoreErrorV1::Conflict);
            }
            Ok(self.record.clone())
        }

        fn compare_and_swap(
            &mut self,
            binding: Digest32,
            expected: Option<Digest32>,
            next: &EvaluationAttemptCasRecordV1,
        ) -> Result<(), EvaluationAttemptCasStoreErrorV1> {
            let current = self.record.as_ref().map(|record| record.state_digest);
            if next.binding != binding || current != expected {
                return Err(EvaluationAttemptCasStoreErrorV1::Conflict);
            }
            if let Some(error) = self.next_error.take() {
                if self.commit_before_error {
                    self.record = Some(next.clone());
                }
                return Err(error);
            }
            self.record = Some(next.clone());
            Ok(())
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn post_holdout_failure_is_a_retry_forbidden_terminal_state() {
        let binding = digest("binding");
        let mut journal =
            EvaluationAttemptJournalV1::initialize(MemoryStore::default(), binding)
                .expect("initialize");
        let attempt = id("attempt");
        journal
            .begin(attempt.clone(), digest("plan"), digest("before"))
            .expect("begin");
        journal
            .transition(
                attempt.clone(),
                digest("plan"),
                EvaluationAttemptPhaseV1::HoldoutConsumedWithoutTerminalReceipt,
                digest("before"),
                digest("after"),
                Digest32::ZERO,
                Digest32::ZERO,
                digest("provider-failure"),
            )
            .expect("terminal failure");
        assert_eq!(
            journal.begin(attempt, digest("plan"), digest("before")),
            Err(EvaluationAttemptErrorV1::RetryForbidden)
        );
    }

    #[test]
    fn holdout_commit_unknown_is_explicit_and_retry_forbidden() {
        let mut journal = EvaluationAttemptJournalV1::initialize(
            MemoryStore::default(),
            digest("binding"),
        )
        .expect("initialize");
        let attempt = id("attempt");
        journal
            .begin(attempt.clone(), digest("plan"), digest("before"))
            .expect("begin");
        let terminal = journal
            .transition(
                attempt.clone(),
                digest("plan"),
                EvaluationAttemptPhaseV1::HoldoutConsumptionIndeterminate,
                digest("before"),
                digest("before"),
                Digest32::ZERO,
                Digest32::ZERO,
                digest("unknown-cas"),
            )
            .expect("indeterminate");
        assert!(terminal.phase.retry_forbidden());
        assert_eq!(
            journal.begin(attempt, digest("plan"), digest("before")),
            Err(EvaluationAttemptErrorV1::RetryForbidden)
        );
    }

    #[test]
    fn a_plan_cannot_be_rebound_to_a_different_attempt_id() {
        let mut journal = EvaluationAttemptJournalV1::initialize(
            MemoryStore::default(),
            digest("binding"),
        )
        .expect("initialize");
        journal
            .begin(id("attempt-a"), digest("plan"), digest("before"))
            .expect("first attempt");
        assert_eq!(
            journal.begin(id("attempt-b"), digest("plan"), digest("before")),
            Err(EvaluationAttemptErrorV1::RetryForbidden)
        );
    }

    #[test]
    fn exact_started_retry_is_idempotent_before_holdout_advances() {
        let mut journal = EvaluationAttemptJournalV1::initialize(
            MemoryStore::default(),
            digest("binding"),
        )
        .expect("initialize");
        let attempt = id("attempt");
        let first = journal
            .begin(attempt.clone(), digest("plan"), digest("before"))
            .expect("begin");
        let second = journal
            .begin(attempt, digest("plan"), digest("before"))
            .expect("idempotent begin");
        assert_eq!(first, second);
    }

    #[test]
    fn temporal_evaluation_can_reconcile_indeterminate_publication_to_published() {
        let mut journal = EvaluationAttemptJournalV1::initialize(
            MemoryStore::default(),
            digest("binding"),
        )
        .expect("initialize");
        let attempt = id("attempt");
        journal
            .begin(attempt.clone(), digest("plan"), digest("before"))
            .expect("begin");
        journal
            .transition(
                attempt.clone(),
                digest("plan"),
                EvaluationAttemptPhaseV1::TemporalEvaluated,
                digest("before"),
                digest("after"),
                digest("execution"),
                Digest32::ZERO,
                Digest32::ZERO,
            )
            .expect("evaluated");
        journal
            .transition(
                attempt.clone(),
                digest("plan"),
                EvaluationAttemptPhaseV1::PublicationIndeterminate,
                digest("before"),
                digest("after"),
                digest("execution"),
                Digest32::ZERO,
                digest("unknown-write"),
            )
            .expect("indeterminate");
        let published = journal
            .transition(
                attempt,
                digest("plan"),
                EvaluationAttemptPhaseV1::Published,
                digest("before"),
                digest("after"),
                digest("execution"),
                digest("publication"),
                Digest32::ZERO,
            )
            .expect("reconciled");
        assert_eq!(published.phase, EvaluationAttemptPhaseV1::Published);
    }

    #[test]
    fn accepted_or_unknown_cas_poisons_writer_until_recovery() {
        let binding = digest("binding");
        let mut journal =
            EvaluationAttemptJournalV1::initialize(MemoryStore::default(), binding)
                .expect("initialize");
        journal.store.next_error = Some(EvaluationAttemptCasStoreErrorV1::Indeterminate);
        journal.store.commit_before_error = true;
        assert_eq!(
            journal.begin(id("attempt"), digest("plan"), digest("before")),
            Err(EvaluationAttemptErrorV1::Indeterminate)
        );
        assert!(journal.is_poisoned());
        let store = journal.into_store();
        let recovered = EvaluationAttemptJournalV1::recover(store, binding).expect("recover");
        assert_eq!(
            recovered
                .latest(&id("attempt"))
                .expect("committed event")
                .phase,
            EvaluationAttemptPhaseV1::Started
        );
    }

    #[test]
    fn stale_writer_conflict_poisons_the_losing_handle() {
        let binding = digest("binding");
        let store = MemoryStore::default();
        let first = EvaluationAttemptJournalV1::initialize(store, binding).expect("initialize");
        let shared = first.into_store();
        let mut left =
            EvaluationAttemptJournalV1::recover(shared.clone(), binding).expect("left");
        let mut right = EvaluationAttemptJournalV1::recover(shared, binding).expect("right");
        left.begin(id("left"), digest("plan-left"), digest("before"))
            .expect("left commit");
        right.store.record = left.store.record.clone();
        right.state_digest = digest("stale-state");
        assert_eq!(
            right.begin(id("right"), digest("plan-right"), digest("before")),
            Err(EvaluationAttemptErrorV1::Conflict)
        );
        assert!(right.is_poisoned());
    }
}
