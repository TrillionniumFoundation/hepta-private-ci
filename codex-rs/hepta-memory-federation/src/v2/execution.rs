use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_types::{AuthorityPosture, Digest32, Revision, StableId};
use tokio::sync::Semaphore;
use tokio::task::JoinSet;
use tokio_util::sync::CancellationToken;

use super::authority::{
    FederationAuthorityV2, FederationClockV2, FederationPeerDirectoryV2, ensure_same_capability,
};
use super::model::{
    FederatedBatchResultV2, FederatedCompletenessV2, FederatedCoverageV2,
    FederatedEvidenceItemV2, FederatedResultV2, FederatedValidityV2, FederationAttemptV2,
    FederationPeerFailureV2, FederationV2Error, MAX_FEDERATED_PEERS_V2,
    MAX_FEDERATED_RESULTS_V2, MAX_FEDERATION_CONCURRENCY_V2, evidence_identity,
    normalize_completeness,
};
use super::transport::{
    FederationTransportOutcomeV2, FederationTransportResultV2, FederationTransportV2,
};

pub async fn execute_once<T, A, P, C>(
    transport: &T,
    authority: &A,
    peers: &P,
    clock: &C,
    cancellation: &CancellationToken,
    query: super::model::FederatedQueryV2,
    lease: &super::model::FederatedLeaseV2,
) -> Result<FederatedResultV2, FederationV2Error>
where
    T: FederationTransportV2 + ?Sized,
    A: FederationAuthorityV2 + ?Sized,
    P: FederationPeerDirectoryV2 + ?Sized,
    C: FederationClockV2 + ?Sized,
{
    if cancellation.is_cancelled() {
        return Err(FederationV2Error::Cancelled);
    }
    let pre_send_now = clock.now_unix_ms()?;
    query.validate(pre_send_now)?;
    lease.validate_claims_for_query(pre_send_now, &query)?;
    let capability = authority.verify_for_query(pre_send_now, &query, lease).await?;
    capability.validate_for_query(pre_send_now, &query, lease)?;
    let peer = peers.resolve_peer(&query.peer_id)?;
    let hard_deadline = query
        .deadline_unix_ms
        .min(lease.expires_unix_ms)
        .min(capability.expires_unix_ms);
    let timeout_ms = hard_deadline
        .checked_sub(pre_send_now)
        .filter(|value| *value > 0)
        .ok_or(FederationV2Error::DeadlineExpired)?;

    let child_cancel = cancellation.child_token();
    let send_future = transport.send_once(&query, &capability, child_cancel.clone());
    let transport_result = tokio::select! {
        _ = cancellation.cancelled() => {
            child_cancel.cancel();
            return Err(FederationV2Error::Cancelled);
        }
        timed = tokio::time::timeout(Duration::from_millis(timeout_ms), send_future) => {
            match timed {
                Ok(result) => result?,
                Err(_) => {
                    child_cancel.cancel();
                    FederationTransportResultV2::NonTerminal(FederationTransportOutcomeV2::TimedOut)
                }
            }
        }
    };

    let post_send_now = clock.now_unix_ms()?;
    query.validate(post_send_now)?;
    lease.validate_claims_for_query(post_send_now, &query)?;
    if cancellation.is_cancelled() {
        child_cancel.cancel();
        return Err(FederationV2Error::Cancelled);
    }
    let refreshed = authority
        .revalidate(post_send_now, &query, lease, &capability)
        .await?;
    refreshed.validate_for_query(post_send_now, &query, lease)?;
    ensure_same_capability(&capability, &refreshed)?;
    if refreshed.revocation_epoch < capability.revocation_epoch {
        return Err(FederationV2Error::RevocationEpochRegressed);
    }

    let query_binding_digest = query.binding_digest();
    let capability_receipt_digest = refreshed.binding_digest();
    let mut result = match transport_result {
        FederationTransportResultV2::NonTerminal(_) => FederatedResultV2 {
            query_id: query.query_id.clone(),
            peer_id: query.peer_id.clone(),
            grant_id: query.grant_id.clone(),
            lease_id: lease.lease_id.clone(),
            query_binding_digest,
            capability_receipt_digest,
            generation_vector_digest: query.generation_vector_digest,
            observed_frontier: None,
            expires_unix_ms: hard_deadline.min(refreshed.expires_unix_ms),
            items: Vec::new(),
            coverage: FederatedCoverageV2 {
                requested_peers: 1,
                completed_peers: 0,
                failed_peers: 1,
                truncated_items: 0,
            },
            completeness: FederatedCompletenessV2::Indeterminate,
            validity: FederatedValidityV2::Indeterminate,
            remote_response_digest: None,
            response_nonce_digest: None,
            result_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        },
        FederationTransportResultV2::Terminal(response) => {
            response.verify_for_request(&query, lease, &refreshed, &peer)?;
            if post_send_now >= response.expires_unix_ms {
                return Err(FederationV2Error::ResponseExpired);
            }
            let stale_generation = response.generation_vector_digest != query.generation_vector_digest;
            let maximum = usize::try_from(query.maximum_results).unwrap_or(MAX_FEDERATED_RESULTS_V2);
            let remote_count = response.items.len();
            let remote_completeness = response.completeness;
            let remote_digest = response.response_digest;
            let response_nonce = response.response_nonce_digest;
            let observed_frontier = response.observed_frontier;
            let response_expiry = response.expires_unix_ms;
            let mut items = if stale_generation { Vec::new() } else { response.items };
            items.truncate(maximum);
            let truncated = remote_count.saturating_sub(items.len());
            let completeness = normalize_completeness(
                stale_generation,
                remote_completeness,
                items.is_empty(),
                truncated,
            );
            FederatedResultV2 {
                query_id: query.query_id.clone(),
                peer_id: query.peer_id.clone(),
                grant_id: query.grant_id.clone(),
                lease_id: lease.lease_id.clone(),
                query_binding_digest,
                capability_receipt_digest,
                generation_vector_digest: query.generation_vector_digest,
                observed_frontier: Some(observed_frontier),
                expires_unix_ms: response_expiry
                    .min(query.deadline_unix_ms)
                    .min(lease.expires_unix_ms)
                    .min(refreshed.expires_unix_ms),
                items,
                coverage: FederatedCoverageV2 {
                    requested_peers: 1,
                    completed_peers: 1,
                    failed_peers: 0,
                    truncated_items: u32::try_from(truncated).unwrap_or(u32::MAX),
                },
                completeness,
                validity: if stale_generation {
                    FederatedValidityV2::StaleGeneration
                } else {
                    FederatedValidityV2::Valid
                },
                remote_response_digest: Some(remote_digest),
                response_nonce_digest: Some(response_nonce),
                result_digest: Digest32::ZERO,
                authority: AuthorityPosture::DENY_ALL,
            }
        }
    };
    if post_send_now >= result.expires_unix_ms {
        return Err(FederationV2Error::ResultExpired);
    }
    result.result_digest = result.compute_result_digest();
    result.validate()?;
    Ok(result)
}

pub async fn execute_federated<T, A, P, C>(
    transport: Arc<T>,
    authority: Arc<A>,
    peers: Arc<P>,
    clock: Arc<C>,
    cancellation: CancellationToken,
    attempts: Vec<FederationAttemptV2>,
    concurrency_limit: usize,
) -> Result<FederatedBatchResultV2, FederationV2Error>
where
    T: FederationTransportV2 + 'static,
    A: FederationAuthorityV2 + 'static,
    P: FederationPeerDirectoryV2 + 'static,
    C: FederationClockV2 + 'static,
{
    if attempts.is_empty() || attempts.len() > MAX_FEDERATED_PEERS_V2 {
        return Err(FederationV2Error::InvalidPeerCount);
    }
    if concurrency_limit == 0 || concurrency_limit > MAX_FEDERATION_CONCURRENCY_V2 {
        return Err(FederationV2Error::InvalidConcurrencyLimit);
    }
    let mut unique_peers = BTreeSet::new();
    for attempt in &attempts {
        if !unique_peers.insert(attempt.query.peer_id.clone()) {
            return Err(FederationV2Error::DuplicatePeerIdentity);
        }
    }

    let requested = u32::try_from(attempts.len()).map_err(|_| FederationV2Error::InvalidPeerCount)?;
    let semaphore = Arc::new(Semaphore::new(concurrency_limit));
    let mut tasks = JoinSet::new();
    for attempt in attempts {
        let transport = Arc::clone(&transport);
        let authority = Arc::clone(&authority);
        let peers = Arc::clone(&peers);
        let clock = Arc::clone(&clock);
        let semaphore = Arc::clone(&semaphore);
        let child_cancel = cancellation.child_token();
        tasks.spawn(async move {
            let peer_id = attempt.query.peer_id.clone();
            let query_id = attempt.query.query_id.clone();
            let permit = semaphore
                .acquire_owned()
                .await
                .map_err(|_| FederationV2Error::Cancelled)?;
            let result = execute_once(
                transport.as_ref(),
                authority.as_ref(),
                peers.as_ref(),
                clock.as_ref(),
                &child_cancel,
                attempt.query,
                &attempt.lease,
            )
            .await;
            drop(permit);
            Ok::<_, FederationV2Error>((peer_id, query_id, result))
        });
    }

    let mut results = Vec::new();
    let mut failures = Vec::new();
    while let Some(joined) = tasks.join_next().await {
        match joined {
            Ok(Ok((_peer_id, _query_id, Ok(result)))) => results.push(result),
            Ok(Ok((peer_id, query_id, Err(error)))) => failures.push(FederationPeerFailureV2 {
                peer_id,
                query_id,
                error,
            }),
            Ok(Err(error)) => return Err(error),
            Err(_) => return Err(FederationV2Error::TransportRejected),
        }
    }
    results.sort_by(|a, b| a.peer_id.cmp(&b.peer_id).then_with(|| a.query_id.cmp(&b.query_id)));
    failures.sort_by(|a, b| a.peer_id.cmp(&b.peer_id).then_with(|| a.query_id.cmp(&b.query_id)));

    aggregate(requested, results, failures)
}

fn aggregate(
    requested: u32,
    results: Vec<FederatedResultV2>,
    failures: Vec<FederationPeerFailureV2>,
) -> Result<FederatedBatchResultV2, FederationV2Error> {
    let mut merged = BTreeMap::<(StableId, StableId, Revision), FederatedEvidenceItemV2>::new();
    let mut truncated = 0u64;
    let mut completed = 0u64;
    let mut failed = u64::try_from(failures.len()).unwrap_or(u64::MAX);
    let mut partial = !failures.is_empty();
    let mut usable_terminal = false;
    let mut all_empty = !results.is_empty();

    for result in &results {
        truncated = truncated.saturating_add(u64::from(result.coverage.truncated_items));
        completed = completed.saturating_add(u64::from(result.coverage.completed_peers));
        failed = failed.saturating_add(u64::from(result.coverage.failed_peers));
        if result.coverage.completed_peers > 0 && matches!(result.validity, FederatedValidityV2::Valid) {
            usable_terminal = true;
        }
        if !matches!(result.completeness, FederatedCompletenessV2::Empty) {
            all_empty = false;
        }
        if matches!(result.completeness, FederatedCompletenessV2::Partial | FederatedCompletenessV2::Indeterminate)
            || !matches!(result.validity, FederatedValidityV2::Valid)
        {
            partial = true;
        }
        for item in &result.items {
            let identity = evidence_identity(item);
            if let Some(existing) = merged.get(&identity) {
                if existing != item {
                    return Err(FederationV2Error::ConflictingResultIdentity);
                }
            } else {
                merged.insert(identity, item.clone());
            }
        }
    }

    let mut items = merged.into_values().collect::<Vec<_>>();
    if items.len() > MAX_FEDERATED_RESULTS_V2 {
        let excess = items.len() - MAX_FEDERATED_RESULTS_V2;
        items.truncate(MAX_FEDERATED_RESULTS_V2);
        truncated = truncated.saturating_add(u64::try_from(excess).unwrap_or(u64::MAX));
        partial = true;
    }
    let completeness = if !usable_terminal {
        FederatedCompletenessV2::Indeterminate
    } else if partial || failed > 0 || truncated > 0 {
        FederatedCompletenessV2::Partial
    } else if all_empty {
        FederatedCompletenessV2::Empty
    } else {
        FederatedCompletenessV2::Complete
    };
    let mut batch = FederatedBatchResultV2 {
        results,
        failures,
        items,
        coverage: FederatedCoverageV2 {
            requested_peers: requested,
            completed_peers: u32::try_from(completed).unwrap_or(u32::MAX),
            failed_peers: u32::try_from(failed).unwrap_or(u32::MAX),
            truncated_items: u32::try_from(truncated).unwrap_or(u32::MAX),
        },
        completeness,
        result_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    batch.result_digest = batch.compute_result_digest();
    batch.validate()?;
    Ok(batch)
}
