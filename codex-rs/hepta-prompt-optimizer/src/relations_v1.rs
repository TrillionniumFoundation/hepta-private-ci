//! Authenticated relation input for canonical prompt portfolio selection.
//!
//! Hard constraints are complete according to the authenticated owner view.
//! Numeric pair effects are sparse: absence means unsupported for co-selection,
//! never an implicit zero interaction.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::canonical_v1::CanonicalPromptErrorV1;
use crate::canonical_v1::PromptAuthenticationErrorV1;
use crate::canonical_v1::PromptCandidateSetReceiptV1;
use crate::canonical_v1::push_id;
use crate::canonical_v1::push_len;
use crate::canonical_v1::require_digest;

pub const MAX_CANONICAL_PROMPT_INTERACTIONS_V1: usize = 512;
pub const MAX_CANONICAL_PROMPT_CONSTRAINTS_V1: usize = 512;

/// Authenticates the exact interaction/constraint owner view used by selection.
///
/// The authenticated view must be complete for hard conflicts/prerequisites for
/// this candidate set. Pair marginals may be sparse; lack of an explicit pair
/// record means that pair is unsupported for co-selection.
pub trait PromptRelationSourceAuthenticatorV1 {
    fn authenticate_relation_source(
        &self,
        source: &PromptRelationSourceV1,
        objective_digest: Digest32,
        now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPairInteractionV1 {
    pub left_candidate_id: StableId,
    pub right_candidate_id: StableId,
    pub marginal_net_utility: FixedQ32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptHardConstraintV1 {
    Conflict {
        left_candidate_id: StableId,
        right_candidate_id: StableId,
        support_digest: Digest32,
    },
    Requires {
        candidate_id: StableId,
        prerequisite_candidate_id: StableId,
        support_digest: Digest32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRelationSourceV1 {
    pub producer_id: StableId,
    pub candidate_set_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub hard_constraint_completeness_digest: Digest32,
    pub interactions: Vec<PromptPairInteractionV1>,
    pub hard_constraints: Vec<PromptHardConstraintV1>,
    pub source_digest: Digest32,
}

impl PromptRelationSourceV1 {
    #[must_use]
    pub fn compute_source_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.relation-source.v1".to_vec();
        push_id(&mut bytes, &self.producer_id);
        for digest in [
            self.candidate_set_digest,
            self.generation_vector_digest,
            self.hard_constraint_completeness_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_len(&mut bytes, self.interactions.len());
        for interaction in &self.interactions {
            push_id(&mut bytes, &interaction.left_candidate_id);
            push_id(&mut bytes, &interaction.right_candidate_id);
            bytes.extend_from_slice(&interaction.marginal_net_utility.raw().to_be_bytes());
            bytes.extend_from_slice(interaction.support_digest.as_array());
        }
        push_len(&mut bytes, self.hard_constraints.len());
        for constraint in &self.hard_constraints {
            match constraint {
                PromptHardConstraintV1::Conflict {
                    left_candidate_id,
                    right_candidate_id,
                    support_digest,
                } => {
                    bytes.push(0);
                    push_id(&mut bytes, left_candidate_id);
                    push_id(&mut bytes, right_candidate_id);
                    bytes.extend_from_slice(support_digest.as_array());
                }
                PromptHardConstraintV1::Requires {
                    candidate_id,
                    prerequisite_candidate_id,
                    support_digest,
                } => {
                    bytes.push(1);
                    push_id(&mut bytes, candidate_id);
                    push_id(&mut bytes, prerequisite_candidate_id);
                    bytes.extend_from_slice(support_digest.as_array());
                }
            }
        }
        Digest32::of_bytes(&bytes)
    }

    pub fn validate_for(
        &self,
        candidate_set: &PromptCandidateSetReceiptV1,
        now_unix_ms: u64,
    ) -> Result<(), PromptRelationErrorV1> {
        candidate_set.validate(now_unix_ms)?;
        ValidatedPromptRelationsV1::new(candidate_set, self).map(|_| ())
    }
}

pub(crate) struct ValidatedPromptRelationsV1 {
    pub(crate) interactions: BTreeMap<(StableId, StableId), FixedQ32>,
    pub(crate) conflicts: BTreeSet<(StableId, StableId)>,
    pub(crate) requires: BTreeMap<StableId, Vec<StableId>>,
}

impl ValidatedPromptRelationsV1 {
    pub(crate) fn new(
        candidate_set: &PromptCandidateSetReceiptV1,
        source: &PromptRelationSourceV1,
    ) -> Result<Self, PromptRelationErrorV1> {
        if source.producer_id.as_str().is_empty()
            || source.candidate_set_digest != candidate_set.candidate_set_digest
            || source.generation_vector_digest != candidate_set.generation_vector_digest
            || source.interactions.len() > MAX_CANONICAL_PROMPT_INTERACTIONS_V1
            || source.hard_constraints.len() > MAX_CANONICAL_PROMPT_CONSTRAINTS_V1
        {
            return Err(PromptRelationErrorV1::InvalidRelationSource);
        }
        for digest in [
            source.hard_constraint_completeness_digest,
            source.source_digest,
        ] {
            require_digest(digest, "relation source")?;
        }
        if source.source_digest != source.compute_source_digest() {
            return Err(PromptRelationErrorV1::DigestMismatch("relation source"));
        }
        let known = candidate_set
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<BTreeSet<_>>();
        let interactions = validate_interactions(source, &known)?;
        let (conflicts, requires) = validate_constraints(source, &known)?;
        ensure_no_dependency_cycle(&known, &requires)?;
        Ok(Self {
            interactions,
            conflicts,
            requires,
        })
    }
}

fn validate_interactions(
    source: &PromptRelationSourceV1,
    known: &BTreeSet<StableId>,
) -> Result<BTreeMap<(StableId, StableId), FixedQ32>, PromptRelationErrorV1> {
    let mut interactions = BTreeMap::new();
    let mut previous_pair: Option<(StableId, StableId)> = None;
    for edge in &source.interactions {
        if edge.left_candidate_id >= edge.right_candidate_id
            || !known.contains(&edge.left_candidate_id)
            || !known.contains(&edge.right_candidate_id)
        {
            return Err(PromptRelationErrorV1::InvalidRelationEndpoint);
        }
        require_digest(edge.support_digest, "pair interaction support")?;
        let key = (edge.left_candidate_id.clone(), edge.right_candidate_id.clone());
        if previous_pair.as_ref().is_some_and(|previous| previous >= &key) {
            return Err(PromptRelationErrorV1::NonCanonicalRelationOrder);
        }
        previous_pair = Some(key.clone());
        if interactions
            .insert(key, edge.marginal_net_utility)
            .is_some()
        {
            return Err(PromptRelationErrorV1::DuplicateInteraction);
        }
    }
    Ok(interactions)
}

fn validate_constraints(
    source: &PromptRelationSourceV1,
    known: &BTreeSet<StableId>,
) -> Result<
    (
        BTreeSet<(StableId, StableId)>,
        BTreeMap<StableId, Vec<StableId>>,
    ),
    PromptRelationErrorV1,
> {
    let mut conflicts = BTreeSet::new();
    let mut requires = BTreeMap::<StableId, Vec<StableId>>::new();
    let mut keys = BTreeSet::new();
    let mut previous: Option<(u8, StableId, StableId)> = None;
    for constraint in &source.hard_constraints {
        let (kind, left, right, support) = match constraint {
            PromptHardConstraintV1::Conflict {
                left_candidate_id,
                right_candidate_id,
                support_digest,
            } => (0, left_candidate_id, right_candidate_id, support_digest),
            PromptHardConstraintV1::Requires {
                candidate_id,
                prerequisite_candidate_id,
                support_digest,
            } => (1, candidate_id, prerequisite_candidate_id, support_digest),
        };
        if left == right
            || !known.contains(left)
            || !known.contains(right)
            || (kind == 0 && left > right)
        {
            return Err(PromptRelationErrorV1::InvalidRelationEndpoint);
        }
        require_digest(*support, "hard constraint support")?;
        let key = (kind, left.clone(), right.clone());
        if previous.as_ref().is_some_and(|previous| previous >= &key) {
            return Err(PromptRelationErrorV1::NonCanonicalRelationOrder);
        }
        previous = Some(key.clone());
        if !keys.insert(key) {
            return Err(PromptRelationErrorV1::DuplicateConstraint);
        }
        if kind == 0 {
            conflicts.insert((left.clone(), right.clone()));
        } else {
            requires.entry(left.clone()).or_default().push(right.clone());
        }
    }
    Ok((conflicts, requires))
}

fn ensure_no_dependency_cycle(
    candidates: &BTreeSet<StableId>,
    requires: &BTreeMap<StableId, Vec<StableId>>,
) -> Result<(), PromptRelationErrorV1> {
    fn visit(
        candidate_id: &StableId,
        requires: &BTreeMap<StableId, Vec<StableId>>,
        visiting: &mut BTreeSet<StableId>,
        visited: &mut BTreeSet<StableId>,
    ) -> Result<(), PromptRelationErrorV1> {
        if visited.contains(candidate_id) {
            return Ok(());
        }
        if !visiting.insert(candidate_id.clone()) {
            return Err(PromptRelationErrorV1::DependencyCycle);
        }
        if let Some(prerequisites) = requires.get(candidate_id) {
            for prerequisite in prerequisites {
                visit(prerequisite, requires, visiting, visited)?;
            }
        }
        visiting.remove(candidate_id);
        visited.insert(candidate_id.clone());
        Ok(())
    }

    let mut visiting = BTreeSet::new();
    let mut visited = BTreeSet::new();
    for candidate_id in candidates {
        visit(candidate_id, requires, &mut visiting, &mut visited)?;
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptRelationErrorV1 {
    Canonical(CanonicalPromptErrorV1),
    InvalidRelationSource,
    InvalidRelationEndpoint,
    NonCanonicalRelationOrder,
    DuplicateInteraction,
    DuplicateConstraint,
    DependencyCycle,
    EmptyDigest(&'static str),
    DigestMismatch(&'static str),
}

impl From<CanonicalPromptErrorV1> for PromptRelationErrorV1 {
    fn from(value: CanonicalPromptErrorV1) -> Self {
        match value {
            CanonicalPromptErrorV1::EmptyDigest(label) => Self::EmptyDigest(label),
            CanonicalPromptErrorV1::DigestMismatch(label) => Self::DigestMismatch(label),
            other => Self::Canonical(other),
        }
    }
}

impl fmt::Display for PromptRelationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptRelationErrorV1 {}

#[cfg(test)]
#[path = "relations_v1_tests.rs"]
mod tests;
