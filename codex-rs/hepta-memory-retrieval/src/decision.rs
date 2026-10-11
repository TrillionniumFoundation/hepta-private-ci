//! Causal-evaluation observation for one retrieval assignment.
//!
//! This type is authority-free and append-ready evidence, not a learning-ledger
//! writer. It binds the owner-enumerated candidate set separately from the
//! deterministic post-budget legal set so truncation and source incompleteness
//! cannot be hidden by the final selection.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::GeneratedCandidateInputV1;
use crate::GeneratedRecallV1;
use crate::MemoryCueV1;
use crate::RetrievalPolicyV1;
use crate::RetrievalSourceCompletenessV1;
use crate::build_candidate_union_from_generated;

const ASSIGNMENT_DOMAIN: &[u8] = b"hepta.retrieval-assignment-observation.v1";

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct RetrievalCandidateIdentityV1 {
    pub record_id: StableId,
    pub record_revision: Revision,
    pub record_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RetrievalAssignmentCompletenessV1 {
    /// Every configured generator reported source exhaustion for the observed
    /// cut. Deterministic policy truncation, when present, is still recorded.
    Complete,
    /// At least one generator hit its source/output bound. The observation is
    /// valid generator-relative evidence but must not be treated as a complete
    /// source candidate universe.
    GeneratorRelativeIncomplete,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalAssignmentObservationV1 {
    pub cue_digest: Digest32,
    pub policy_digest: Digest32,
    pub source_completeness_digest: Digest32,
    pub candidate_union_digest: Digest32,
    pub recall_packet_digest: Digest32,
    /// Every exact record enumerated by the configured owner generators before
    /// retrieval-policy channel limits.
    pub enumerated_candidates: Vec<RetrievalCandidateIdentityV1>,
    /// Exact candidates admitted to the deterministic candidate union after
    /// channel limits and deduplication.
    pub legal_candidates: Vec<RetrievalCandidateIdentityV1>,
    /// Exact selected record set. Empty is the explicit abstention action.
    pub selected_candidates: Vec<RetrievalCandidateIdentityV1>,
    pub omitted_by_policy_limits: u32,
    pub completeness: RetrievalAssignmentCompletenessV1,
    /// The HNMF assignment is deterministic for the bound input/policy, hence
    /// propensity is one. A downstream learned reranker is a separate policy
    /// decision and must record its own propensity rather than reusing this.
    pub assignment_propensity: ProbabilityQ32,
    pub observation_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl RetrievalAssignmentObservationV1 {
    pub fn validate(&self) -> Result<(), AssignmentErrorV1> {
        for (name, digest) in [
            ("assignment_cue", self.cue_digest),
            ("assignment_policy", self.policy_digest),
            (
                "assignment_source_completeness",
                self.source_completeness_digest,
            ),
            ("assignment_candidate_union", self.candidate_union_digest),
            ("assignment_recall_packet", self.recall_packet_digest),
            ("assignment_observation", self.observation_digest),
        ] {
            if digest.is_zero() {
                return Err(AssignmentErrorV1::EmptyDigest(name));
            }
        }
        if self.authority.grants_any() {
            return Err(AssignmentErrorV1::AuthorityGranted);
        }
        if self.assignment_propensity != ProbabilityQ32::ONE {
            return Err(AssignmentErrorV1::InvalidDeterministicPropensity);
        }
        if !strictly_sorted_unique(&self.enumerated_candidates)
            || !strictly_sorted_unique(&self.legal_candidates)
            || !strictly_sorted_unique(&self.selected_candidates)
        {
            return Err(AssignmentErrorV1::NonCanonicalCandidateSet);
        }
        let enumerated = self.enumerated_candidates.iter().collect::<BTreeSet<_>>();
        let legal = self.legal_candidates.iter().collect::<BTreeSet<_>>();
        if !legal.is_subset(&enumerated) {
            return Err(AssignmentErrorV1::LegalCandidateOutsideEnumeration);
        }
        let selected = self.selected_candidates.iter().collect::<BTreeSet<_>>();
        if !selected.is_subset(&legal) {
            return Err(AssignmentErrorV1::SelectedCandidateOutsideLegalSet);
        }
        if self.observation_digest != self.compute_observation_digest() {
            return Err(AssignmentErrorV1::DigestMismatch);
        }
        Ok(())
    }

    #[must_use]
    pub fn causal_eligible(&self) -> bool {
        self.completeness == RetrievalAssignmentCompletenessV1::Complete
    }

    #[must_use]
    pub fn compute_observation_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ASSIGNMENT_DOMAIN);
        push_digest(&mut bytes, self.cue_digest);
        push_digest(&mut bytes, self.policy_digest);
        push_digest(&mut bytes, self.source_completeness_digest);
        push_digest(&mut bytes, self.candidate_union_digest);
        push_digest(&mut bytes, self.recall_packet_digest);
        push_candidates(&mut bytes, &self.enumerated_candidates);
        push_candidates(&mut bytes, &self.legal_candidates);
        push_candidates(&mut bytes, &self.selected_candidates);
        push_u64(&mut bytes, u64::from(self.omitted_by_policy_limits));
        bytes.push(match self.completeness {
            RetrievalAssignmentCompletenessV1::Complete => 0,
            RetrievalAssignmentCompletenessV1::GeneratorRelativeIncomplete => 1,
        });
        push_u64(&mut bytes, self.assignment_propensity.raw());
        Digest32::of_bytes(&bytes)
    }
}

pub fn observe_retrieval_assignment(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    input: &GeneratedCandidateInputV1,
    recall: &GeneratedRecallV1,
) -> Result<RetrievalAssignmentObservationV1, AssignmentErrorV1> {
    cue.validate()
        .map_err(|error| AssignmentErrorV1::InvalidRecall(error.to_string()))?;
    policy
        .validate()
        .map_err(|error| AssignmentErrorV1::InvalidRecall(error.to_string()))?;
    input
        .validate()
        .map_err(|error| AssignmentErrorV1::InvalidGenerator(error.to_string()))?;
    recall
        .validate()
        .map_err(|error| AssignmentErrorV1::InvalidGenerator(error.to_string()))?;

    let union = build_candidate_union_from_generated(cue, policy, input)
        .map_err(|error| AssignmentErrorV1::InvalidGenerator(error.to_string()))?;
    if recall.packet.cue_digest != union.union.cue_digest
        || recall.packet.policy_digest != union.union.policy_digest
        || recall.packet.candidate_union_digest != union.union.union_digest
        || recall.source_completeness_digest != input.source_completeness_digest
    {
        return Err(AssignmentErrorV1::RecallUnionMismatch);
    }

    let mut enumerated_candidates = input
        .flattened_candidates()
        .map_err(|error| AssignmentErrorV1::InvalidGenerator(error.to_string()))?
        .into_iter()
        .map(|candidate| {
            let record_digest = candidate.record.record_digest();
            RetrievalCandidateIdentityV1 {
                record_id: candidate.record.record_id,
                record_revision: candidate.record.revision,
                record_digest,
            }
        })
        .collect::<Vec<_>>();
    enumerated_candidates.sort();
    enumerated_candidates.dedup();

    let mut legal_candidates = union
        .union
        .entries
        .iter()
        .map(|entry| RetrievalCandidateIdentityV1 {
            record_id: entry.record.record_id.clone(),
            record_revision: entry.record.revision,
            record_digest: entry.record.record_digest(),
        })
        .collect::<Vec<_>>();
    legal_candidates.sort();

    let legal_by_identity = legal_candidates
        .iter()
        .map(|candidate| {
            (
                (candidate.record_id.clone(), candidate.record_revision),
                candidate.record_digest,
            )
        })
        .collect::<std::collections::BTreeMap<_, _>>();
    let mut selected_candidates = recall
        .packet
        .selections
        .iter()
        .map(|selection| {
            let key = (selection.record_id.clone(), selection.record_revision);
            let digest = legal_by_identity
                .get(&key)
                .copied()
                .ok_or(AssignmentErrorV1::SelectedCandidateOutsideLegalSet)?;
            if digest != selection.record_digest {
                return Err(AssignmentErrorV1::SelectedDigestMismatch);
            }
            Ok(RetrievalCandidateIdentityV1 {
                record_id: selection.record_id.clone(),
                record_revision: selection.record_revision,
                record_digest: selection.record_digest,
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    selected_candidates.sort();

    let completeness = if input
        .batches
        .iter()
        .all(|batch| batch.receipt.completeness == RetrievalSourceCompletenessV1::Exhausted)
    {
        RetrievalAssignmentCompletenessV1::Complete
    } else {
        RetrievalAssignmentCompletenessV1::GeneratorRelativeIncomplete
    };
    let omitted_by_policy_limits = union.union.omitted_by_channel_limits;

    let mut observation = RetrievalAssignmentObservationV1 {
        cue_digest: cue.digest(),
        policy_digest: policy.digest(),
        source_completeness_digest: input.source_completeness_digest,
        candidate_union_digest: union.union.union_digest,
        recall_packet_digest: recall.packet.packet_digest,
        enumerated_candidates,
        legal_candidates,
        selected_candidates,
        omitted_by_policy_limits,
        completeness,
        assignment_propensity: ProbabilityQ32::ONE,
        observation_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    observation.observation_digest = observation.compute_observation_digest();
    observation.validate()?;
    Ok(observation)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AssignmentErrorV1 {
    EmptyDigest(&'static str),
    InvalidGenerator(String),
    InvalidRecall(String),
    RecallUnionMismatch,
    NonCanonicalCandidateSet,
    LegalCandidateOutsideEnumeration,
    SelectedCandidateOutsideLegalSet,
    SelectedDigestMismatch,
    InvalidDeterministicPropensity,
    AuthorityGranted,
    DigestMismatch,
}

impl fmt::Display for AssignmentErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AssignmentErrorV1 {}

fn strictly_sorted_unique<T: Ord>(values: &[T]) -> bool {
    values.windows(2).all(|pair| pair[0] < pair[1])
}

fn push_candidates(bytes: &mut Vec<u8>, candidates: &[RetrievalCandidateIdentityV1]) {
    push_len(bytes, candidates.len());
    for candidate in candidates {
        push_id(bytes, &candidate.record_id);
        push_u64(bytes, candidate.record_revision.get());
        push_digest(bytes, candidate.record_digest);
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

#[cfg(test)]
#[path = "decision_tests.rs"]
mod tests;
