//! Product-facing retrieval binding over one authenticated owner observation.
//!
//! This layer keeps the existing V1/V2 compatibility surfaces intact while
//! providing the stricter limits and provenance binding required by product
//! callers. It still does not authenticate an owner by itself: the caller must
//! obtain `owner_observation_digest` from the owning read path and revalidate
//! selected records before physical attachment.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::Error;
use crate::MemoryCueV1;
use crate::RecallErrorV1;
use crate::RetrievalCandidate;
use crate::RetrievalChannelV1;
use crate::RetrievalReceiptV2;
use crate::RetrievalRequest;
use crate::retrieve_v2;

/// Product hot-path ceiling from the memory.retrieval target contract.
pub const MAX_PRODUCT_RETRIEVAL_CANDIDATES: usize = 512;
/// Product hot-path result ceiling from the memory.retrieval target contract.
pub const MAX_PRODUCT_RETRIEVAL_RESULTS: usize = 16;
/// Owner relation evidence is bounded independently from raw candidate count.
pub const MAX_PRODUCT_RELATION_EVIDENCE: usize = 512;

const PRODUCT_RECEIPT_V1_DOMAIN: &[u8] = b"hepta.memory.retrieval.product.v1";
const PRODUCT_RECEIPT_V2_DOMAIN: &[u8] = b"hepta.memory.retrieval.product.v2";

/// Explicit inputs for deterministic cue construction.
///
/// The digests must come from the owning objective/context/snapshot producers;
/// this function does not infer authority or freshness from their values.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CueCompileRequestV1 {
    pub cue_id: StableId,
    pub objective_digest: Digest32,
    pub approved_context_digest: Digest32,
    pub snapshot_key: CognitiveSnapshotKeyV1,
    pub cue_profile_digest: Digest32,
}

/// Compile and validate one generation-bound memory cue.
pub fn compile_cue(request: CueCompileRequestV1) -> Result<MemoryCueV1, RecallErrorV1> {
    let cue = MemoryCueV1 {
        cue_id: request.cue_id,
        objective_digest: request.objective_digest,
        approved_context_digest: request.approved_context_digest,
        snapshot_key: request.snapshot_key,
        cue_profile_digest: request.cue_profile_digest,
    };
    cue.validate()?;
    Ok(cue)
}

/// Product input produced from one bounded owner-generator observation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductRetrievalRequestV1 {
    pub query_id: StableId,
    pub query_digest: Digest32,
    pub snapshot_digest: Digest32,
    /// Digest emitted by the owning generator/read transaction. It binds
    /// channel limits and owner-side candidate/support observations outside the
    /// generic retrieval crate.
    pub owner_observation_digest: Digest32,
    pub maximum_results: usize,
    pub candidates: Vec<RetrievalCandidate>,
}

/// Product receipt binding the exact owner observation and complete supplied
/// candidate set. The nested V2 receipt remains available for compatibility.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductRetrievalReceiptV1 {
    pub receipt_version: u32,
    pub owner_observation_digest: Digest32,
    pub retrieval: RetrievalReceiptV2,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// Registered owner KG relation meanings admitted into product provenance.
/// This is deliberately narrower than arbitrary/free-form relation strings.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ProductRelationKindV1 {
    Supports,
    Contradicts,
    TemporalBefore,
    TemporalAfter,
    Causes,
    Enables,
    ProcedureStep,
}

impl ProductRelationKindV1 {
    /// Parse the canonical token emitted by the owner retrieval observation.
    #[must_use]
    pub fn from_owner_token(value: &str) -> Option<Self> {
        match value {
            "supports" => Some(Self::Supports),
            "contradicts" => Some(Self::Contradicts),
            "temporal_before" => Some(Self::TemporalBefore),
            "temporal_after" => Some(Self::TemporalAfter),
            "causes" => Some(Self::Causes),
            "enables" => Some(Self::Enables),
            "procedure_step" => Some(Self::ProcedureStep),
            _ => None,
        }
    }

    #[must_use]
    pub const fn retrieval_channel(self) -> RetrievalChannelV1 {
        match self {
            Self::Supports | Self::Contradicts => RetrievalChannelV1::ContradictionSupport,
            Self::TemporalBefore | Self::TemporalAfter => RetrievalChannelV1::Temporal,
            Self::Causes | Self::Enables => RetrievalChannelV1::Causal,
            Self::ProcedureStep => RetrievalChannelV1::Procedural,
        }
    }
}

/// Exact typed relation provenance supplied by the authenticated owner read.
/// Both the candidate and support revision must already be present in the
/// complete admitted product candidate set; relation evidence cannot introduce
/// a new record or widen scope.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductRelationEvidenceV1 {
    pub candidate_record_id: StableId,
    pub candidate_revision: Revision,
    pub support_record_id: StableId,
    pub support_revision: Revision,
    pub relation: ProductRelationKindV1,
    pub support_digest: Digest32,
    pub relation_group_digest: Digest32,
}

impl ProductRelationEvidenceV1 {
    #[must_use]
    pub const fn retrieval_channel(&self) -> RetrievalChannelV1 {
        self.relation.retrieval_channel()
    }

    #[must_use]
    pub fn contradiction_group_digest(&self) -> Option<Digest32> {
        (self.relation == ProductRelationKindV1::Contradicts)
            .then_some(self.relation_group_digest)
    }
}

/// V2 product request adds typed owner relation evidence without changing the
/// deterministic owner RRF score. `owner_relation_evidence_count` and the limit
/// bit describe the owner's complete bounded observation before Lane-C cut
/// intersection; `relation_evidence` contains the subset whose candidate and
/// support revisions were both admitted by that cut.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductRetrievalRequestV2 {
    pub retrieval: ProductRetrievalRequestV1,
    pub owner_relation_evidence_count: usize,
    pub owner_relation_limit_reached: bool,
    pub relation_evidence: Vec<ProductRelationEvidenceV1>,
}

/// V2 product receipt binds all admitted typed KG relation evidence, including
/// explicit coverage/omission facts for owner relation enumeration.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductRetrievalReceiptV2 {
    pub receipt_version: u32,
    pub retrieval: ProductRetrievalReceiptV1,
    pub owner_relation_evidence_count: usize,
    pub owner_relation_limit_reached: bool,
    pub omitted_relation_evidence_count: usize,
    pub relation_evidence: Vec<ProductRelationEvidenceV1>,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductRetrievalError {
    EmptyOwnerObservationDigest,
    InvalidMaximumResults,
    CandidateLimitExceeded,
    RelationEvidenceLimitExceeded,
    RelationEvidenceCountMismatch,
    RelationCandidateNotAdmitted(String),
    RelationSupportNotAdmitted(String),
    EmptyRelationDigest(&'static str),
    DuplicateRelationEvidence,
    Retrieval(Error),
}

impl fmt::Display for ProductRetrievalError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProductRetrievalError {}

impl From<Error> for ProductRetrievalError {
    fn from(error: Error) -> Self {
        Self::Retrieval(error)
    }
}

/// Rank one bounded owner observation under product limits.
///
/// This compatibility product surface deliberately reuses the V2 complete-input
/// binding rather than creating a second ranking algorithm. New owner-backed
/// callers that possess typed relation evidence should use [`retrieve_product_v2`].
pub fn retrieve_product_v1(
    request: ProductRetrievalRequestV1,
) -> Result<ProductRetrievalReceiptV1, ProductRetrievalError> {
    if request.owner_observation_digest.is_zero() {
        return Err(ProductRetrievalError::EmptyOwnerObservationDigest);
    }
    if request.maximum_results == 0 || request.maximum_results > MAX_PRODUCT_RETRIEVAL_RESULTS {
        return Err(ProductRetrievalError::InvalidMaximumResults);
    }
    if request.candidates.len() > MAX_PRODUCT_RETRIEVAL_CANDIDATES {
        return Err(ProductRetrievalError::CandidateLimitExceeded);
    }

    let owner_observation_digest = request.owner_observation_digest;
    let retrieval = retrieve_v2(RetrievalRequest {
        query_id: request.query_id,
        query_digest: request.query_digest,
        snapshot_digest: request.snapshot_digest,
        maximum_results: request.maximum_results,
        candidates: request.candidates,
    })?;

    let receipt_version = 1_u32;
    let mut bytes = PRODUCT_RECEIPT_V1_DOMAIN.to_vec();
    bytes.extend_from_slice(&receipt_version.to_be_bytes());
    bytes.extend_from_slice(owner_observation_digest.as_array());
    bytes.extend_from_slice(retrieval.request_binding_digest.as_array());
    bytes.extend_from_slice(retrieval.receipt_digest.as_array());
    push_count(&mut bytes, retrieval.caller_candidate_count);
    push_count(&mut bytes, retrieval.retrieval.results.len());
    push_count(&mut bytes, retrieval.retrieval.omitted_count);
    bytes.push(0); // deny-all authority posture marker

    Ok(ProductRetrievalReceiptV1 {
        receipt_version,
        owner_observation_digest,
        retrieval,
        receipt_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

/// Bind typed KG relation provenance for the exact complete product candidate
/// set. Relation evidence does not change the owner RRF score in this version.
pub fn retrieve_product_v2(
    request: ProductRetrievalRequestV2,
) -> Result<ProductRetrievalReceiptV2, ProductRetrievalError> {
    if request.owner_relation_evidence_count > MAX_PRODUCT_RELATION_EVIDENCE
        || request.relation_evidence.len() > MAX_PRODUCT_RELATION_EVIDENCE
    {
        return Err(ProductRetrievalError::RelationEvidenceLimitExceeded);
    }
    if request.relation_evidence.len() > request.owner_relation_evidence_count {
        return Err(ProductRetrievalError::RelationEvidenceCountMismatch);
    }
    let admitted = request
        .retrieval
        .candidates
        .iter()
        .map(|candidate| {
            (
                candidate.record.record_id.clone(),
                candidate.record.revision,
            )
        })
        .collect::<BTreeSet<_>>();
    let mut relation_evidence = request.relation_evidence;
    let mut seen = BTreeSet::new();
    for evidence in &relation_evidence {
        if !admitted.contains(&(
            evidence.candidate_record_id.clone(),
            evidence.candidate_revision,
        )) {
            return Err(ProductRetrievalError::RelationCandidateNotAdmitted(
                evidence.candidate_record_id.to_string(),
            ));
        }
        if !admitted.contains(&(
            evidence.support_record_id.clone(),
            evidence.support_revision,
        )) {
            return Err(ProductRetrievalError::RelationSupportNotAdmitted(
                evidence.support_record_id.to_string(),
            ));
        }
        if evidence.support_digest.is_zero() {
            return Err(ProductRetrievalError::EmptyRelationDigest("support"));
        }
        if evidence.relation_group_digest.is_zero() {
            return Err(ProductRetrievalError::EmptyRelationDigest("relation_group"));
        }
        let identity = (
            evidence.candidate_record_id.clone(),
            evidence.candidate_revision,
            evidence.support_record_id.clone(),
            evidence.support_revision,
            evidence.relation,
            evidence.support_digest,
            evidence.relation_group_digest,
        );
        if !seen.insert(identity) {
            return Err(ProductRetrievalError::DuplicateRelationEvidence);
        }
    }
    relation_evidence.sort_by(|left, right| {
        left.candidate_record_id
            .cmp(&right.candidate_record_id)
            .then_with(|| left.candidate_revision.cmp(&right.candidate_revision))
            .then_with(|| left.support_record_id.cmp(&right.support_record_id))
            .then_with(|| left.support_revision.cmp(&right.support_revision))
            .then_with(|| left.relation.cmp(&right.relation))
            .then_with(|| left.support_digest.cmp(&right.support_digest))
            .then_with(|| left.relation_group_digest.cmp(&right.relation_group_digest))
    });

    let owner_relation_evidence_count = request.owner_relation_evidence_count;
    let owner_relation_limit_reached = request.owner_relation_limit_reached;
    let omitted_relation_evidence_count = owner_relation_evidence_count - relation_evidence.len();
    let retrieval = retrieve_product_v1(request.retrieval)?;
    let receipt_version = 2_u32;
    let mut bytes = PRODUCT_RECEIPT_V2_DOMAIN.to_vec();
    bytes.extend_from_slice(&receipt_version.to_be_bytes());
    bytes.extend_from_slice(retrieval.receipt_digest.as_array());
    push_count(&mut bytes, owner_relation_evidence_count);
    bytes.push(u8::from(owner_relation_limit_reached));
    push_count(&mut bytes, omitted_relation_evidence_count);
    push_count(&mut bytes, relation_evidence.len());
    for evidence in &relation_evidence {
        push_id(&mut bytes, &evidence.candidate_record_id);
        bytes.extend_from_slice(&evidence.candidate_revision.get().to_be_bytes());
        push_id(&mut bytes, &evidence.support_record_id);
        bytes.extend_from_slice(&evidence.support_revision.get().to_be_bytes());
        bytes.push(relation_code(evidence.relation));
        bytes.push(channel_code(evidence.retrieval_channel()));
        bytes.extend_from_slice(evidence.support_digest.as_array());
        bytes.extend_from_slice(evidence.relation_group_digest.as_array());
    }
    bytes.push(0); // deny-all authority posture marker

    Ok(ProductRetrievalReceiptV2 {
        receipt_version,
        retrieval,
        owner_relation_evidence_count,
        owner_relation_limit_reached,
        omitted_relation_evidence_count,
        relation_evidence,
        receipt_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn push_count(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

const fn relation_code(value: ProductRelationKindV1) -> u8 {
    match value {
        ProductRelationKindV1::Supports => 0,
        ProductRelationKindV1::Contradicts => 1,
        ProductRelationKindV1::TemporalBefore => 2,
        ProductRelationKindV1::TemporalAfter => 3,
        ProductRelationKindV1::Causes => 4,
        ProductRelationKindV1::Enables => 5,
        ProductRelationKindV1::ProcedureStep => 6,
    }
}

const fn channel_code(value: RetrievalChannelV1) -> u8 {
    match value {
        RetrievalChannelV1::Lexical => 0,
        RetrievalChannelV1::Vector => 1,
        RetrievalChannelV1::Entity => 2,
        RetrievalChannelV1::Temporal => 3,
        RetrievalChannelV1::Causal => 4,
        RetrievalChannelV1::Procedural => 5,
        RetrievalChannelV1::ContradictionSupport => 6,
    }
}

#[cfg(test)]
#[path = "product_tests.rs"]
mod tests;
