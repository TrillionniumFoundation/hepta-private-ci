//! Bounded multi-peer federation orchestration and deterministic merge.

use std::collections::{BTreeMap, BTreeSet};
use std::thread;

use codex_hepta_types::{AuthorityPosture, Digest32, StableId};

use crate::{
    FederatedCompletenessV2, FederatedCoverageV2, FederatedEvidenceItemV2, FederatedLeaseV2,
    FederatedQueryV2, FederatedResultV2, FederatedValidityV2, FederationAuthorityVerifierV2,
    FederationClockV2, FederationPeerSignatureVerifierV2, FederationTransportV2, FederationV2Error,
    MAX_FEDERATED_RESULTS_V2, execute_once,
};

pub const MAX_FEDERATED_PEERS_V2: usize = 16;
const FANOUT_RESULT_DOMAIN: &[u8] = b"hepta.memory-federation.fanout-result.v2\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedPeerReadV2 {
    pub query: FederatedQueryV2,
    pub lease: FederatedLeaseV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedFanoutRequestV2 {
    pub request_id: StableId,
    pub peer_reads: Vec<FederatedPeerReadV2>,
    pub maximum_total_results: u32,
    pub maximum_concurrency: u8,
}

impl FederatedFanoutRequestV2 {
    fn validate(&self, now_unix_ms: u64) -> Result<(), FederationFanoutErrorV2> {
        if self.peer_reads.is_empty() || self.peer_reads.len() > MAX_FEDERATED_PEERS_V2 {
            return Err(FederationFanoutErrorV2::InvalidPeerCount);
        }
        let maximum_total_results = usize::try_from(self.maximum_total_results).unwrap_or(usize::MAX);
        if maximum_total_results == 0 || maximum_total_results > MAX_FEDERATED_RESULTS_V2 {
            return Err(FederationFanoutErrorV2::InvalidResultLimit);
        }
        let maximum_concurrency = usize::from(self.maximum_concurrency);
        if maximum_concurrency == 0 || maximum_concurrency > MAX_FEDERATED_PEERS_V2 {
            return Err(FederationFanoutErrorV2::InvalidConcurrency);
        }

        let mut peers = BTreeSet::new();
        let mut reserved_results = 0usize;
        for peer_read in &self.peer_reads {
            peer_read
                .query
                .validate(now_unix_ms)
                .map_err(FederationFanoutErrorV2::InvalidPeerQuery)?;
            if peer_read.query.peer_id != peer_read.lease.peer_id {
                return Err(FederationFanoutErrorV2::PeerLeaseMismatch);
            }
            if !peers.insert(peer_read.query.peer_id.clone()) {
                return Err(FederationFanoutErrorV2::DuplicatePeer);
            }
            reserved_results = reserved_results
                .checked_add(usize::try_from(peer_read.query.maximum_results).unwrap_or(usize::MAX))
                .ok_or(FederationFanoutErrorV2::InvalidResultLimit)?;
        }
        if reserved_results > maximum_total_results {
            return Err(FederationFanoutErrorV2::InvalidResultLimit);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederatedPeerDispositionV2 {
    Complete,
    Partial,
    Empty,
    StaleGeneration,
    Indeterminate,
    Failed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedPeerSummaryV2 {
    pub peer_id: StableId,
    pub disposition: FederatedPeerDispositionV2,
    pub item_count: u32,
    pub expires_unix_ms: Option<u64>,
    pub result_digest: Option<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedPeerFailureV2 {
    pub peer_id: StableId,
    pub error: FederationV2Error,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedFanoutResultV2 {
    pub request_id: StableId,
    pub items: Vec<FederatedEvidenceItemV2>,
    pub coverage: FederatedCoverageV2,
    pub completeness: FederatedCompletenessV2,
    pub peer_summaries: Vec<FederatedPeerSummaryV2>,
    pub failures: Vec<FederatedPeerFailureV2>,
    pub result_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl FederatedFanoutResultV2 {
    #[must_use]
    pub fn compute_result_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(FANOUT_RESULT_DOMAIN);
        push_id(&mut bytes, &self.request_id);
        push_u64(&mut bytes, u64::try_from(self.items.len()).unwrap_or(u64::MAX));
        for item in &self.items {
            push_item(&mut bytes, item);
        }
        for value in [
            self.coverage.requested_peers,
            self.coverage.completed_peers,
            self.coverage.failed_peers,
            self.coverage.truncated_items,
        ] {
            push_u64(&mut bytes, u64::from(value));
        }
        bytes.push(completeness_code(self.completeness));
        push_u64(
            &mut bytes,
            u64::try_from(self.peer_summaries.len()).unwrap_or(u64::MAX),
        );
        for summary in &self.peer_summaries {
            push_id(&mut bytes, &summary.peer_id);
            bytes.push(disposition_code(summary.disposition));
            push_u64(&mut bytes, u64::from(summary.item_count));
            push_optional_u64(&mut bytes, summary.expires_unix_ms);
            push_optional_digest(&mut bytes, summary.result_digest);
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FederationFanoutErrorV2 {
    InvalidPeerCount,
    InvalidConcurrency,
    InvalidResultLimit,
    InvalidPeerQuery(crate::LegacyFederationV2Error),
    PeerLeaseMismatch,
    DuplicatePeer,
    ConflictingEvidenceIdentity,
    WorkerPanicked,
}

pub fn fanout_once<T, A, P, C>(
    transport: &T,
    authority_verifier: &A,
    peer_verifier: &P,
    clock: &C,
    request: FederatedFanoutRequestV2,
) -> Result<FederatedFanoutResultV2, FederationFanoutErrorV2>
where
    T: FederationTransportV2,
    A: FederationAuthorityVerifierV2,
    P: FederationPeerSignatureVerifierV2,
    C: FederationClockV2,
{
    let now_unix_ms = clock
        .now_unix_ms()
        .map_err(|_| FederationFanoutErrorV2::InvalidPeerCount)?;
    request.validate(now_unix_ms)?;

    let mut outcomes = Vec::with_capacity(request.peer_reads.len());
    let maximum_concurrency = usize::from(request.maximum_concurrency);
    for chunk in request.peer_reads.chunks(maximum_concurrency) {
        let chunk_outcomes = thread::scope(|scope| {
            let mut handles = Vec::with_capacity(chunk.len());
            for peer_read in chunk {
                handles.push(scope.spawn(move || {
                    let peer_id = peer_read.query.peer_id.clone();
                    let result = execute_once(
                        transport,
                        authority_verifier,
                        peer_verifier,
                        clock,
                        peer_read.query.clone(),
                        &peer_read.lease,
                    );
                    (peer_id, result)
                }));
            }
            let mut values = Vec::with_capacity(handles.len());
            for handle in handles {
                values.push(
                    handle
                        .join()
                        .map_err(|_| FederationFanoutErrorV2::WorkerPanicked)?,
                );
            }
            Ok::<_, FederationFanoutErrorV2>(values)
        })?;
        outcomes.extend(chunk_outcomes);
    }
    outcomes.sort_by(|left, right| left.0.cmp(&right.0));
    merge_outcomes(request.request_id, outcomes)
}

fn merge_outcomes(
    request_id: StableId,
    outcomes: Vec<(StableId, Result<FederatedResultV2, FederationV2Error>)>,
) -> Result<FederatedFanoutResultV2, FederationFanoutErrorV2> {
    let requested_peers = u32::try_from(outcomes.len()).unwrap_or(u32::MAX);
    let mut completed_peers = 0u32;
    let mut failed_peers = 0u32;
    let mut truncated_items = 0u32;
    let mut peer_summaries = Vec::with_capacity(outcomes.len());
    let mut failures = Vec::new();
    let mut merged = BTreeMap::new();
    let mut saw_partial = false;

    for (peer_id, outcome) in outcomes {
        match outcome {
            Err(error) => {
                failed_peers = failed_peers.saturating_add(1);
                peer_summaries.push(FederatedPeerSummaryV2 {
                    peer_id: peer_id.clone(),
                    disposition: FederatedPeerDispositionV2::Failed,
                    item_count: 0,
                    expires_unix_ms: None,
                    result_digest: None,
                });
                failures.push(FederatedPeerFailureV2 { peer_id, error });
            }
            Ok(result) => {
                truncated_items = truncated_items.saturating_add(result.coverage.truncated_items);
                let disposition = disposition_for_result(&result);
                if matches!(disposition, FederatedPeerDispositionV2::Indeterminate) {
                    failed_peers = failed_peers.saturating_add(1);
                } else {
                    completed_peers = completed_peers.saturating_add(1);
                }
                if matches!(
                    disposition,
                    FederatedPeerDispositionV2::Partial
                        | FederatedPeerDispositionV2::StaleGeneration
                        | FederatedPeerDispositionV2::Indeterminate
                ) {
                    saw_partial = true;
                }
                for item in &result.items {
                    let identity = (
                        item.source_owner_id.clone(),
                        item.record_id.clone(),
                        item.record_revision,
                    );
                    if let Some(existing) = merged.get(&identity) {
                        if existing != item {
                            return Err(FederationFanoutErrorV2::ConflictingEvidenceIdentity);
                        }
                    } else {
                        merged.insert(identity, item.clone());
                    }
                }
                peer_summaries.push(FederatedPeerSummaryV2 {
                    peer_id,
                    disposition,
                    item_count: u32::try_from(result.items.len()).unwrap_or(u32::MAX),
                    expires_unix_ms: Some(result.expires_unix_ms),
                    result_digest: Some(result.result_digest),
                });
            }
        }
    }

    let items = merged.into_values().collect::<Vec<_>>();
    let completeness = if completed_peers == 0 {
        FederatedCompletenessV2::Indeterminate
    } else if failed_peers > 0 || saw_partial {
        FederatedCompletenessV2::Partial
    } else if items.is_empty() {
        FederatedCompletenessV2::Empty
    } else {
        FederatedCompletenessV2::Complete
    };
    let mut result = FederatedFanoutResultV2 {
        request_id,
        items,
        coverage: FederatedCoverageV2 {
            requested_peers,
            completed_peers,
            failed_peers,
            truncated_items,
        },
        completeness,
        peer_summaries,
        failures,
        result_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.result_digest = result.compute_result_digest();
    Ok(result)
}

fn disposition_for_result(result: &FederatedResultV2) -> FederatedPeerDispositionV2 {
    if result.validity == FederatedValidityV2::Indeterminate
        || result.completeness == FederatedCompletenessV2::Indeterminate
    {
        FederatedPeerDispositionV2::Indeterminate
    } else if result.validity == FederatedValidityV2::StaleGeneration {
        FederatedPeerDispositionV2::StaleGeneration
    } else {
        match result.completeness {
            FederatedCompletenessV2::Complete => FederatedPeerDispositionV2::Complete,
            FederatedCompletenessV2::Partial => FederatedPeerDispositionV2::Partial,
            FederatedCompletenessV2::Empty => FederatedPeerDispositionV2::Empty,
            FederatedCompletenessV2::Indeterminate => FederatedPeerDispositionV2::Indeterminate,
        }
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_u64(bytes, u64::try_from(value.as_str().len()).unwrap_or(u64::MAX));
    bytes.extend_from_slice(value.as_str().as_bytes());
}

fn push_item(bytes: &mut Vec<u8>, item: &FederatedEvidenceItemV2) {
    push_id(bytes, &item.source_owner_id);
    push_id(bytes, &item.record_id);
    push_u64(bytes, item.record_revision.get());
    for digest in [item.record_digest, item.support_digest, item.validity_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_optional_u64(bytes: &mut Vec<u8>, value: Option<u64>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_u64(bytes, value);
        }
        None => bytes.push(0),
    }
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(value.as_array());
        }
        None => bytes.push(0),
    }
}

const fn completeness_code(value: FederatedCompletenessV2) -> u8 {
    match value {
        FederatedCompletenessV2::Complete => 0,
        FederatedCompletenessV2::Partial => 1,
        FederatedCompletenessV2::Empty => 2,
        FederatedCompletenessV2::Indeterminate => 3,
    }
}

const fn disposition_code(value: FederatedPeerDispositionV2) -> u8 {
    match value {
        FederatedPeerDispositionV2::Complete => 0,
        FederatedPeerDispositionV2::Partial => 1,
        FederatedPeerDispositionV2::Empty => 2,
        FederatedPeerDispositionV2::StaleGeneration => 3,
        FederatedPeerDispositionV2::Indeterminate => 4,
        FederatedPeerDispositionV2::Failed => 5,
    }
}

#[cfg(test)]
#[path = "fanout_tests.rs"]
mod tests;
