//! Product-facing retrieval binding over one authenticated owner observation.
//!
//! This layer keeps the existing V1/V2 compatibility surfaces intact while
//! providing the stricter limits and provenance binding required by product
//! callers.  It still does not authenticate an owner by itself: the caller must
//! obtain `owner_observation_digest` from the owning read path and revalidate
//! selected records before physical attachment.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::Error;
use crate::MemoryCueV1;
use crate::RecallErrorV1;
use crate::RetrievalCandidate;
use crate::RetrievalReceiptV2;
use crate::RetrievalRequest;
use crate::retrieve_v2;

/// Product hot-path ceiling from the memory.retrieval target contract.
pub const MAX_PRODUCT_RETRIEVAL_CANDIDATES: usize = 512;
/// Product hot-path result ceiling from the memory.retrieval target contract.
pub const MAX_PRODUCT_RETRIEVAL_RESULTS: usize = 16;

const PRODUCT_RECEIPT_DOMAIN: &[u8] = b"hepta.memory.retrieval.product.v1";

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
    /// Digest emitted by the owning generator/read transaction.  It binds
    /// channel limits and owner-side candidate/support observations outside the
    /// generic retrieval crate.
    pub owner_observation_digest: Digest32,
    pub maximum_results: usize,
    pub candidates: Vec<RetrievalCandidate>,
}

/// Product receipt binding the exact owner observation and complete supplied
/// candidate set.  The nested V2 receipt remains available for compatibility.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductRetrievalReceiptV1 {
    pub receipt_version: u32,
    pub owner_observation_digest: Digest32,
    pub retrieval: RetrievalReceiptV2,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductRetrievalError {
    EmptyOwnerObservationDigest,
    InvalidMaximumResults,
    CandidateLimitExceeded,
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
/// This is the product composition surface.  It deliberately reuses the V2
/// complete-input binding rather than creating a second ranking algorithm.
/// Selected records still require owner revalidation immediately before use.
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
    let mut bytes = PRODUCT_RECEIPT_DOMAIN.to_vec();
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

fn push_count(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}

#[cfg(test)]
#[path = "product_tests.rs"]
mod tests;
