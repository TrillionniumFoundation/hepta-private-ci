//! Bounded, append-only bookkeeping for governed self-iteration.
//!
//! The ledger records externally supplied evidence and candidate state. It does
//! not run a sandbox, evaluate code, choose a winner, or grant any authority.
//! Consumers must authenticate the evidence and perform those decisions in an
//! independent control plane before recording them here.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt;

use codex_hepta_types::{Digest32, LogicalSequence, StableId};

use crate::{
    IterationCandidateStateV1, IterationCandidateV1, IterationEnvelopeV1,
    validate_iteration_transition,
};

pub const MAX_ITERATION_EVENTS: usize = 384;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum IterationEvidenceKindV1 {
    StaticValidation,
    Sandbox,
    Evaluation,
    Review,
    Decision,
    Selection,
    Promotion,
    Release,
    Rejection,
    Quarantine,
    Supersession,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IterationEvidenceV1 {
    pub evidence_id: StableId,
    pub candidate_id: StableId,
    pub actor_id: StableId,
    pub kind: IterationEvidenceKindV1,
    pub evidence_digest: Digest32,
    pub observed_unix_seconds: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IterationLedgerEventV1 {
    pub sequence: LogicalSequence,
    pub candidate_id: StableId,
    pub from: IterationCandidateStateV1,
    pub to: IterationCandidateStateV1,
    pub evidence: IterationEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IterationLedgerSnapshotV1 {
    pub envelope: IterationEnvelopeV1,
    pub candidates: Vec<IterationCandidateV1>,
    pub events: Vec<IterationLedgerEventV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IterationLedgerError {
    InvalidEnvelope(String),
    InvalidCandidate(String),
    CandidateLimitExceeded,
    EventLimitExceeded,
    CandidateAlreadyExists(String),
    CandidateNotFound(String),
    EvidenceIdentityConflict(String),
    EvidenceAlreadyUsed(String),
    EmptyEvidenceDigest,
    EvidenceTimestampMissing,
    EvidenceCandidateMismatch,
    IndependentActorConflict(String),
    EvidenceKindMismatch,
    InvalidTransition(String),
    SnapshotMismatch,
}

impl fmt::Display for IterationLedgerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl Error for IterationLedgerError {}

#[derive(Clone, Debug)]
pub struct IterationLedgerV1 {
    envelope: IterationEnvelopeV1,
    candidates: BTreeMap<StableId, IterationCandidateV1>,
    evidence: BTreeMap<StableId, IterationEvidenceV1>,
    events: Vec<IterationLedgerEventV1>,
}

impl IterationLedgerV1 {
    pub fn new(envelope: IterationEnvelopeV1) -> Result<Self, IterationLedgerError> {
        envelope
            .validate()
            .map_err(IterationLedgerError::InvalidEnvelope)?;
        Ok(Self {
            envelope,
            candidates: BTreeMap::new(),
            evidence: BTreeMap::new(),
            events: Vec::new(),
        })
    }

    #[must_use]
    pub fn envelope(&self) -> &IterationEnvelopeV1 {
        &self.envelope
    }

    #[must_use]
    pub fn candidate(&self, id: &StableId) -> Option<&IterationCandidateV1> {
        self.candidates.get(id)
    }

    pub fn candidates(&self) -> impl Iterator<Item = &IterationCandidateV1> {
        self.candidates.values()
    }

    #[must_use]
    pub fn events(&self) -> &[IterationLedgerEventV1] {
        &self.events
    }

    /// Add a candidate in its only generator-owned state. All later state is
    /// reached through `transition`, which requires typed external evidence.
    pub fn append_candidate(
        &mut self,
        candidate: IterationCandidateV1,
    ) -> Result<(), IterationLedgerError> {
        if self.candidates.len() >= self.envelope.maximum_candidates as usize {
            return Err(IterationLedgerError::CandidateLimitExceeded);
        }
        if self.candidates.contains_key(&candidate.candidate_id) {
            return Err(IterationLedgerError::CandidateAlreadyExists(
                candidate.candidate_id.to_string(),
            ));
        }
        if candidate.state != IterationCandidateStateV1::Drafted {
            return Err(IterationLedgerError::InvalidCandidate(
                "new candidates must start drafted".into(),
            ));
        }
        candidate
            .validate(&self.envelope)
            .map_err(IterationLedgerError::InvalidCandidate)?;
        if candidate.predecessor.as_ref() == Some(&candidate.candidate_id) {
            return Err(IterationLedgerError::InvalidCandidate(
                "candidate cannot roll back to itself".into(),
            ));
        }
        self.candidates
            .insert(candidate.candidate_id.clone(), candidate);
        Ok(())
    }

    /// Record one state transition with its externally produced receipt. This
    /// method only validates shape, ordering and separation; it never executes
    /// or trusts the claimed sandbox/evaluator/decision.
    pub fn transition(
        &mut self,
        candidate_id: &StableId,
        next: IterationCandidateStateV1,
        receipt: IterationEvidenceV1,
    ) -> Result<IterationLedgerEventV1, IterationLedgerError> {
        if self.events.len() >= MAX_ITERATION_EVENTS {
            return Err(IterationLedgerError::EventLimitExceeded);
        }
        let current = self
            .candidates
            .get(candidate_id)
            .ok_or_else(|| IterationLedgerError::CandidateNotFound(candidate_id.to_string()))?
            .clone();
        self.validate_evidence(candidate_id, &current, next, &receipt)?;
        validate_iteration_transition(current.state, next)
            .map_err(IterationLedgerError::InvalidTransition)?;
        if let Some(previous) = self.evidence.get(&receipt.evidence_id) {
            if previous != &receipt {
                return Err(IterationLedgerError::EvidenceIdentityConflict(
                    receipt.evidence_id.to_string(),
                ));
            }
            return Err(IterationLedgerError::EvidenceAlreadyUsed(
                receipt.evidence_id.to_string(),
            ));
        }
        let sequence = LogicalSequence::new((self.events.len() as u64) + 1)
            .map_err(|_| IterationLedgerError::EventLimitExceeded)?;
        let event = IterationLedgerEventV1 {
            sequence,
            candidate_id: candidate_id.clone(),
            from: current.state,
            to: next,
            evidence: receipt.clone(),
        };
        self.evidence.insert(receipt.evidence_id.clone(), receipt);
        self.events.push(event.clone());
        let Some(entry) = self.candidates.get_mut(candidate_id) else {
            return Err(IterationLedgerError::CandidateNotFound(
                candidate_id.to_string(),
            ));
        };
        entry.state = next;
        Ok(event)
    }

    fn validate_evidence(
        &self,
        candidate_id: &StableId,
        current: &IterationCandidateV1,
        next: IterationCandidateStateV1,
        receipt: &IterationEvidenceV1,
    ) -> Result<(), IterationLedgerError> {
        if &receipt.candidate_id != candidate_id {
            return Err(IterationLedgerError::EvidenceCandidateMismatch);
        }
        if receipt.evidence_digest.is_zero() {
            return Err(IterationLedgerError::EmptyEvidenceDigest);
        }
        if receipt.observed_unix_seconds == 0 {
            return Err(IterationLedgerError::EvidenceTimestampMissing);
        }
        if requires_independent_actor(next) && receipt.actor_id == current.generator_identity {
            return Err(IterationLedgerError::IndependentActorConflict(
                receipt.actor_id.to_string(),
            ));
        }
        // Generation, independent evaluation, selection, promotion and release
        // are distinct control roles. A single identity must not evaluate its
        // own evidence and then select/promote/release the same candidate.
        let actor_for = |state| {
            self.events
                .iter()
                .rev()
                .find(|event| event.candidate_id == *candidate_id && event.to == state)
                .map(|event| &event.evidence.actor_id)
        };
        let collides = match next {
            IterationCandidateStateV1::Selected => {
                actor_for(IterationCandidateStateV1::IndependentlyEvaluated)
                    .is_some_and(|actor| actor == &receipt.actor_id)
            }
            IterationCandidateStateV1::Promoted => [
                IterationCandidateStateV1::IndependentlyEvaluated,
                IterationCandidateStateV1::Selected,
            ]
            .into_iter()
            .filter_map(actor_for)
            .any(|actor| actor == &receipt.actor_id),
            IterationCandidateStateV1::Released => [
                IterationCandidateStateV1::IndependentlyEvaluated,
                IterationCandidateStateV1::Selected,
                IterationCandidateStateV1::Promoted,
            ]
            .into_iter()
            .filter_map(actor_for)
            .any(|actor| actor == &receipt.actor_id),
            _ => false,
        };
        if collides {
            return Err(IterationLedgerError::IndependentActorConflict(
                receipt.actor_id.to_string(),
            ));
        }
        if expected_kind(next) != receipt.kind {
            return Err(IterationLedgerError::EvidenceKindMismatch);
        }
        Ok(())
    }

    pub fn snapshot(&self) -> IterationLedgerSnapshotV1 {
        IterationLedgerSnapshotV1 {
            envelope: self.envelope.clone(),
            candidates: self.candidates.values().cloned().collect(),
            events: self.events.clone(),
        }
    }

    pub fn from_snapshot(
        snapshot: IterationLedgerSnapshotV1,
    ) -> Result<Self, IterationLedgerError> {
        let mut ledger = Self::new(snapshot.envelope)?;
        let expected_states: BTreeMap<StableId, IterationCandidateStateV1> = snapshot
            .candidates
            .iter()
            .map(|candidate| (candidate.candidate_id.clone(), candidate.state))
            .collect();
        for mut candidate in snapshot.candidates {
            // Rebuild state exclusively by replaying the append-only events.
            // A snapshot cannot smuggle in a state that has no receipt.
            candidate.state = IterationCandidateStateV1::Drafted;
            ledger.append_candidate(candidate)?;
        }
        let mut prior: BTreeSet<StableId> = BTreeSet::new();
        for expected in snapshot.events {
            let actual = ledger.transition(
                &expected.candidate_id,
                expected.to,
                expected.evidence.clone(),
            )?;
            if actual != expected || !prior.insert(expected.evidence.evidence_id.clone()) {
                return Err(IterationLedgerError::SnapshotMismatch);
            }
        }
        if ledger
            .candidates
            .iter()
            .any(|(id, candidate)| expected_states.get(id) != Some(&candidate.state))
        {
            return Err(IterationLedgerError::SnapshotMismatch);
        }
        Ok(ledger)
    }
}

const fn expected_kind(next: IterationCandidateStateV1) -> IterationEvidenceKindV1 {
    match next {
        IterationCandidateStateV1::StaticallyValidated => IterationEvidenceKindV1::StaticValidation,
        IterationCandidateStateV1::SandboxTested => IterationEvidenceKindV1::Sandbox,
        IterationCandidateStateV1::IndependentlyEvaluated => IterationEvidenceKindV1::Evaluation,
        IterationCandidateStateV1::ReviewRequested => IterationEvidenceKindV1::Review,
        IterationCandidateStateV1::AcceptedCandidate => IterationEvidenceKindV1::Decision,
        IterationCandidateStateV1::Selected => IterationEvidenceKindV1::Selection,
        IterationCandidateStateV1::Promoted => IterationEvidenceKindV1::Promotion,
        IterationCandidateStateV1::Released => IterationEvidenceKindV1::Release,
        IterationCandidateStateV1::Rejected => IterationEvidenceKindV1::Rejection,
        IterationCandidateStateV1::Quarantined => IterationEvidenceKindV1::Quarantine,
        IterationCandidateStateV1::Superseded => IterationEvidenceKindV1::Supersession,
        IterationCandidateStateV1::Drafted => IterationEvidenceKindV1::StaticValidation,
    }
}

const fn requires_independent_actor(next: IterationCandidateStateV1) -> bool {
    !matches!(
        next,
        IterationCandidateStateV1::StaticallyValidated | IterationCandidateStateV1::SandboxTested
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap()
    }
    fn digest(value: u8) -> Digest32 {
        Digest32::from_array([value; 32])
    }
    fn envelope() -> IterationEnvelopeV1 {
        IterationEnvelopeV1 {
            envelope_id: id("env"),
            base_commit: digest(1),
            base_tree: digest(2),
            objective_digest: digest(3),
            grammar_digest: digest(4),
            maximum_files: 1,
            maximum_diff_bytes: 1,
            maximum_candidates: 2,
            maximum_parallel_sandboxes: 1,
            expiry_unix_seconds: 1,
        }
    }
    fn candidate() -> IterationCandidateV1 {
        IterationCandidateV1 {
            candidate_id: id("candidate"),
            envelope_id: id("env"),
            generator_identity: id("generator"),
            semantic_diff_digest: digest(5),
            test_plan_digest: digest(6),
            rollback_digest: digest(7),
            predecessor: Some(id("base")),
            state: IterationCandidateStateV1::Drafted,
        }
    }
    fn receipt(kind: IterationEvidenceKindV1, actor: &str, n: u8) -> IterationEvidenceV1 {
        IterationEvidenceV1 {
            evidence_id: id(&format!("evidence-{n}")),
            candidate_id: id("candidate"),
            actor_id: id(actor),
            kind,
            evidence_digest: digest(n),
            observed_unix_seconds: 1,
        }
    }

    #[test]
    fn records_bounded_external_transitions() {
        let mut ledger = IterationLedgerV1::new(envelope()).unwrap();
        ledger.append_candidate(candidate()).unwrap();
        ledger
            .transition(
                &id("candidate"),
                IterationCandidateStateV1::StaticallyValidated,
                receipt(IterationEvidenceKindV1::StaticValidation, "generator", 8),
            )
            .unwrap();
        ledger
            .transition(
                &id("candidate"),
                IterationCandidateStateV1::SandboxTested,
                receipt(IterationEvidenceKindV1::Sandbox, "generator", 9),
            )
            .unwrap();
        assert!(
            ledger
                .transition(
                    &id("candidate"),
                    IterationCandidateStateV1::IndependentlyEvaluated,
                    receipt(IterationEvidenceKindV1::Evaluation, "generator", 10)
                )
                .is_err()
        );
        ledger
            .transition(
                &id("candidate"),
                IterationCandidateStateV1::IndependentlyEvaluated,
                receipt(IterationEvidenceKindV1::Evaluation, "evaluator", 10),
            )
            .unwrap();
        assert_eq!(ledger.events().len(), 3);
    }

    #[test]
    fn evaluator_selector_promoter_and_releaser_are_role_separated() {
        let mut ledger = IterationLedgerV1::new(envelope()).unwrap();
        ledger.append_candidate(candidate()).unwrap();
        let steps = [
            (
                IterationCandidateStateV1::StaticallyValidated,
                IterationEvidenceKindV1::StaticValidation,
                "generator",
                8,
            ),
            (
                IterationCandidateStateV1::SandboxTested,
                IterationEvidenceKindV1::Sandbox,
                "generator",
                9,
            ),
            (
                IterationCandidateStateV1::IndependentlyEvaluated,
                IterationEvidenceKindV1::Evaluation,
                "evaluator",
                10,
            ),
            (
                IterationCandidateStateV1::ReviewRequested,
                IterationEvidenceKindV1::Review,
                "reviewer",
                11,
            ),
            (
                IterationCandidateStateV1::AcceptedCandidate,
                IterationEvidenceKindV1::Decision,
                "reviewer",
                12,
            ),
        ];
        for (state, kind, actor, n) in steps {
            ledger
                .transition(&id("candidate"), state, receipt(kind, actor, n))
                .unwrap();
        }
        assert!(matches!(
            ledger.transition(
                &id("candidate"),
                IterationCandidateStateV1::Selected,
                receipt(IterationEvidenceKindV1::Selection, "evaluator", 13),
            ),
            Err(IterationLedgerError::IndependentActorConflict(_))
        ));
        ledger
            .transition(
                &id("candidate"),
                IterationCandidateStateV1::Selected,
                receipt(IterationEvidenceKindV1::Selection, "selector", 14),
            )
            .unwrap();
        assert!(matches!(
            ledger.transition(
                &id("candidate"),
                IterationCandidateStateV1::Promoted,
                receipt(IterationEvidenceKindV1::Promotion, "selector", 15),
            ),
            Err(IterationLedgerError::IndependentActorConflict(_))
        ));
        ledger
            .transition(
                &id("candidate"),
                IterationCandidateStateV1::Promoted,
                receipt(IterationEvidenceKindV1::Promotion, "promoter", 16),
            )
            .unwrap();
        assert!(matches!(
            ledger.transition(
                &id("candidate"),
                IterationCandidateStateV1::Released,
                receipt(IterationEvidenceKindV1::Release, "promoter", 17),
            ),
            Err(IterationLedgerError::IndependentActorConflict(_))
        ));
        ledger
            .transition(
                &id("candidate"),
                IterationCandidateStateV1::Released,
                receipt(IterationEvidenceKindV1::Release, "releaser", 18),
            )
            .unwrap();
    }

    #[test]
    fn snapshot_replay_is_exact_and_duplicate_receipts_fail() {
        let mut ledger = IterationLedgerV1::new(envelope()).unwrap();
        ledger.append_candidate(candidate()).unwrap();
        let r = receipt(IterationEvidenceKindV1::StaticValidation, "generator", 8);
        ledger
            .transition(
                &id("candidate"),
                IterationCandidateStateV1::StaticallyValidated,
                r.clone(),
            )
            .unwrap();
        assert!(matches!(
            ledger.transition(
                &id("candidate"),
                IterationCandidateStateV1::SandboxTested,
                r
            ),
            Err(IterationLedgerError::EvidenceKindMismatch)
        ));
        let restored = IterationLedgerV1::from_snapshot(ledger.snapshot()).unwrap();
        assert_eq!(restored.snapshot(), ledger.snapshot());
    }
}
