use std::future;
use std::future::Future;
use std::sync::Arc;
use std::task::Context;
use std::task::Poll;
use std::task::Wake;
use std::task::Waker;
use std::thread;

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
}

impl FederationTransportV2 for FixtureTransport {
    fn send_once<'a>(&'a self, _query: &'a FederatedQueryV2) -> FederationTransportFuture<'a> {
        let result = self.result.clone();
        Box::pin(async move { result })
    }
}

struct PendingTransport;

impl FederationTransportV2 for PendingTransport {
    fn send_once<'a>(&'a self, _query: &'a FederatedQueryV2) -> FederationTransportFuture<'a> {
        Box::pin(future::pending())
    }
}

#[derive(Clone, Copy)]
struct FixtureAuthority {
    state: FederationAuthorityStateV2,
    observed_unix_ms: u64,
}

impl FederationAuthorityV2 for FixtureAuthority {
    fn revalidate<'a>(
        &'a self,
        query: &'a FederatedQueryV2,
        _lease: &'a FederatedLeaseV2,
    ) -> FederationAuthorityFuture<'a> {
        let observation = FederationAuthorityObservationV2 {
            query_binding_digest: query.binding_digest(),
            lease_epoch: query.lease_epoch,
            observed_unix_ms: self.observed_unix_ms,
            state: self.state,
        };
        Box::pin(async move { Ok(observation) })
    }
}

#[derive(Clone, Copy)]
enum FixtureControl {
    Pending,
    Stop(FederationStopReasonV2),
}

impl FederationAttemptControlV2 for FixtureControl {
    fn wait_for_stop<'a>(&'a self, _query: &'a FederatedQueryV2) -> FederationStopFuture<'a> {
        match self {
            Self::Pending => Box::pin(future::pending()),
            Self::Stop(reason) => Box::pin(future::ready(*reason)),
        }
    }
}

fn current_authority() -> FixtureAuthority {
    FixtureAuthority {
        state: FederationAuthorityStateV2::Current,
        observed_unix_ms: 20,
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
    .seal()
    .unwrap_or_else(|error| panic!("valid terminal response: {error}"))
}

fn execute(
    transport: &impl FederationTransportV2,
    query: FederatedQueryV2,
    lease: &FederatedLeaseV2,
) -> Result<FederatedResultV2, FederationV2Error> {
    let authority = current_authority();
    let control = FixtureControl::Pending;
    block_on(execute_once(
        transport, &authority, &control, 10, query, lease,
    ))
}

#[test]
fn one_attempt_returns_bounded_partial_result() {
    let query = query();
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(terminal_response(
            &query,
        ))),
    };
    let result = execute(&transport, query.clone(), &lease(&query))
        .unwrap_or_else(|error| panic!("valid result: {error}"));
    assert_eq!(result.items.len(), 2);
    assert_eq!(result.coverage.truncated_items, 1);
    assert_eq!(result.completeness, FederatedCompletenessV2::Partial);
    assert_eq!(result.validity, FederatedValidityV2::Valid);
    assert_eq!(result.expires_unix_ms, 80);
    assert!(result.authority_observation_digest.is_some());
    result
        .validate()
        .unwrap_or_else(|error| panic!("valid receipt: {error}"));
}

#[test]
fn response_digest_detects_field_tampering() {
    let query = query();
    let mut response = terminal_response(&query);
    response.observed_frontier += 1;
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(response)),
    };
    assert_eq!(
        execute(&transport, query.clone(), &lease(&query)),
        Err(FederationV2Error::DigestMismatch("response"))
    );
}

#[test]
fn response_cannot_replay_across_query_binding() {
    let first = query();
    let response = terminal_response(&first);
    let mut second = query();
    second.query_id = id("query:2");
    second.nonce_digest = digest("nonce-2");
    let second_lease = lease(&second);
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(response)),
    };
    assert_eq!(
        execute(&transport, second, &second_lease),
        Err(FederationV2Error::DigestMismatch("response_query_binding"))
    );
}

#[test]
fn result_expiry_is_capped_by_lease_and_query() {
    let query = query();
    let mut response = terminal_response(&query);
    response.expires_unix_ms = 500;
    response.response_digest = response.compute_response_digest();
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(response)),
    };
    let result = execute(&transport, query.clone(), &lease(&query))
        .unwrap_or_else(|error| panic!("valid capped result: {error}"));
    assert_eq!(result.expires_unix_ms, 90);
}

#[test]
fn post_io_revocation_suppresses_remote_items() {
    let query = query();
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(terminal_response(
            &query,
        ))),
    };
    let authority = FixtureAuthority {
        state: FederationAuthorityStateV2::Revoked,
        observed_unix_ms: 20,
    };
    let control = FixtureControl::Pending;
    let result = block_on(execute_once(
        &transport,
        &authority,
        &control,
        10,
        query.clone(),
        &lease(&query),
    ))
    .unwrap_or_else(|error| panic!("revoked result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.validity, FederatedValidityV2::Revoked);
    assert_eq!(result.completeness, FederatedCompletenessV2::Partial);
}

#[test]
fn post_io_generation_drift_suppresses_remote_items() {
    let query = query();
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(terminal_response(
            &query,
        ))),
    };
    let authority = FixtureAuthority {
        state: FederationAuthorityStateV2::StaleGeneration,
        observed_unix_ms: 20,
    };
    let control = FixtureControl::Pending;
    let result = block_on(execute_once(
        &transport,
        &authority,
        &control,
        10,
        query.clone(),
        &lease(&query),
    ))
    .unwrap_or_else(|error| panic!("stale result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.validity, FederatedValidityV2::StaleGeneration);
}

#[test]
fn deadline_control_interrupts_pending_transport() {
    let query = query();
    let authority = current_authority();
    let control = FixtureControl::Stop(FederationStopReasonV2::DeadlineExpired);
    assert_eq!(
        block_on(execute_once(
            &PendingTransport,
            &authority,
            &control,
            10,
            query.clone(),
            &lease(&query),
        )),
        Err(FederationV2Error::DeadlineExpired)
    );
}

#[test]
fn cancellation_control_interrupts_pending_transport() {
    let query = query();
    let authority = current_authority();
    let control = FixtureControl::Stop(FederationStopReasonV2::Cancelled);
    assert_eq!(
        block_on(execute_once(
            &PendingTransport,
            &authority,
            &control,
            10,
            query.clone(),
            &lease(&query),
        )),
        Err(FederationV2Error::AttemptCancelled)
    );
}

#[test]
fn post_io_observation_cannot_outlive_lease() {
    let query = query();
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(terminal_response(
            &query,
        ))),
    };
    let authority = FixtureAuthority {
        state: FederationAuthorityStateV2::Current,
        observed_unix_ms: 95,
    };
    let control = FixtureControl::Pending;
    assert_eq!(
        block_on(execute_once(
            &transport,
            &authority,
            &control,
            10,
            query.clone(),
            &lease(&query),
        )),
        Err(FederationV2Error::LeaseExpired)
    );
}

#[test]
fn nonterminal_attempt_is_explicitly_indeterminate_without_retry() {
    let query = query();
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::NonTerminal(
            FederationTransportOutcomeV2::TimedOut,
        )),
    };
    let result = execute(&transport, query.clone(), &lease(&query))
        .unwrap_or_else(|error| panic!("indeterminate result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.completeness, FederatedCompletenessV2::Indeterminate);
    assert_eq!(result.validity, FederatedValidityV2::Indeterminate);
    assert_eq!(result.coverage.failed_peers, 1);
    assert_eq!(result.expires_unix_ms, 90);
    assert!(result.authority_observation_digest.is_none());
}

#[test]
fn stale_response_generation_never_exposes_remote_items() {
    let query = query();
    let mut response = terminal_response(&query);
    response.generation_vector_digest = digest("stale-generation");
    response.response_digest = response.compute_response_digest();
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(response)),
    };
    let result = execute(&transport, query.clone(), &lease(&query))
        .unwrap_or_else(|error| panic!("stale result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.validity, FederatedValidityV2::StaleGeneration);
}

#[test]
fn peer_scope_and_lease_drift_fail_closed() {
    let query = query();
    let mut response = terminal_response(&query);
    response.peer_id = id("peer:other");
    response.response_digest = response.compute_response_digest();
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(response)),
    };
    assert_eq!(
        execute(&transport, query.clone(), &lease(&query)),
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
        execute(&transport, query, &stale_lease),
        Err(FederationV2Error::LeaseEpochMismatch)
    );
}

#[test]
fn duplicate_remote_identity_is_rejected() {
    let query = query();
    let mut response = terminal_response(&query);
    response.items = vec![item(1), item(1)];
    response.response_digest = response.compute_response_digest();
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(response)),
    };
    assert_eq!(
        execute(&transport, query.clone(), &lease(&query)),
        Err(FederationV2Error::DuplicateResultIdentity)
    );
}

#[test]
fn result_digest_binds_post_io_authority_observation() {
    let query = query();
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(terminal_response(
            &query,
        ))),
    };
    let mut result = execute(&transport, query.clone(), &lease(&query))
        .unwrap_or_else(|error| panic!("valid result: {error}"));
    result.authority_observation_digest = Some(digest("changed-authority"));
    assert_eq!(
        result.validate(),
        Err(FederationV2Error::DigestMismatch("result"))
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

struct ThreadWaker(thread::Thread);

impl Wake for ThreadWaker {
    fn wake(self: Arc<Self>) {
        self.0.unpark();
    }

    fn wake_by_ref(self: &Arc<Self>) {
        self.0.unpark();
    }
}

fn block_on<F: Future>(future: F) -> F::Output {
    let mut future = Box::pin(future);
    let waker = Waker::from(Arc::new(ThreadWaker(thread::current())));
    let mut context = Context::from_waker(&waker);
    loop {
        match future.as_mut().poll(&mut context) {
            Poll::Ready(output) => return output,
            Poll::Pending => thread::park(),
        }
    }
}
