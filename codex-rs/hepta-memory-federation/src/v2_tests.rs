use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
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

fn authority_observation(
    query: &FederatedQueryV2,
    lease: &FederatedLeaseV2,
) -> FederationAuthorityObservationV2 {
    FederationAuthorityObservationV2 {
        lease_id: lease.lease_id.clone(),
        query_binding_digest: query.binding_digest(),
        generation_vector_digest: query.generation_vector_digest,
        lease_epoch: query.lease_epoch,
        expires_unix_ms: lease.expires_unix_ms,
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
    delay_ms: u64,
}

impl FixtureTransport {
    fn immediate(result: FederationTransportResultV2) -> Self {
        Self {
            result: Ok(result),
            delay_ms: 0,
        }
    }
}

impl FederationTransportV2 for FixtureTransport {
    fn send_once<'a>(
        &'a self,
        _query: &'a FederatedQueryV2,
    ) -> FederationV2Future<'a, Result<FederationTransportResultV2, FederationV2Error>> {
        let result = self.result.clone();
        let delay_ms = self.delay_ms;
        Box::pin(async move {
            if delay_ms > 0 {
                tokio::time::sleep(Duration::from_millis(delay_ms)).await;
            }
            result
        })
    }
}

#[derive(Clone)]
struct FixtureAuthority {
    observations: Arc<Vec<FederationAuthorityObservationV2>>,
    calls: Arc<AtomicUsize>,
}

impl FixtureAuthority {
    fn stable(query: &FederatedQueryV2, lease: &FederatedLeaseV2) -> Self {
        let observation = authority_observation(query, lease);
        Self {
            observations: Arc::new(vec![observation.clone(), observation]),
            calls: Arc::new(AtomicUsize::new(0)),
        }
    }

    fn sequence(observations: Vec<FederationAuthorityObservationV2>) -> Self {
        assert!(!observations.is_empty());
        Self {
            observations: Arc::new(observations),
            calls: Arc::new(AtomicUsize::new(0)),
        }
    }
}

impl FederationAuthorityV2 for FixtureAuthority {
    fn observe<'a>(
        &'a self,
        _query: &'a FederatedQueryV2,
        _lease: &'a FederatedLeaseV2,
    ) -> FederationV2Future<'a, Result<FederationAuthorityObservationV2, FederationV2Error>> {
        let index = self.calls.fetch_add(1, Ordering::SeqCst);
        let observation = self
            .observations
            .get(index)
            .or_else(|| self.observations.last())
            .expect("fixture authority has an observation")
            .clone();
        Box::pin(async move { Ok(observation) })
    }
}

#[derive(Clone, Copy)]
struct FixtureCancellation {
    cancelled: bool,
}

impl FederationCancellationV2 for FixtureCancellation {
    fn cancelled<'a>(&'a self) -> FederationV2Future<'a, ()> {
        if self.cancelled {
            Box::pin(async {})
        } else {
            Box::pin(std::future::pending())
        }
    }
}

fn terminal_response(query: &FederatedQueryV2) -> RemoteFederatedResponseV2 {
    RemoteFederatedResponseV2 {
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
    }
    .sealed()
}

#[tokio::test]
async fn one_attempt_returns_bounded_partial_result() {
    let query = query();
    let lease = lease(&query);
    let authority = FixtureAuthority::stable(&query, &lease);
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(terminal_response(&query)));
    let result = execute_once(
        &transport,
        &authority,
        &FixtureCancellation { cancelled: false },
        10,
        query.clone(),
        &lease,
    )
    .await
    .unwrap_or_else(|error| panic!("valid result: {error}"));
    assert_eq!(result.items.len(), 2);
    assert_eq!(result.coverage.truncated_items, 1);
    assert_eq!(result.completeness, FederatedCompletenessV2::Partial);
    assert_eq!(result.validity, FederatedValidityV2::Valid);
    assert_eq!(authority.calls.load(Ordering::SeqCst), 2);
    result
        .validate()
        .unwrap_or_else(|error| panic!("valid receipt: {error}"));
}

#[tokio::test]
async fn nonterminal_attempt_is_explicitly_indeterminate_without_retry() {
    let query = query();
    let lease = lease(&query);
    let authority = FixtureAuthority::stable(&query, &lease);
    let transport = FixtureTransport::immediate(FederationTransportResultV2::NonTerminal(
        FederationTransportOutcomeV2::TimedOut,
    ));
    let result = execute_once(
        &transport,
        &authority,
        &FixtureCancellation { cancelled: false },
        10,
        query.clone(),
        &lease,
    )
    .await
    .unwrap_or_else(|error| panic!("indeterminate result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.completeness, FederatedCompletenessV2::Indeterminate);
    assert_eq!(result.validity, FederatedValidityV2::Indeterminate);
    assert_eq!(result.coverage.failed_peers, 1);
    assert_eq!(result.expires_unix_ms, 90);
}

#[tokio::test]
async fn response_digest_binds_every_remote_evidence_field() {
    let query = query();
    let lease = lease(&query);
    let authority = FixtureAuthority::stable(&query, &lease);
    let mut response = terminal_response(&query);
    response.items[0].record_digest = digest("tampered-record");
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &FixtureCancellation { cancelled: false },
            10,
            query,
            &lease,
        )
        .await,
        Err(FederationV2Error::DigestMismatch("response"))
    );
}

#[tokio::test]
async fn response_cannot_be_replayed_across_query_bindings() {
    let first_query = query();
    let response = terminal_response(&first_query);
    let mut second_query = query();
    second_query.nonce_digest = digest("different-nonce");
    let second_lease = lease(&second_query);
    let authority = FixtureAuthority::stable(&second_query, &second_lease);
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &FixtureCancellation { cancelled: false },
            10,
            second_query,
            &second_lease,
        )
        .await,
        Err(FederationV2Error::DigestMismatch("response_query_binding"))
    );
}

#[tokio::test]
async fn result_expiry_is_capped_by_lease_and_query_deadline() {
    let query = query();
    let lease = lease(&query);
    let authority = FixtureAuthority::stable(&query, &lease);
    let mut response = terminal_response(&query);
    response.expires_unix_ms = 1_000;
    response = response.sealed();
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    let result = execute_once(
        &transport,
        &authority,
        &FixtureCancellation { cancelled: false },
        10,
        query,
        &lease,
    )
    .await
    .unwrap_or_else(|error| panic!("valid capped result: {error}"));
    assert_eq!(result.expires_unix_ms, 90);
}

#[tokio::test]
async fn post_transport_revocation_fails_closed() {
    let query = query();
    let lease = lease(&query);
    let first = authority_observation(&query, &lease);
    let mut revoked = first.clone();
    revoked.revoked = true;
    let authority = FixtureAuthority::sequence(vec![first, revoked]);
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(terminal_response(&query)));
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &FixtureCancellation { cancelled: false },
            10,
            query,
            &lease,
        )
        .await,
        Err(FederationV2Error::LeaseRevoked)
    );
}

#[tokio::test]
async fn post_transport_generation_change_fails_closed() {
    let query = query();
    let lease = lease(&query);
    let first = authority_observation(&query, &lease);
    let mut changed = first.clone();
    changed.generation_vector_digest = digest("changed-generation");
    let authority = FixtureAuthority::sequence(vec![first, changed]);
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(terminal_response(&query)));
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &FixtureCancellation { cancelled: false },
            10,
            query,
            &lease,
        )
        .await,
        Err(FederationV2Error::DigestMismatch(
            "authority_generation_vector"
        ))
    );
}

#[tokio::test(start_paused = true)]
async fn hard_deadline_interrupts_slow_transport() {
    let mut query = query();
    query.deadline_unix_ms = 20;
    let mut lease = lease(&query);
    lease.expires_unix_ms = 90;
    lease.query_binding_digest = query.binding_digest();
    let authority = FixtureAuthority::stable(&query, &lease);
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(terminal_response(&query))),
        delay_ms: 1_000,
    };
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &FixtureCancellation { cancelled: false },
            10,
            query,
            &lease,
        )
        .await,
        Err(FederationV2Error::AttemptTimedOut)
    );
}

#[tokio::test(start_paused = true)]
async fn cancellation_interrupts_in_flight_transport() {
    let query = query();
    let lease = lease(&query);
    let authority = FixtureAuthority::stable(&query, &lease);
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(terminal_response(&query))),
        delay_ms: 1_000,
    };
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &FixtureCancellation { cancelled: true },
            10,
            query,
            &lease,
        )
        .await,
        Err(FederationV2Error::Cancelled)
    );
}

#[tokio::test]
async fn stale_generation_never_exposes_remote_items() {
    let query = query();
    let lease = lease(&query);
    let authority = FixtureAuthority::stable(&query, &lease);
    let mut response = terminal_response(&query);
    response.generation_vector_digest = digest("stale-generation");
    response = response.sealed();
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    let result = execute_once(
        &transport,
        &authority,
        &FixtureCancellation { cancelled: false },
        10,
        query,
        &lease,
    )
    .await
    .unwrap_or_else(|error| panic!("stale result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.validity, FederatedValidityV2::StaleGeneration);
}

#[tokio::test]
async fn peer_scope_and_lease_drift_fail_closed() {
    let query = query();
    let lease = lease(&query);
    let authority = FixtureAuthority::stable(&query, &lease);
    let mut response = terminal_response(&query);
    response.peer_id = id("peer:other");
    response = response.sealed();
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &FixtureCancellation { cancelled: false },
            10,
            query.clone(),
            &lease,
        )
        .await,
        Err(FederationV2Error::IdentityMismatch("response_peer"))
    );

    let mut stale_lease = lease(&query);
    stale_lease.lease_epoch += 1;
    let stale_authority = FixtureAuthority::stable(&query, &stale_lease);
    let transport = FixtureTransport::immediate(FederationTransportResultV2::NonTerminal(
        FederationTransportOutcomeV2::Unavailable,
    ));
    assert_eq!(
        execute_once(
            &transport,
            &stale_authority,
            &FixtureCancellation { cancelled: false },
            10,
            query,
            &stale_lease,
        )
        .await,
        Err(FederationV2Error::LeaseEpochMismatch)
    );
}

#[tokio::test]
async fn duplicate_remote_identity_is_rejected() {
    let query = query();
    let lease = lease(&query);
    let authority = FixtureAuthority::stable(&query, &lease);
    let mut response = terminal_response(&query);
    response.items = vec![item(1), item(1)];
    response = response.sealed();
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    assert_eq!(
        execute_once(
            &transport,
            &authority,
            &FixtureCancellation { cancelled: false },
            10,
            query,
            &lease,
        )
        .await,
        Err(FederationV2Error::DuplicateResultIdentity)
    );
}

#[tokio::test]
async fn restored_result_rejects_unaccounted_peer_coverage() {
    let query = query();
    let lease = lease(&query);
    let authority = FixtureAuthority::stable(&query, &lease);
    let transport =
        FixtureTransport::immediate(FederationTransportResultV2::Terminal(terminal_response(&query)));
    let mut result = execute_once(
        &transport,
        &authority,
        &FixtureCancellation { cancelled: false },
        10,
        query,
        &lease,
    )
    .await
    .expect("valid result");
    result.coverage.completed_peers = 0;
    result.result_digest = result.compute_result_digest();
    assert_eq!(result.validate(), Err(FederationV2Error::InvalidCoverage));
}

#[test]
fn response_digest_is_order_independent_for_canonical_item_order() {
    let query = query();
    let left = terminal_response(&query);
    let mut right = left.clone();
    right.items.reverse();
    right.response_digest = right.compute_response_digest();
    assert_eq!(left.response_digest, right.response_digest);
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
