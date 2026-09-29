//! Versioned proposition evidence and policy admission for generation-bound recall.
//!
//! A conflict report is not a denial. Only an affirmed and a denied claim for
//! the same proposition at the same generation form a contradiction. The
//! generation vector already binds scope and purpose. Proposition owners must
//! include temporal qualifiers in the canonical proposition digest.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;

use crate::CandidateUnionEntryV1;
use crate::CandidateUnionV1;
use crate::RecallErrorV1;
use crate::RetrievalPolicyV1;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PropositionPolarityV2 {
    Affirmed,
    Denied,
    /// Evidence that a source reports a conflict; not either side of a claim.
    ConflictReported,
}

/// Integrity-bound evidence, not an authority credential. The historical
/// `contradiction_group_digest(s)` field names are retained during the source
/// migration, but their values are now structured claims rather than opaque
/// hashes. Old opaque groups cannot be upgraded by guessing a polarity.
///
/// The fields are private so callers cannot construct or later mutate a
/// proposition/generation pair independently. Owners that already maintain a
/// canonical proposition digest use [`Self::new`]; callers holding canonical
/// value bytes use [`Self::from_canonical_value`], which derives the digest.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct ContradictionEvidenceV2 {
    proposition_digest: Digest32,
    generation_vector_digest: Digest32,
    polarity: PropositionPolarityV2,
}

impl ContradictionEvidenceV2 {
    /// Bind a digest already derived by the authoritative proposition owner.
    /// This constructor does not accept a separate value, so no value/digest
    /// pair can disagree inside this type.
    pub fn new(
        proposition_digest: Digest32,
        generation_vector_digest: Digest32,
        polarity: PropositionPolarityV2,
    ) -> Result<Self, RecallErrorV1> {
        let value = Self {
            proposition_digest,
            generation_vector_digest,
            polarity,
        };
        value.validate(generation_vector_digest)?;
        Ok(value)
    }

    /// Derive the proposition digest from the canonical value bytes inside the
    /// constructor. Empty values are rejected before they can become evidence.
    pub fn from_canonical_value(
        canonical_value: &[u8],
        generation_vector_digest: Digest32,
        polarity: PropositionPolarityV2,
    ) -> Result<Self, RecallErrorV1> {
        if canonical_value.is_empty() {
            return Err(RecallErrorV1::EmptyDigest("canonical_proposition_value"));
        }
        Self::new(
            Digest32::of_bytes(canonical_value),
            generation_vector_digest,
            polarity,
        )
    }

    #[must_use]
    pub fn proposition_digest(&self) -> Digest32 {
        self.proposition_digest
    }

    #[must_use]
    pub fn generation_vector_digest(&self) -> Digest32 {
        self.generation_vector_digest
    }

    #[must_use]
    pub fn polarity(&self) -> PropositionPolarityV2 {
        self.polarity
    }

    pub fn validate(&self, expected_generation: Digest32) -> Result<(), RecallErrorV1> {
        if self.proposition_digest.is_zero() {
            return Err(RecallErrorV1::EmptyDigest("contradiction_proposition"));
        }
        if self.generation_vector_digest.is_zero() {
            return Err(RecallErrorV1::EmptyDigest("contradiction_generation"));
        }
        if self.generation_vector_digest != expected_generation {
            return Err(RecallErrorV1::GenerationVectorMismatch(
                "contradiction_evidence".to_string(),
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.retrieval-proposition-evidence.v2".to_vec();
        bytes.extend_from_slice(self.proposition_digest.as_array());
        bytes.extend_from_slice(self.generation_vector_digest.as_array());
        bytes.push(match self.polarity {
            PropositionPolarityV2::Affirmed => 0,
            PropositionPolarityV2::Denied => 1,
            PropositionPolarityV2::ConflictReported => 2,
        });
        Digest32::of_bytes(&bytes)
    }
}

pub(crate) fn contradiction_population_count(entries: &[CandidateUnionEntryV1]) -> usize {
    let mut polarities = BTreeMap::<(Digest32, Digest32), u8>::new();
    for entry in entries {
        for claim in &entry.contradiction_group_digests {
            let mask = match claim.polarity {
                PropositionPolarityV2::Affirmed => 1,
                PropositionPolarityV2::Denied => 2,
                PropositionPolarityV2::ConflictReported => 0,
            };
            *polarities
                .entry((claim.proposition_digest, claim.generation_vector_digest))
                .or_default() |= mask;
        }
    }
    polarities.values().filter(|mask| **mask == 3).count()
}

/// Derive the decision set without rewriting the observed input receipt.
/// Callers retain the original union digest/count for audit accounting; only
/// this admitted view may seed dynamics or contribute coverage, OOD or conflict.
pub(crate) fn policy_admitted_union(
    union: &CandidateUnionV1,
    policy: &RetrievalPolicyV1,
) -> Result<CandidateUnionV1, RecallErrorV1> {
    union.validate()?;
    policy.validate()?;
    if union.policy_digest != policy.digest() {
        return Err(RecallErrorV1::DigestMismatch("admission_policy"));
    }
    let mut admitted = union.clone();
    admitted.entries.retain(|entry| {
        entry.weighted_score > FixedQ32::ZERO && entry.weighted_score >= policy.minimum_total_score
    });
    let channels = admitted
        .entries
        .iter()
        .flat_map(|entry| entry.channels.iter().copied())
        .collect::<BTreeSet<_>>();
    admitted.distinct_channels =
        u32::try_from(channels.len()).map_err(|_| RecallErrorV1::Arithmetic)?;
    admitted.union_digest = admitted.compute_union_digest();
    admitted.validate()?;
    Ok(admitted)
}
