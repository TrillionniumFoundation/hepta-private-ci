use codex_hepta_types::{AuthorityPosture, Digest32, StableId};

use crate::v3::{
    CapabilityAuthorityEnvelopeV3, CapabilityVerifierV3, FederatedCompletenessV3,
    FederatedCoverageV3, FederatedEvidenceItemV3, FederatedQueryV3, FederatedResultV3,
    FederationCancellationTokenV3, FederationClockV3, FederationKeyResolverV3,
    FederationTransportV3, FederationV3Error, MAX_FEDERATED_RESULTS_V3, MAX_FEDERATION_PEERS_V3,
    execute_once_v3,
};

const ORCHESTRATION_DOMAIN: &[u8] = b"hepta.memory-federation.orchestration.v3";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedPeerFailureV3 {
    pub peer_id: StableId,
    pub query_id: StableId,
    pub error: FederationV3Error,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedOrchestrationV3 {
    pub results: Vec<FederatedResultV3>,
    pub failures: Vec<FederatedPeerFailureV3>,
    pub items: Vec<FederatedEvidenceItemV3>,
    pub coverage: FederatedCoverageV3,
    pub completeness: FederatedCompletenessV3,
    pub expires_unix_ms: u64,
    pub orchestration_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// Bounded multi-peer fan-out with per-peer failure isolation.
///
/// Unlike the lower-level aggregate helper, this product orchestrator records
/// structural/authentication/transport failure for one peer as failed coverage
/// while retaining valid results from other peers. It never promotes such an
/// incomplete federation to `Complete` or `Empty`.
pub fn execute_federation_resilient_v3<T, C, V, K>(
    transport: &T,
    clock: &C,
    capability_verifier: &V,
    peer_keys: &K,
    requests: Vec<(FederatedQueryV3, CapabilityAuthorityEnvelopeV3)>,
) -> Result<FederatedOrchestrationV3, FederationV3Error>
where
    T: FederationTransportV3,
    C: FederationClockV3,
    V: CapabilityVerifierV3,
    K: FederationKeyResolverV3,
{
    if requests.is_empty() || requests.len() > MAX_FEDERATION_PEERS_V3 {
        return Err(FederationV3Error::InvalidPeerCount);
    }
    let requested_peers = requests.len();
    let outcomes = std::thread::scope(|scope| {
        let mut handles = Vec::with_capacity(requested_peers);
        for (query, authority) in requests {
            handles.push(scope.spawn(move || {
                let peer_id = query.peer_id.clone();
                let query_id = query.query_id.clone();
                let cancellation = FederationCancellationTokenV3::default();
                let outcome = execute_once_v3(
                    transport,
                    clock,
                    capability_verifier,
                    peer_keys,
                    query,
                    &authority,
                    &cancellation,
                );
                (peer_id, query_id, outcome)
            }));
        }
        let mut joined = Vec::with_capacity(handles.len());
        for handle in handles {
            joined.push(handle.join().map_err(|_| FederationV3Error::WorkerPanicked)?);
        }
        Ok::<_, FederationV3Error>(joined)
    })?;

    let mut results = Vec::new();
    let mut failures = Vec::new();
    for (peer_id, query_id, outcome) in outcomes {
        match outcome {
            Ok(result) => results.push(result),
            Err(error) => failures.push(FederatedPeerFailureV3 {
                peer_id,
                query_id,
                error,
            }),
        }
    }
    results.sort_by(|left, right| left.peer_id.cmp(&right.peer_id));
    failures.sort_by(|left, right| {
        left.peer_id
            .cmp(&right.peer_id)
            .then_with(|| left.query_id.cmp(&right.query_id))
    });

    let completed_peers = results
        .iter()
        .filter(|result| result.coverage.completed_peers == 1)
        .count();
    let indeterminate_peers = results.len().saturating_sub(completed_peers);
    let failed_peers = failures.len().saturating_add(indeterminate_peers);

    let mut items = results
        .iter()
        .flat_map(|result| result.items.iter().cloned())
        .collect::<Vec<_>>();
    items.sort_by(|left, right| {
        left.source_owner_id
            .cmp(&right.source_owner_id)
            .then_with(|| left.record_id.cmp(&right.record_id))
            .then_with(|| left.record_revision.cmp(&right.record_revision))
    });
    items.dedup_by(|left, right| {
        left.source_owner_id == right.source_owner_id
            && left.record_id == right.record_id
            && left.record_revision == right.record_revision
    });
    let before_truncate = items.len();
    items.truncate(MAX_FEDERATED_RESULTS_V3);
    let aggregate_truncated = before_truncate.saturating_sub(items.len());
    let child_truncated = results
        .iter()
        .map(|result| u64::from(result.coverage.truncated_items))
        .sum::<u64>();
    let truncated_items = child_truncated
        .saturating_add(u64::try_from(aggregate_truncated).unwrap_or(u64::MAX));

    let any_partial = results.iter().any(|result| {
        matches!(
            result.completeness,
            FederatedCompletenessV3::Partial | FederatedCompletenessV3::Indeterminate
        )
    });
    let all_completed_empty = !results.is_empty()
        && results
            .iter()
            .all(|result| matches!(result.completeness, FederatedCompletenessV3::Empty));
    let completeness = if failed_peers > 0 || any_partial || truncated_items > 0 {
        FederatedCompletenessV3::Partial
    } else if all_completed_empty {
        FederatedCompletenessV3::Empty
    } else {
        FederatedCompletenessV3::Complete
    };

    let expires_unix_ms = results
        .iter()
        .map(|result| result.expires_unix_ms)
        .min()
        .unwrap_or_else(|| clock.now_unix_ms().saturating_add(1));
    let coverage = FederatedCoverageV3 {
        requested_peers: u32::try_from(requested_peers).unwrap_or(u32::MAX),
        completed_peers: u32::try_from(completed_peers).unwrap_or(u32::MAX),
        failed_peers: u32::try_from(failed_peers).unwrap_or(u32::MAX),
        truncated_items: u32::try_from(truncated_items).unwrap_or(u32::MAX),
    };
    let orchestration_digest = compute_orchestration_digest(
        &results,
        &failures,
        &items,
        &coverage,
        completeness,
        expires_unix_ms,
    );
    Ok(FederatedOrchestrationV3 {
        results,
        failures,
        items,
        coverage,
        completeness,
        expires_unix_ms,
        orchestration_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn compute_orchestration_digest(
    results: &[FederatedResultV3],
    failures: &[FederatedPeerFailureV3],
    items: &[FederatedEvidenceItemV3],
    coverage: &FederatedCoverageV3,
    completeness: FederatedCompletenessV3,
    expires_unix_ms: u64,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(ORCHESTRATION_DOMAIN);
    push_len(&mut bytes, results.len());
    for result in results {
        push_digest(&mut bytes, result.result_digest);
    }
    push_len(&mut bytes, failures.len());
    for failure in failures {
        push_id(&mut bytes, &failure.peer_id);
        push_id(&mut bytes, &failure.query_id);
        let error = &failure.error;
        let error = format!("{error:?}");
        push_len(&mut bytes, error.len());
        bytes.extend_from_slice(error.as_bytes());
    }
    push_len(&mut bytes, items.len());
    for item in items {
        push_id(&mut bytes, &item.source_owner_id);
        push_id(&mut bytes, &item.record_id);
        push_u64(&mut bytes, item.record_revision.get());
        push_digest(&mut bytes, item.record_digest);
        push_digest(&mut bytes, item.support_digest);
        push_digest(&mut bytes, item.validity_digest);
    }
    push_u64(&mut bytes, u64::from(coverage.requested_peers));
    push_u64(&mut bytes, u64::from(coverage.completed_peers));
    push_u64(&mut bytes, u64::from(coverage.failed_peers));
    push_u64(&mut bytes, u64::from(coverage.truncated_items));
    bytes.push(match completeness {
        FederatedCompletenessV3::Complete => 0,
        FederatedCompletenessV3::Partial => 1,
        FederatedCompletenessV3::Empty => 2,
        FederatedCompletenessV3::Indeterminate => 3,
    });
    push_u64(&mut bytes, expires_unix_ms);
    Digest32::of_bytes(&bytes)
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
