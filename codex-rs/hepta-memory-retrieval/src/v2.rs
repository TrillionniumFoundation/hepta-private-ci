//! Additive, owner-local binding for the complete supplied retrieval input.
//!
//! V2 is a native Rust result, not a registered ModulePort or wire protocol.
//! It binds exactly the caller's bounded candidates, including omitted ones;
//! it does not authenticate sources, establish external completeness or
//! freshness, or grant authority. The V1 result and digest remain unchanged.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::Error;
use crate::RetrievalReceipt;
use crate::RetrievalRequest;
use crate::push_id;
use crate::retrieve_request;

/// A V2 integrity binding for the supplied input and its complete V1 result.
///
/// Consumers can compare `request_binding_digest` against
/// [`RetrievalRequest::binding_digest_v2`] for their expected input. The
/// embedded `retrieval.receipt_digest` continues to use its V1 byte scope;
/// the outer `receipt_digest` also binds the full input and omission count.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalReceiptV2 {
    pub receipt_version: u32,
    pub retrieval: RetrievalReceipt,
    pub caller_candidate_count: usize,
    pub request_binding_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl RetrievalRequest {
    /// Validate and bind the full supplied query, limits, candidates and scores.
    ///
    /// Candidate order and citation order are canonicalized. This checks the
    /// same bounded, live-record and scoring invariants as [`crate::retrieve`];
    /// no source authentication or external freshness is established.
    pub fn binding_digest_v2(&self) -> Result<Digest32, Error> {
        retrieve_request(self)?;
        Ok(digest_request(self))
    }
}

/// Preserve V1 retrieval while additionally binding every supplied candidate.
pub fn retrieve_v2(request: RetrievalRequest) -> Result<RetrievalReceiptV2, Error> {
    // Validate before sorting or hashing the full input. Borrowing also avoids
    // cloning an oversized candidate set before its bounds are checked.
    let retrieval = retrieve_request(&request)?;
    let request_binding_digest = digest_request(&request);
    let caller_candidate_count = request.candidates.len();
    let receipt_version = 2_u32;
    let mut bytes = b"hepta.memory.retrieval.receipt.v2".to_vec();
    bytes.extend_from_slice(&receipt_version.to_be_bytes());
    bytes.extend_from_slice(request_binding_digest.as_array());
    push_count(&mut bytes, caller_candidate_count);
    bytes.extend_from_slice(retrieval.receipt_digest.as_array());
    push_count(&mut bytes, retrieval.results.len());
    push_count(&mut bytes, retrieval.omitted_count);
    bytes.extend_from_slice(&[0, 0]); // Inner and outer deny-all authority bits.

    Ok(RetrievalReceiptV2 {
        receipt_version,
        retrieval,
        caller_candidate_count,
        request_binding_digest,
        receipt_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn digest_request(request: &RetrievalRequest) -> Digest32 {
    let mut candidates = request.candidates.iter().collect::<Vec<_>>();
    candidates.sort_by(|left, right| left.record.record_id.cmp(&right.record.record_id));
    let mut bytes = b"hepta.memory.retrieval.request.v2".to_vec();
    push_id(&mut bytes, &request.query_id);
    bytes.extend_from_slice(request.query_digest.as_array());
    bytes.extend_from_slice(request.snapshot_digest.as_array());
    push_count(&mut bytes, request.maximum_results);
    push_count(&mut bytes, candidates.len());
    for candidate in candidates {
        push_id(&mut bytes, &candidate.record.record_id);
        bytes.extend_from_slice(candidate.record.record_digest().as_array());
        bytes.extend_from_slice(candidate.snapshot_digest.as_array());
        bytes.extend_from_slice(&candidate.lexical_score.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.graph_score.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.freshness_score.raw().to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn push_count(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}

#[cfg(test)]
#[path = "v2_tests.rs"]
mod tests;
