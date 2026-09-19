use std::collections::VecDeque;
use std::sync::Mutex;

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

#[derive(Clone)]
struct FixtureTransport {
    result: Result<FederationTransportResultV2, FederationV2Error>,
    pending: bool,
}

impl FixtureTransport {
    fn immediate(result: FederationTransportResultV2) -> Self {
        Self {
            result: Ok(result),
            pending: false,
        }
    }

    fn pending() -> Self {
        Self {
            result: Err(FederationV2Error::TransportRejected),
            pending: true,
        }
    }
}

impl FederationTransportV2 for FixtureTransport {
    fn send_once<'a>(
        &'a self,
        _query: &'a FederatedQueryV2,
    ) -> FederationFutureV2<'a, Result<FederationTransportResultV2, FederationV2Error>> {
        if self.pending {
            Box::pin(std::future::pending())
        } else {
            let result = self.result.clone();
            Box::pin(async move { result })
        }
    }
}

struct FixtureAuthority {
    states: Mutex<VecDeque<FederationAuthorityStateV2>>,
}

impl FixtureAuthority {
    fn new(states: impl IntoIterator<Item = FederationAuthorityStateV2>) -> Self {
        Self {
            states: Mutex::new(states.into_iter().collect()),
        }
    }
}

impl FederationAuthorityV2 for FixtureAuthority {
    fn revalidate<'a>(
        &'a self,
        _query: &'a FederatedQueryV2,
        _lease: &'a FederatedLeaseV2,
        _now_unix_ms: u64,
    ) -> FederationFutureV2<'a, Result<FederationAuthorityStateV2, FederationV2Error>> {
        let state = self
            .states
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .pop_front()
            .unwrap_or(FederationAuthorityStateV2::Current);
        Box::pin(async move { Ok(state) })
    }
}


struct PendingAuthority;

impl FederationAuthorityV2 for PendingAuthority {
    fn revalidate<'a>(
        &'a self,
        _query: &'a FederatedQueryV2,
        _lease: &'a FederatedLeaseV2,
        _now_unix_ms: u64,
    ) -> FederationFutureV2<'a, Result<FederationAuthorityStateV2, FederationV2Error>> {
        Box::pin(std::future::pending())
    }
}

#[derive(Clone, Copy)]
struct FixedClock(u64);

impl FederationClockV2 for FixedClock {
    fn now_unix_ms(&self) -> u64 {
        self.0
    }
}

#[derive(Clone, Copy)]
struct CancelImmediately;

impl FederationCancellationV2 for CancelImmediately {
    fn cancelled<'a>(&'a self, _query_id: &'a StableId) -> FederationFutureV2<'a, ()> {
        Box::pin(async {})
    }
}

fn terminal_response(query: &FederatedQueryV2) -> RemoteFederatedResponseV2 {
    let mut response = RemoteFederatedResponseV2 {
        peer_id: query.peer_id.clone(),
        query_binding_digest: query.binding_digest(),
        scope_digest: query.scope_digest,
        purpose_digest: query.purpose_digest,
        generation_vector_digest: query.generation_vector_digest,
        response_digest: Digest32::ZERO,
        observed_frontier: 7,
        expires_unix_ms: 80,
        items: vec![item(1), item(2), item(3)],
        completeness: FederatedCompletenessV2::Complete,
        terminal_observed: true,
    };
    response.response_digest = response.compute_response_digest();
    response
}

#[tokio::test]
async fn one_attempt_returns_bounded_partial_result() {
    let query = query();
    let transport = FixtureTransport::immediate(FederationTransportResultV2::Terminal(
        terminal_response(&query),
    ));
    let authority = FixtureAuthority::new([
        FederationAuthorityStateV2::Current,
        FederationAuthorityStateV2::Current,
    ]);
    let result = execute_once(
        &transport,
        &authority,
        &NeverCancelledV2,
        &FixedClock(10),
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("valid result: {error}"));
    assert_eq!(result.items.len(), 2);
    assert_eq!(result.coverage.truncated_items, 1);
    assert_eq!(result.completeness, FederatedCompletenessV2::Partial);
    assert_eq!(result.validity, FederatedValidityV2::Valid);
    result
        .validate()
        .unwrap_or_else(|error| panic!("valid receipt: {error}"));
}

#[tokio::test]
async fn empty_scope_can_report_zero_frontier_without_fabrication() {
    let query = query();
    let mut response = terminal_response(&query);
    response.observed_frontier = 0;
    response.items.clear();
    response.completeness = FederatedCompletenessV2::Empty;
    response.response_digest = response.compute_response_digest();
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    let authority = FixtureAuthority::new([
        FederationAuthorityStateV2::Current,
        FederationAuthorityStateV2::Current,
    ]);
    let result = execute_once(
        &transport,
        &authority,
        &NeverCancelledV2,
        &FixedClock(10),
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("valid empty result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.observed_frontier, Some(0));
    assert_eq!(result.completeness, FederatedCompletenessV2::Empty);
    assert_eq!(result.validity, FederatedValidityV2::Valid);
    result.validate().expect("zero frontier result remains valid");
}

#[tokio::test]
async fn nonterminal_attempt_is_explicitly_indeterminate_without_retry() {
    let query = query();
    let transport = FixtureTransport::immediate(FederationTransportResultV2::NonTerminal(
        FederationTransportOutcomeV2::TimedOut,
    ));
    let authority = FixtureAuthority::new([FederationAuthorityStateV2::Current]);
    let result = execute_once(
        &transport,
        &authority,
        &NeverCancelledV2,
        &FixedClock(10),
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("indeterminate result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(
        result.completeness,
        FederatedCompletenessV2::Indeterminate
    );
    assert_eq!(result.validity, FederatedValidityV2::Indeterminate);
    assert_eq!(result.coverage.failed_peers, 1);
}

#[tokio::test]
async fn response_digest_detects_item_tampering() {
    let query = query();
    let mut response = terminal_response(&query);
    response.items[0].record_digest = digest("tampered-record");
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    let authority = FixtureAuthority::new([FederationAuthorityStateV2::Current]);
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &NeverCancelledV2,
            &FixedClock(10),
            query.clone(),
            &lease(&query),
        )
        .await,
        Err(FederationV2Error::DigestMismatch("response"))
    );
}

#[tokio::test]
async fn response_from_another_query_cannot_be_replayed() {
    let original = query();
    let response = terminal_response(&original);
    let mut replayed = original.clone();
    replayed.query_id = id("query:2");
    replayed.query_digest = digest("query-2");
    replayed.nonce_digest = digest("nonce-2");
    let replayed_lease = lease(&replayed);
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    let authority = FixtureAuthority::new([FederationAuthorityStateV2::Current]);
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &NeverCancelledV2,
            &FixedClock(10),
            replayed,
            &replayed_lease,
        )
        .await,
        Err(FederationV2Error::DigestMismatch(
            "response_query_binding"
        ))
    );
}

#[tokio::test]
async fn successful_result_expiry_is_bounded_by_query_and_lease() {
    let mut query = query();
    query.deadline_unix_ms = 500;
    let mut lease = lease(&query);
    lease.expires_unix_ms = 120;
    lease.query_binding_digest = query.binding_digest();
    let mut response = terminal_response(&query);
    response.expires_unix_ms = 900;
    response.response_digest = response.compute_response_digest();
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    let authority = FixtureAuthority::new([
        FederationAuthorityStateV2::Current,
        FederationAuthorityStateV2::Current,
    ]);
    let result = execute_once(
        &transport,
        &authority,
        &NeverCancelledV2,
        &FixedClock(10),
        query,
        &lease,
    )
    .await
    .unwrap_or_else(|error| panic!("valid result: {error}"));
    assert_eq!(result.expires_unix_ms, 120);
}

#[tokio::test]
async fn postflight_revocation_never_exposes_remote_items() {
    let query = query();
    let transport = FixtureTransport::immediate(FederationTransportResultV2::Terminal(
        terminal_response(&query),
    ));
    let authority = FixtureAuthority::new([
        FederationAuthorityStateV2::Current,
        FederationAuthorityStateV2::Revoked,
    ]);
    let result = execute_once(
        &transport,
        &authority,
        &NeverCancelledV2,
        &FixedClock(10),
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
async fn postflight_generation_drift_never_exposes_remote_items() {
    let query = query();
    let transport = FixtureTransport::immediate(FederationTransportResultV2::Terminal(
        terminal_response(&query),
    ));
    let authority = FixtureAuthority::new([
        FederationAuthorityStateV2::Current,
        FederationAuthorityStateV2::StaleGeneration,
    ]);
    let result = execute_once(
        &transport,
        &authority,
        &NeverCancelledV2,
        &FixedClock(10),
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("stale result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.validity, FederatedValidityV2::StaleGeneration);
}

#[tokio::test]
async fn stale_remote_generation_never_exposes_remote_items() {
    let query = query();
    let mut response = terminal_response(&query);
    response.generation_vector_digest = digest("stale-generation");
    response.response_digest = response.compute_response_digest();
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    let authority = FixtureAuthority::new([
        FederationAuthorityStateV2::Current,
        FederationAuthorityStateV2::Current,
    ]);
    let result = execute_once(
        &transport,
        &authority,
        &NeverCancelledV2,
        &FixedClock(10),
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("stale result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.validity, FederatedValidityV2::StaleGeneration);
}

#[tokio::test]
async fn peer_scope_and_lease_drift_fail_closed() {
    let query = query();
    let mut response = terminal_response(&query);
    response.peer_id = id("peer:other");
    response.response_digest = response.compute_response_digest();
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    let authority = FixtureAuthority::new([FederationAuthorityStateV2::Current]);
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &NeverCancelledV2,
            &FixedClock(10),
            query.clone(),
            &lease(&query),
        )
        .await,
        Err(FederationV2Error::IdentityMismatch("response_peer"))
    );

    let mut stale_lease = lease(&query);
    stale_lease.lease_epoch += 1;
    let transport = FixtureTransport::immediate(FederationTransportResultV2::NonTerminal(
        FederationTransportOutcomeV2::Unavailable,
    ));
    let authority = FixtureAuthority::new([FederationAuthorityStateV2::Current]);
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &NeverCancelledV2,
            &FixedClock(10),
            query,
            &stale_lease,
        )
        .await,
        Err(FederationV2Error::LeaseEpochMismatch)
    );
}

#[tokio::test]
async fn duplicate_remote_identity_is_rejected_even_with_fresh_digest() {
    let query = query();
    let mut response = terminal_response(&query);
    response.items = vec![item(1), item(1)];
    response.response_digest = response.compute_response_digest();
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    let authority = FixtureAuthority::new([FederationAuthorityStateV2::Current]);
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &NeverCancelledV2,
            &FixedClock(10),
            query.clone(),
            &lease(&query),
        )
        .await,
        Err(FederationV2Error::DuplicateResultIdentity)
    );
}

#[tokio::test]
async fn cancellation_interrupts_a_pending_transport_attempt() {
    let query = query();
    let authority = FixtureAuthority::new([FederationAuthorityStateV2::Current]);
    let result = execute_once(
        &FixtureTransport::pending(),
        &authority,
        &CancelImmediately,
        &FixedClock(10),
        query.clone(),
        &lease(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("cancelled result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.validity, FederatedValidityV2::Indeterminate);
}

#[tokio::test(start_paused = true)]
async fn engine_deadline_bounds_a_pending_authority_lookup() {
    let query = query();
    assert_eq!(
        execute_once(
            &FixtureTransport::pending(),
            &PendingAuthority,
            &NeverCancelledV2,
            &FixedClock(10),
            query.clone(),
            &lease(&query),
        )
        .await,
        Err(FederationV2Error::DeadlineExpired)
    );
}

#[tokio::test(start_paused = true)]
async fn engine_deadline_interrupts_a_pending_transport_attempt() {
    let mut query = query();
    query.deadline_unix_ms = 11;
    let mut lease = lease(&query);
    lease.expires_unix_ms = 90;
    lease.query_binding_digest = query.binding_digest();
    let authority = FixtureAuthority::new([FederationAuthorityStateV2::Current]);
    let result = execute_once(
        &FixtureTransport::pending(),
        &authority,
        &NeverCancelledV2,
        &FixedClock(10),
        query,
        &lease,
    )
    .await
    .unwrap_or_else(|error| panic!("timed out result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.validity, FederatedValidityV2::Indeterminate);
}

#[test]
fn response_digest_is_canonical_over_item_order() {
    let query = query();
    let response = terminal_response(&query);
    let mut reordered = response.clone();
    reordered.items.reverse();
    reordered.response_digest = reordered.compute_response_digest();
    assert_eq!(response.response_digest, reordered.response_digest);
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
