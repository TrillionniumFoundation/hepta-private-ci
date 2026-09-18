use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn query() -> FederatedQueryV2 {
    FederatedQueryV2 {
        query_id: id("query:1"),
        peer_id: id("peer:1"),
        principal_id: id("principal:1"),
        scope_digest: digest("scope"),
        purpose_digest: digest("purpose"),
        generation_vector_digest: digest("generation-vector"),
        query_digest: digest("query"),
        maximum_results: 2,
        deadline_unix_ms: 100,
        lease_epoch: 3,
        nonce_digest: digest("nonce"),
    }
}

fn lease(query: &FederatedQueryV2) -> FederatedLeaseV2 {
    FederatedLeaseV2 {
        lease_id: id("lease:1"),
        query_id: query.query_id.clone(),
        peer_id: query.peer_id.clone(),
        principal_id: query.principal_id.clone(),
        scope_digest: query.scope_digest,
        purpose_digest: query.purpose_digest,
        generation_vector_digest: query.generation_vector_digest,
        query_binding_digest: query.binding_digest(),
        lease_epoch: query.lease_epoch,
        expires_unix_ms: 90,
        revoked: false,
    }
}

fn item(number: u64) -> FederatedEvidenceItemV2 {
    FederatedEvidenceItemV2 {
        source_owner_id: id("owner:1"),
        record_id: id(&format!("record:{number}")),
        record_revision: revision(number),
        record_digest: digest(&format!("record-{number}")),
        support_digest: digest(&format!("support-{number}")),
        validity_digest: digest(&format!("validity-{number}")),
    }
}

fn terminal_response(query: &FederatedQueryV2) -> RemoteFederatedResponseV2 {
    RemoteFederatedResponseV2 {
        peer_id: query.peer_id.clone(),
        scope_digest: query.scope_digest,
        purpose_digest: query.purpose_digest,
        generation_vector_digest: query.generation_vector_digest,
        response_digest: Digest32::ZERO,
        observed_frontier: 7,
        expires_unix_ms: 80,
        items: vec![item(1), item(2), item(3)],
        completeness: FederatedCompletenessV2::Complete,
        terminal_observed: true,
    }
    .seal(query.binding_digest())
    .unwrap_or_else(|error| panic!("valid sealed response: {error}"))
}

fn authority_observation(
    query: &FederatedQueryV2,
    observed_at_unix_ms: u64,
) -> FederationAuthorityObservationV2 {
    FederationAuthorityObservationV2 {
        peer_id: query.peer_id.clone(),
        principal_id: query.principal_id.clone(),
        query_binding_digest: query.binding_digest(),
        generation_vector_digest: query.generation_vector_digest,
        lease_epoch: query.lease_epoch,
        expires_unix_ms: 90,
        observed_at_unix_ms,
        peer_enrolled: true,
        revoked: false,
    }
}

struct FixtureAuthority {
    observations: Mutex<VecDeque<FederationAuthorityObservationV2>>,
}

impl FixtureAuthority {
    fn new(observations: impl IntoIterator<Item = FederationAuthorityObservationV2>) -> Self {
        Self {
            observations: Mutex::new(observations.into_iter().collect()),
        }
    }
}

impl FederationAuthorityV2 for FixtureAuthority {
    fn observe<'a>(
        &'a self,
        _query: &'a FederatedQueryV2,
        _lease: &'a FederatedLeaseV2,
    ) -> FederationAuthorityFutureV2<'a> {
        Box::pin(async move {
            self.observations
                .lock()
                .map_err(|_| FederationV2Error::TransportRejected)?
                .pop_front()
                .ok_or(FederationV2Error::TransportRejected)
        })
    }
}

#[derive(Clone)]
struct FixtureTransport {
    result: Result<FederationTransportResultV2, FederationV2Error>,
}

impl FederationTransportV2 for FixtureTransport {
    fn send_once<'a>(
        &'a self,
        _query: &'a FederatedQueryV2,
    ) -> FederationTransportFutureV2<'a> {
        Box::pin(async move { self.result.clone() })
    }
}

#[derive(Clone)]
struct SlowTransport {
    result: FederationTransportResultV2,
    delay: Duration,
    completed: Arc<AtomicBool>,
}

impl FederationTransportV2 for SlowTransport {
    fn send_once<'a>(
        &'a self,
        _query: &'a FederatedQueryV2,
    ) -> FederationTransportFutureV2<'a> {
        Box::pin(async move {
            tokio::time::sleep(self.delay).await;
            self.completed.store(true, Ordering::SeqCst);
            Ok(self.result.clone())
        })
    }
}

struct ImmediateCancellation;

impl FederationCancellationV2 for ImmediateCancellation {
    fn cancelled<'a>(
        &'a self,
        _query: &'a FederatedQueryV2,
    ) -> FederationCancellationFutureV2<'a> {
        Box::pin(async {})
    }
}

struct DelayedCancellation {
    delay: Duration,
}

impl FederationCancellationV2 for DelayedCancellation {
    fn cancelled<'a>(
        &'a self,
        _query: &'a FederatedQueryV2,
    ) -> FederationCancellationFutureV2<'a> {
        Box::pin(async move {
            tokio::time::sleep(self.delay).await;
        })
    }
}

struct SlowAuthority {
    observation: FederationAuthorityObservationV2,
    delay: Duration,
    completed: Arc<AtomicBool>,
}

impl FederationAuthorityV2 for SlowAuthority {
    fn observe<'a>(
        &'a self,
        _query: &'a FederatedQueryV2,
        _lease: &'a FederatedLeaseV2,
    ) -> FederationAuthorityFutureV2<'a> {
        Box::pin(async move {
            tokio::time::sleep(self.delay).await;
            self.completed.store(true, Ordering::SeqCst);
            Ok(self.observation.clone())
        })
    }
}

fn current_authority(query: &FederatedQueryV2) -> FixtureAuthority {
    FixtureAuthority::new([
        authority_observation(query, 10),
        authority_observation(query, 11),
    ])
}

#[tokio::test]
async fn one_attempt_returns_bounded_partial_result() {
    let query = query();
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(terminal_response(
            &query,
        ))),
    };
    let result = execute_once(
        &transport,
        &current_authority(&query),
        &NeverCancelledV2,
        10,
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("valid result: {error}"));
    assert_eq!(result.items.len(), 2);
    assert_eq!(result.coverage.truncated_items, 1);
    assert_eq!(result.completeness, FederatedCompletenessV2::Partial);
    assert_eq!(result.validity, FederatedValidityV2::Valid);
    assert_eq!(result.expires_unix_ms, 80);
    result
        .validate()
        .unwrap_or_else(|error| panic!("valid receipt: {error}"));
}

#[tokio::test]
async fn terminal_receipt_cannot_drop_remote_provenance() {
    let query = query();
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(terminal_response(
            &query,
        ))),
    };
    let mut result = execute_once(
        &transport,
        &current_authority(&query),
        &NeverCancelledV2,
        10,
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("valid result: {error}"));
    result.remote_response_digest = None;
    result.result_digest = result.compute_result_digest();
    assert_eq!(
        result.validate(),
        Err(FederationV2Error::InvalidCompleteness)
    );
}

#[tokio::test]
async fn nonterminal_attempt_is_explicitly_indeterminate_without_retry() {
    let query = query();
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::NonTerminal(
            FederationTransportOutcomeV2::Unavailable,
        )),
    };
    let result = execute_once(
        &transport,
        &current_authority(&query),
        &NeverCancelledV2,
        10,
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("indeterminate result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.completeness, FederatedCompletenessV2::Indeterminate);
    assert_eq!(result.validity, FederatedValidityV2::Indeterminate);
    assert_eq!(result.coverage.failed_peers, 1);
}


#[tokio::test]
async fn genuine_empty_zero_frontier_response_is_valid() {
    let query = query();
    let response = RemoteFederatedResponseV2 {
        peer_id: query.peer_id.clone(),
        scope_digest: query.scope_digest,
        purpose_digest: query.purpose_digest,
        generation_vector_digest: query.generation_vector_digest,
        response_digest: Digest32::ZERO,
        observed_frontier: 0,
        expires_unix_ms: 80,
        items: Vec::new(),
        completeness: FederatedCompletenessV2::Empty,
        terminal_observed: true,
    }
    .seal(query.binding_digest())
    .unwrap_or_else(|error| panic!("valid empty response: {error}"));
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(response)),
    };
    let result = execute_once(
        &transport,
        &current_authority(&query),
        &NeverCancelledV2,
        10,
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("valid empty result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.observed_frontier, Some(0));
    assert_eq!(result.completeness, FederatedCompletenessV2::Empty);
    assert_eq!(result.validity, FederatedValidityV2::Valid);
}

#[tokio::test]
async fn sealed_response_detects_payload_tampering() {
    let query = query();
    let mut response = terminal_response(&query);
    response.items[0].record_digest = digest("tampered-record");
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(response)),
    };
    assert_eq!(
        execute_once(
            &transport,
            &current_authority(&query),
            &NeverCancelledV2,
            10,
            query.clone(),
            &lease(&query),
        )
        .await,
        Err(FederationV2Error::DigestMismatch("response"))
    );
}

#[tokio::test]
async fn sealed_response_cannot_be_replayed_across_query_bindings() {
    let original = query();
    let response = terminal_response(&original);
    let mut replay = query();
    replay.query_id = id("query:replay");
    replay.nonce_digest = digest("nonce-replay");
    let replay_lease = lease(&replay);
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(response)),
    };
    assert_eq!(
        execute_once(
            &transport,
            &current_authority(&replay),
            &NeverCancelledV2,
            10,
            replay.clone(),
            &replay_lease,
        )
        .await,
        Err(FederationV2Error::DigestMismatch("response"))
    );
}

#[test]
fn response_digest_is_canonical_over_item_order() {
    let query = query();
    let response = terminal_response(&query);
    let mut permuted = response.clone();
    permuted.items.reverse();
    permuted.response_digest = Digest32::ZERO;
    let permuted = permuted
        .seal(query.binding_digest())
        .unwrap_or_else(|error| panic!("valid permuted response: {error}"));
    assert_eq!(response.response_digest, permuted.response_digest);
}

#[tokio::test]
async fn overlimit_item_permutations_yield_identical_admitted_result() {
    let query = query();
    let response = terminal_response(&query);
    let mut permuted = response.clone();
    permuted.items.reverse();
    permuted.response_digest = permuted.compute_response_digest(query.binding_digest());

    let left = execute_once(
        &FixtureTransport {
            result: Ok(FederationTransportResultV2::Terminal(response)),
        },
        &current_authority(&query),
        &NeverCancelledV2,
        10,
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("left result: {error}"));
    let right = execute_once(
        &FixtureTransport {
            result: Ok(FederationTransportResultV2::Terminal(permuted)),
        },
        &current_authority(&query),
        &NeverCancelledV2,
        10,
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("right result: {error}"));

    assert_eq!(left.items, right.items);
    assert_eq!(left.result_digest, right.result_digest);
    assert_eq!(left.coverage.truncated_items, 1);
    assert_eq!(right.coverage.truncated_items, 1);
}

#[tokio::test]
async fn response_expiry_is_capped_by_authority_and_lease() {
    let query = query();
    let mut response = terminal_response(&query);
    response.expires_unix_ms = 500;
    response.response_digest = response.compute_response_digest(query.binding_digest());
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(response)),
    };
    let result = execute_once(
        &transport,
        &current_authority(&query),
        &NeverCancelledV2,
        10,
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("valid capped result: {error}"));
    assert_eq!(result.expires_unix_ms, 90);
}

#[tokio::test]
async fn authentic_stale_generation_never_exposes_remote_items() {
    let query = query();
    let mut response = terminal_response(&query);
    response.generation_vector_digest = digest("stale-generation");
    response.response_digest = response.compute_response_digest(query.binding_digest());
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(response)),
    };
    let result = execute_once(
        &transport,
        &current_authority(&query),
        &NeverCancelledV2,
        10,
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("stale result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.validity, FederatedValidityV2::StaleGeneration);
}

#[tokio::test]
async fn post_transport_revocation_strips_remote_items() {
    let query = query();
    let mut revoked = authority_observation(&query, 11);
    revoked.revoked = true;
    let authority = FixtureAuthority::new([authority_observation(&query, 10), revoked]);
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(terminal_response(
            &query,
        ))),
    };
    let result = execute_once(
        &transport,
        &authority,
        &NeverCancelledV2,
        10,
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("revoked result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.validity, FederatedValidityV2::Revoked);
    assert_eq!(result.completeness, FederatedCompletenessV2::Partial);
}

#[tokio::test]
async fn post_transport_authority_generation_drift_strips_remote_items() {
    let query = query();
    let mut drifted = authority_observation(&query, 11);
    drifted.generation_vector_digest = digest("new-authority-generation");
    let authority = FixtureAuthority::new([authority_observation(&query, 10), drifted]);
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(terminal_response(
            &query,
        ))),
    };
    let result = execute_once(
        &transport,
        &authority,
        &NeverCancelledV2,
        10,
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("drift result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.validity, FederatedValidityV2::StaleGeneration);
}

#[tokio::test]
async fn pre_transport_revocation_fails_before_dispatch() {
    let query = query();
    let mut revoked = authority_observation(&query, 10);
    revoked.revoked = true;
    let authority = FixtureAuthority::new([revoked]);
    let completed = Arc::new(AtomicBool::new(false));
    let transport = SlowTransport {
        result: FederationTransportResultV2::Terminal(terminal_response(&query)),
        delay: Duration::from_millis(1),
        completed: Arc::clone(&completed),
    };
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &NeverCancelledV2,
            10,
            query.clone(),
            &lease(&query),
        )
        .await,
        Err(FederationV2Error::AuthorityRevoked)
    );
    assert!(!completed.load(Ordering::SeqCst));
}

#[tokio::test]
async fn engine_deadline_drops_slow_transport_future() {
    let mut query = query();
    query.deadline_unix_ms = 15;
    let lease = lease(&query);
    let authority = FixtureAuthority::new([
        authority_observation(&query, 10),
        authority_observation(&query, 11),
    ]);
    let completed = Arc::new(AtomicBool::new(false));
    let transport = SlowTransport {
        result: FederationTransportResultV2::Terminal(terminal_response(&query)),
        delay: Duration::from_millis(50),
        completed: Arc::clone(&completed),
    };
    let result = execute_once(
        &transport,
        &authority,
        &NeverCancelledV2,
        10,
        query,
        &lease,
    )
    .await
    .unwrap_or_else(|error| panic!("timeout result: {error}"));
    assert_eq!(result.validity, FederatedValidityV2::Indeterminate);
    assert!(result.items.is_empty());
    assert!(!completed.load(Ordering::SeqCst));
}

#[tokio::test]
async fn cancellation_drops_inflight_transport_future() {
    let query = query();
    let completed = Arc::new(AtomicBool::new(false));
    let transport = SlowTransport {
        result: FederationTransportResultV2::Terminal(terminal_response(&query)),
        delay: Duration::from_millis(50),
        completed: Arc::clone(&completed),
    };
    let result = execute_once(
        &transport,
        &current_authority(&query),
        &DelayedCancellation {
            delay: Duration::from_millis(5),
        },
        10,
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("cancelled result: {error}"));
    assert_eq!(result.validity, FederatedValidityV2::Indeterminate);
    assert!(result.items.is_empty());
    assert!(!completed.load(Ordering::SeqCst));
}

#[tokio::test]
async fn pre_dispatch_cancellation_blocks_authority_and_transport() {
    let query = query();
    let authority_completed = Arc::new(AtomicBool::new(false));
    let authority = SlowAuthority {
        observation: authority_observation(&query, 10),
        delay: Duration::from_millis(50),
        completed: Arc::clone(&authority_completed),
    };
    let transport_completed = Arc::new(AtomicBool::new(false));
    let transport = SlowTransport {
        result: FederationTransportResultV2::Terminal(terminal_response(&query)),
        delay: Duration::from_millis(1),
        completed: Arc::clone(&transport_completed),
    };
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &ImmediateCancellation,
            10,
            query.clone(),
            &lease(&query),
        )
        .await,
        Err(FederationV2Error::OperationCancelled)
    );
    assert!(!authority_completed.load(Ordering::SeqCst));
    assert!(!transport_completed.load(Ordering::SeqCst));
}

#[tokio::test]
async fn authority_observation_is_bounded_by_query_deadline() {
    let mut query = query();
    query.deadline_unix_ms = 15;
    let lease = lease(&query);
    let authority_completed = Arc::new(AtomicBool::new(false));
    let authority = SlowAuthority {
        observation: authority_observation(&query, 11),
        delay: Duration::from_millis(50),
        completed: Arc::clone(&authority_completed),
    };
    let transport_completed = Arc::new(AtomicBool::new(false));
    let transport = SlowTransport {
        result: FederationTransportResultV2::Terminal(terminal_response(&query)),
        delay: Duration::from_millis(1),
        completed: Arc::clone(&transport_completed),
    };
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &NeverCancelledV2,
            10,
            query,
            &lease,
        )
        .await,
        Err(FederationV2Error::AuthorityUnavailable)
    );
    assert!(!authority_completed.load(Ordering::SeqCst));
    assert!(!transport_completed.load(Ordering::SeqCst));
}

#[tokio::test]
async fn peer_scope_and_lease_drift_fail_closed() {
    let query = query();
    let mut response = terminal_response(&query);
    response.peer_id = id("peer:other");
    response.response_digest = response.compute_response_digest(query.binding_digest());
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(response)),
    };
    assert_eq!(
        execute_once(
            &transport,
            &current_authority(&query),
            &NeverCancelledV2,
            10,
            query.clone(),
            &lease(&query),
        )
        .await,
        Err(FederationV2Error::IdentityMismatch("response_peer"))
    );

    let mut stale_lease = lease(&query);
    stale_lease.lease_epoch += 1;
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::NonTerminal(
            FederationTransportOutcomeV2::Unavailable,
        )),
    };
    assert_eq!(
        execute_once(
            &transport,
            &current_authority(&query),
            &NeverCancelledV2,
            10,
            query,
            &stale_lease,
        )
        .await,
        Err(FederationV2Error::LeaseEpochMismatch)
    );
}

#[tokio::test]
async fn duplicate_remote_identity_is_rejected_even_with_resealed_response() {
    let query = query();
    let mut response = terminal_response(&query);
    response.items = vec![item(1), item(1)];
    response.response_digest = response.compute_response_digest(query.binding_digest());
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(response)),
    };
    assert_eq!(
        execute_once(
            &transport,
            &current_authority(&query),
            &NeverCancelledV2,
            10,
            query.clone(),
            &lease(&query),
        )
        .await,
        Err(FederationV2Error::DuplicateResultIdentity)
    );
}

#[test]
fn cancellation_receipt_carries_no_success_assumption() {
    let receipt = observe_cancellation(
        FederationCancellationRequestV2 {
            cancellation_id: id("cancel:1"),
            query_id: id("query:1"),
            peer_id: id("peer:1"),
            query_binding_digest: digest("query-binding"),
            lease_epoch: 3,
            cancellation_nonce_digest: digest("cancel-nonce"),
        },
        false,
    )
    .unwrap_or_else(|error| panic!("valid cancellation receipt: {error}"));
    assert!(!receipt.terminal_observed);
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert!(!receipt.receipt_digest.is_zero());
}
