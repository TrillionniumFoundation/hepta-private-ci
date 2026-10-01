//! Type-level proof that one selected candidate belongs to the exact frozen set.
//!
//! Fields are private and the constructor is crate-owned.  Product callers can
//! inspect a proof but cannot manufacture one from an arbitrary candidate id.

use codex_hepta_intelligence::CanonicalIntelligenceError;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

const MAX_MEMBERSHIP_CANDIDATES: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdLegalCandidateMembershipProofV1 {
    candidate_set_digest: Digest32,
    candidate_id: StableId,
    propensity: ProbabilityQ32,
    proof_digest: Digest32,
}

impl AgentdLegalCandidateMembershipProofV1 {
    pub(crate) fn admit(
        candidate_set_digest: Digest32,
        candidate_ids: &[StableId],
        candidate_id: &StableId,
        propensity: ProbabilityQ32,
    ) -> Result<Self, CanonicalIntelligenceError> {
        if candidate_set_digest.is_zero()
            || propensity.raw() == 0
            || candidate_ids.is_empty()
            || candidate_ids.len() > MAX_MEMBERSHIP_CANDIDATES
        {
            return Err(CanonicalIntelligenceError::InvalidCandidateSet(
                "candidate membership proof",
            ));
        }
        let mut canonical = candidate_ids.to_vec();
        canonical.sort();
        if canonical.windows(2).any(|window| window[0] == window[1]) {
            return Err(CanonicalIntelligenceError::InvalidCandidateSet(
                "duplicate candidate membership",
            ));
        }
        if canonical.binary_search(candidate_id).is_err() {
            return Err(CanonicalIntelligenceError::InvalidCandidateSet(
                "selected candidate absent",
            ));
        }

        let mut bytes = b"hepta.agentd.legal-candidate-membership.v1\0".to_vec();
        bytes.extend_from_slice(candidate_set_digest.as_array());
        push_id(&mut bytes, candidate_id)?;
        bytes.extend_from_slice(&propensity.raw().to_be_bytes());
        for value in &canonical {
            push_id(&mut bytes, value)?;
        }
        Ok(Self {
            candidate_set_digest,
            candidate_id: candidate_id.clone(),
            propensity,
            proof_digest: Digest32::of_bytes(&bytes),
        })
    }

    #[must_use]
    pub const fn candidate_set_digest(&self) -> Digest32 {
        self.candidate_set_digest
    }

    #[must_use]
    pub fn candidate_id(&self) -> &StableId {
        &self.candidate_id
    }

    #[must_use]
    pub const fn propensity(&self) -> ProbabilityQ32 {
        self.propensity
    }

    #[must_use]
    pub const fn proof_digest(&self) -> Digest32 {
        self.proof_digest
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), CanonicalIntelligenceError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| CanonicalIntelligenceError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    #[test]
    fn membership_is_permutation_invariant_and_set_bound() {
        let digest = Digest32::of_bytes(b"candidate-set");
        let propensity = ProbabilityQ32::from_raw(1).expect("probability");
        let selected = id("candidate-b");
        let first = AgentdLegalCandidateMembershipProofV1::admit(
            digest,
            &[id("candidate-a"), selected.clone()],
            &selected,
            propensity,
        )
        .expect("proof");
        let second = AgentdLegalCandidateMembershipProofV1::admit(
            digest,
            &[selected.clone(), id("candidate-a")],
            &selected,
            propensity,
        )
        .expect("proof");
        assert_eq!(first, second);
        assert_eq!(first.candidate_id(), &selected);
        assert_eq!(first.candidate_set_digest(), digest);
        assert!(!first.proof_digest().is_zero());
    }

    #[test]
    fn absent_duplicate_and_zero_propensity_selections_fail_closed() {
        let digest = Digest32::of_bytes(b"candidate-set");
        let one = ProbabilityQ32::from_raw(1).expect("probability");
        assert!(
            AgentdLegalCandidateMembershipProofV1::admit(
                digest,
                &[id("candidate-a")],
                &id("candidate-b"),
                one,
            )
            .is_err()
        );
        assert!(
            AgentdLegalCandidateMembershipProofV1::admit(
                digest,
                &[id("candidate-a"), id("candidate-a")],
                &id("candidate-a"),
                one,
            )
            .is_err()
        );
        assert!(
            AgentdLegalCandidateMembershipProofV1::admit(
                digest,
                &[id("candidate-a")],
                &id("candidate-a"),
                ProbabilityQ32::ZERO,
            )
            .is_err()
        );
    }
}
