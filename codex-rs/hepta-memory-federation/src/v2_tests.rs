use super::*;

use std::future::pending;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

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

#[derive(Clone)]
struct FixtureClock {
    now: Arc<AtomicU64>,
}

impl FixtureClock {
    fn new(now_unix_ms: u64) -> Self {
        Self {
            now: Arc::new(AtomicU64::new(now_unix_ms)),
        }
    }
}

impl FederationClockV2 for FixtureClock {
    fn now_unix_ms(&self) -> u64 {
        self.now.load(Ordering::SeqCst)
    }
}

#[derive(Clone)]
struct AuthorityState {
    generation_vector_digest: Digest32,
    expires_unix_ms: u64,
    revoked: bool,
}

#[derive(Clone)]
struct FixtureAuthority {
    state: Arc<Mutex<AuthorityState>>,
}

impl FixtureAuthority {
    fn current(query: &FederatedQueryV2) -> Self {
        Self {
            state: Arc::new(Mutex::new(AuthorityState {
                generation_vector_digest: query.generation_vector_digest,
                expires_unix_ms: 90,
                revoked: false,
            })),
        }
    }

    fn set_revoked(&self, revoked: bool) {
        self.state.lock().expect("authority lock").revoked = revoked;
    }

    fn set_generation(&self, generation_vector_digest: Digest32) {
        self.state
            .lock()
            .expect("authority lock")
            .generation_vector_digest = generation_vector_digest;
    }

    fn set_expiry(&self, expires_unix_ms: u64) {
        self.state.lock().expect("authority lock").expires_unix_ms = expires_unix_ms;
    }
}

impl FederationAuthorityV2 for FixtureAuthority {
    fn observe<'a>(
        &'a self,
        query: &'a FederatedQueryV2,
        lease: &'a FederatedLeaseV2,
    ) -> FederationAuthorityFutureV2<'a> {
        let state = self.state.lock().expect("authority lock").clone();
        let observation = FederationAuthorityObservationV2 {
            lease_id: lease.lease_id.clone(),
            query_binding_digest: query.binding_digest(),
            generation_vector_digest: state.generation_vector_digest,
            lease_epoch: query.lease_epoch,
            expires_unix_ms: state.expires_unix_ms,
            revoked: state.revoked,
        };
        Box::pin(async move { Ok(observation) })
    }
}

struct NeverCancelled;

impl FederationCancellationV2 for NeverCancelled {
    fn is_cancelled(&self) -> bool {
        false
    }

    fn cancelled<'a>(&'a self) -> FederationCancellationFutureV2<'a> {
        Box::pin(pending())
    }
}

struct DelayedCancellation {
    delay: Duration,
}

impl FederationCancellationV2 for DelayedCancellation {
    fn is_cancelled(&self) -> bool {
        false
    }

    fn cancelled<'a>(&'a self) -> FederationCancellationFutureV2<'a> {
        let delay = self.delay;
        Box::pin(async move {
            tokio::time::sleep(delay).await;
        })
    }
}

#[derive(Clone)]
struct FixtureTransport {
    result: Result<FederationTransportResultV2, FederationV2Error>,
    delay: Duration,
    on_complete: Option<Arc<dyn Fn() + Send + Sync>>,
}

impl FixtureTransport {
    fn immediate(result: FederationTransportResultV2) -> Self {
        Self {
            result: Ok(result),
            delay: Duration::ZERO,
            on_complete: None,
        }
    }
}

impl FederationTransportV2 for FixtureTransport {
    fn send_once<'a>(&'a self, _query: &'a FederatedQueryV2) -> FederationTransportFutureV2<'a> {
        let result = self.result.clone();
        let delay = self.delay;
        let on_complete = self.on_complete.clone();
        Box::pin(async move {
            if !delay.is_zero() {
                tokio::time::sleep(delay).await;
            }
            if let Some(on_complete) = on_complete {
                on_complete();
            }
            result
        })
    }
}

async fn run(
    transport: &FixtureTransport,
    query: FederatedQueryV2,
    lease: &FederatedLeaseV2,
    authority: &FixtureAuthority,
) -> Result<FederatedResultV2, FederationV2Error> {
    execute_once(
        transport,
        authority,
        &FixtureClock::new(10),
        &NeverCancelled,
        query,
        lease,
    )
    .await
}

#[tokio::test]
async fn one_attempt_returns_bounded_partial_result() {
    let query = query();
    let transport = FixtureTransport::immediate(FederationTransportResultV2::Terminal(
        terminal_response(&query),
    ));
    let result = run(&transport, query.clone(), &lease(&query), &FixtureAuthority::current(&query))
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
async fn empty_remote_store_may_report_zero_frontier() {
    let query = query();
    let mut response = terminal_response(&query);
    response.items.clear();
    response.observed_frontier = 0;
    response.completeness = FederatedCompletenessV2::Empty;
    response.response_digest = response.compute_response_digest();
    let transport = FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    let result = run(
        &transport,
        query.clone(),
        &lease(&query),
        &FixtureAuthority::current(&query),
    )
    .await
    .expect("empty store is a valid terminal result");
    assert!(result.items.is_empty());
    assert_eq!(result.observed_frontier, Some(0));
    assert_eq!(result.completeness, FederatedCompletenessV2::Empty);
    assert_eq!(result.validity, FederatedValidityV2::Valid);
}

#[tokio::test]
async fn nonterminal_attempt_is_explicitly_indeterminate_without_retry() {
    let query = query();
    let transport = FixtureTransport::immediate(FederationTransportResultV2::NonTerminal(
        FederationTransportOutcomeV2::Unavailable,
    ));
    let result = run(
        &transport,
        query.clone(),
        &lease(&query),
        &FixtureAuthority::current(&query),
    )
    .await
    .unwrap_or_else(|error| panic!("indeterminate result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.completeness, FederatedCompletenessV2::Indeterminate);
    assert_eq!(result.validity, FederatedValidityV2::Indeterminate);
    assert_eq!(result.coverage.failed_peers, 1);
}

#[tokio::test]
async fn stale_generation_never_exposes_remote_items() {
    let query = query();
    let mut response = terminal_response(&query);
    response.generation_vector_digest = digest("stale-generation");
    response.response_digest = response.compute_response_digest();
    let transport = FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    let result = run(
        &transport,
        query.clone(),
        &lease(&query),
        &FixtureAuthority::current(&query),
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
    let transport = FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    assert_eq!(
        run(
            &transport,
            query.clone(),
            &lease(&query),
            &FixtureAuthority::current(&query)
        )
        .await,
        Err(FederationV2Error::IdentityMismatch("response_peer"))
    );

    let mut stale_lease = lease(&query);
    stale_lease.lease_epoch += 1;
    let transport = FixtureTransport::immediate(FederationTransportResultV2::NonTerminal(
        FederationTransportOutcomeV2::Unavailable,
    ));
    assert_eq!(
        run(
            &transport,
            query.clone(),
            &stale_lease,
            &FixtureAuthority::current(&query)
        )
        .await,
        Err(FederationV2Error::LeaseEpochMismatch)
    );
}

#[tokio::test]
async fn duplicate_remote_identity_is_rejected() {
    let query = query();
    let mut response = terminal_response(&query);
    response.items = vec![item(1), item(1)];
    response.response_digest = response.compute_response_digest();
    let transport = FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    assert_eq!(
        run(
            &transport,
            query.clone(),
            &lease(&query),
            &FixtureAuthority::current(&query)
        )
        .await,
        Err(FederationV2Error::DuplicateResultIdentity)
    );
}

#[tokio::test]
async fn response_digest_rejects_field_tampering() {
    let query = query();
    let mut response = terminal_response(&query);
    response.observed_frontier += 1;
    let transport = FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    assert_eq!(
        run(
            &transport,
            query.clone(),
            &lease(&query),
            &FixtureAuthority::current(&query)
        )
        .await,
        Err(FederationV2Error::DigestMismatch("response"))
    );
}

#[tokio::test]
async fn response_query_binding_rejects_cross_query_replay() {
    let original = query();
    let response = terminal_response(&original);
    let mut replay_query = original.clone();
    replay_query.query_id = id("query:replay");
    replay_query.nonce_digest = digest("nonce:replay");
    let replay_lease = lease(&replay_query);
    let transport = FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    assert_eq!(
        run(
            &transport,
            replay_query.clone(),
            &replay_lease,
            &FixtureAuthority::current(&replay_query),
        )
        .await,
        Err(FederationV2Error::DigestMismatch("response_query_binding"))
    );
}

#[tokio::test]
async fn result_expiry_is_clamped_to_live_authority_ceiling() {
    let query = query();
    let mut response = terminal_response(&query);
    response.expires_unix_ms = 1_000;
    response.response_digest = response.compute_response_digest();
    let authority = FixtureAuthority::current(&query);
    authority.set_expiry(70);
    let transport = FixtureTransport::immediate(FederationTransportResultV2::Terminal(response));
    let result = run(&transport, query.clone(), &lease(&query), &authority)
        .await
        .expect("valid clamped result");
    assert_eq!(result.expires_unix_ms, 70);
}

#[tokio::test]
async fn revocation_after_transport_strips_remote_items() {
    let query = query();
    let authority = FixtureAuthority::current(&query);
    let mutation = authority.clone();
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(terminal_response(
            &query,
        ))),
        delay: Duration::ZERO,
        on_complete: Some(Arc::new(move || mutation.set_revoked(true))),
    };
    let result = run(&transport, query.clone(), &lease(&query), &authority)
        .await
        .expect("revocation is represented fail-closed");
    assert!(result.items.is_empty());
    assert_eq!(result.validity, FederatedValidityV2::Revoked);
    assert_eq!(result.completeness, FederatedCompletenessV2::Partial);
}

#[tokio::test]
async fn generation_drift_after_transport_strips_remote_items() {
    let query = query();
    let authority = FixtureAuthority::current(&query);
    let mutation = authority.clone();
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(terminal_response(
            &query,
        ))),
        delay: Duration::ZERO,
        on_complete: Some(Arc::new(move || {
            mutation.set_generation(digest("generation:next"));
        })),
    };
    let result = run(&transport, query.clone(), &lease(&query), &authority)
        .await
        .expect("generation drift is represented fail-closed");
    assert!(result.items.is_empty());
    assert_eq!(result.validity, FederatedValidityV2::StaleGeneration);
}

#[tokio::test]
async fn stale_authority_before_dispatch_blocks_transport() {
    let query = query();
    let authority = FixtureAuthority::current(&query);
    authority.set_generation(digest("generation:next"));
    let dispatched = Arc::new(AtomicBool::new(false));
    let observed = Arc::clone(&dispatched);
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::NonTerminal(
            FederationTransportOutcomeV2::Unavailable,
        )),
        delay: Duration::ZERO,
        on_complete: Some(Arc::new(move || {
            observed.store(true, Ordering::SeqCst);
        })),
    };
    assert_eq!(
        run(&transport, query.clone(), &lease(&query), &authority).await,
        Err(FederationV2Error::AuthorityGenerationMismatch)
    );
    assert!(!dispatched.load(Ordering::SeqCst));
}

#[tokio::test]
async fn engine_deadline_cancels_inflight_transport_future() {
    let mut query = query();
    query.deadline_unix_ms = 15;
    let lease = lease(&query);
    let completed = Arc::new(AtomicBool::new(false));
    let observed = Arc::clone(&completed);
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(terminal_response(
            &query,
        ))),
        delay: Duration::from_millis(50),
        on_complete: Some(Arc::new(move || {
            observed.store(true, Ordering::SeqCst);
        })),
    };
    let result = execute_once(
        &transport,
        &FixtureAuthority::current(&query),
        &FixtureClock::new(10),
        &NeverCancelled,
        query,
        &lease,
    )
    .await
    .expect("deadline produces indeterminate result");
    assert_eq!(result.validity, FederatedValidityV2::Indeterminate);
    assert!(!completed.load(Ordering::SeqCst));
}

#[tokio::test]
async fn cancellation_interrupts_inflight_transport_future() {
    let mut query = query();
    query.deadline_unix_ms = 1_000;
    let lease = lease(&query);
    let completed = Arc::new(AtomicBool::new(false));
    let observed = Arc::clone(&completed);
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(terminal_response(
            &query,
        ))),
        delay: Duration::from_millis(100),
        on_complete: Some(Arc::new(move || {
            observed.store(true, Ordering::SeqCst);
        })),
    };
    let result = execute_once(
        &transport,
        &FixtureAuthority::current(&query),
        &FixtureClock::new(10),
        &DelayedCancellation {
            delay: Duration::from_millis(5),
        },
        query,
        &lease,
    )
    .await
    .expect("cancellation produces indeterminate result");
    assert_eq!(result.validity, FederatedValidityV2::Indeterminate);
    tokio::time::sleep(Duration::from_millis(20)).await;
    assert!(!completed.load(Ordering::SeqCst));
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
