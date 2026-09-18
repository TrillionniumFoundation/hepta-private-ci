//! Single-attempt, generation-bound federation boundary.
//!
//! `memory.federation` is a read-only adapter. It owns no remote facts, peer
//! enrollment, credential store, transactional writer or retry queue. A product
//! host supplies an enrolled transport, a current authority observer and an
//! attempt control. The engine validates one bounded attempt, races transport
//! and authority work against cancellation/deadline, and returns an explicit
//! complete, partial, empty, stale, revoked or indeterminate result. It never
//! performs a blind retry.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::future::Future;
use std::future::poll_fn;
use std::pin::Pin;
use std::task::Poll;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

pub const MAX_FEDERATED_RESULTS_V2: usize = 512;
const QUERY_DOMAIN: &[u8] = b"hepta.memory-federation.query.v2";
const RESPONSE_DOMAIN: &[u8] = b"hepta.memory-federation.response.v2";
const AUTHORITY_OBSERVATION_DOMAIN: &[u8] = b"hepta.memory-federation.authority-observation.v2";
const RESULT_DOMAIN: &[u8] = b"hepta.memory-federation.result.v2";
const CANCELLATION_DOMAIN: &[u8] = b"hepta.memory-federation.cancellation.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedQueryV2 {
    pub query_id: StableId,
    pub peer_id: StableId,
    pub principal_id: StableId,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub query_digest: Digest32,
    pub maximum_results: u32,
    pub deadline_unix_ms: u64,
    pub lease_epoch: u64,
    pub nonce_digest: Digest32,
}

impl FederatedQueryV2 {
    pub fn validate(&self, now_unix_ms: u64) -> Result<(), FederationV2Error> {
        if now_unix_ms >= self.deadline_unix_ms {
            return Err(FederationV2Error::DeadlineExpired);
        }
        if self.lease_epoch == 0 {
            return Err(FederationV2Error::ZeroValue("lease_epoch"));
        }
        let maximum_results = usize::try_from(self.maximum_results).unwrap_or(usize::MAX);
        if maximum_results == 0 || maximum_results > MAX_FEDERATED_RESULTS_V2 {
            return Err(FederationV2Error::InvalidMaximumResults);
        }
        for (name, digest) in [
            ("scope", self.scope_digest),
            ("purpose", self.purpose_digest),
            ("generation_vector", self.generation_vector_digest),
            ("query", self.query_digest),
            ("nonce", self.nonce_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        Ok(())
    }

    #[must_use]
    pub fn binding_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(QUERY_DOMAIN);
        push_id(&mut bytes, &self.query_id);
        push_id(&mut bytes, &self.peer_id);
        push_id(&mut bytes, &self.principal_id);
        for digest in [
            self.scope_digest,
            self.purpose_digest,
            self.generation_vector_digest,
            self.query_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, u64::from(self.maximum_results));
        push_u64(&mut bytes, self.deadline_unix_ms);
        push_u64(&mut bytes, self.lease_epoch);
        push_digest(&mut bytes, self.nonce_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedLeaseV2 {
    pub lease_id: StableId,
    pub query_id: StableId,
    pub peer_id: StableId,
    pub principal_id: StableId,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub query_binding_digest: Digest32,
    pub lease_epoch: u64,
    pub expires_unix_ms: u64,
    pub revoked: bool,
}

impl FederatedLeaseV2 {
    pub fn validate_for_query(
        &self,
        now_unix_ms: u64,
        query: &FederatedQueryV2,
    ) -> Result<(), FederationV2Error> {
        if self.revoked {
            return Err(FederationV2Error::LeaseRevoked);
        }
        if now_unix_ms >= self.expires_unix_ms {
            return Err(FederationV2Error::LeaseExpired);
        }
        if self.lease_epoch == 0 || self.lease_epoch != query.lease_epoch {
            return Err(FederationV2Error::LeaseEpochMismatch);
        }
        for (name, left, right) in [
            ("query_id", self.query_id.as_str(), query.query_id.as_str()),
            ("peer_id", self.peer_id.as_str(), query.peer_id.as_str()),
            (
                "principal_id",
                self.principal_id.as_str(),
                query.principal_id.as_str(),
            ),
        ] {
            if left != right {
                return Err(FederationV2Error::IdentityMismatch(name));
            }
        }
        for (name, left, right) in [
            ("scope", self.scope_digest, query.scope_digest),
            ("purpose", self.purpose_digest, query.purpose_digest),
            (
                "generation_vector",
                self.generation_vector_digest,
                query.generation_vector_digest,
            ),
            (
                "query_binding",
                self.query_binding_digest,
                query.binding_digest(),
            ),
        ] {
            ensure_digest(name, left)?;
            if left != right {
                return Err(FederationV2Error::DigestMismatch(name));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedEvidenceItemV2 {
    pub source_owner_id: StableId,
    pub record_id: StableId,
    pub record_revision: Revision,
    pub record_digest: Digest32,
    pub support_digest: Digest32,
    pub validity_digest: Digest32,
}

impl FederatedEvidenceItemV2 {
    fn validate(&self) -> Result<(), FederationV2Error> {
        ensure_digest("record", self.record_digest)?;
        ensure_digest("support", self.support_digest)?;
        ensure_digest("validity", self.validity_digest)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederatedCompletenessV2 {
    Complete,
    Partial,
    Empty,
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederatedValidityV2 {
    Valid,
    StaleGeneration,
    Revoked,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RemoteFederatedResponseV2 {
    pub peer_id: StableId,
    pub query_binding_digest: Digest32,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub response_digest: Digest32,
    pub observed_frontier: u64,
    pub expires_unix_ms: u64,
    pub items: Vec<FederatedEvidenceItemV2>,
    pub completeness: FederatedCompletenessV2,
    pub terminal_observed: bool,
}

impl RemoteFederatedResponseV2 {
    fn validate_unsigned_shape(&self) -> Result<(), FederationV2Error> {
        if !self.terminal_observed {
            return Err(FederationV2Error::MissingTerminalObservation);
        }
        if self.observed_frontier == 0 {
            return Err(FederationV2Error::ZeroValue("observed_frontier"));
        }
        if self.expires_unix_ms == 0 {
            return Err(FederationV2Error::ZeroValue("response_expiry"));
        }
        for (name, digest) in [
            ("response_query_binding", self.query_binding_digest),
            ("response_scope", self.scope_digest),
            ("response_purpose", self.purpose_digest),
            ("response_generation_vector", self.generation_vector_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.items.len() > MAX_FEDERATED_RESULTS_V2 {
            return Err(FederationV2Error::ResultLimitExceeded);
        }
        if matches!(self.completeness, FederatedCompletenessV2::Empty) && !self.items.is_empty() {
            return Err(FederationV2Error::InvalidCompleteness);
        }
        if matches!(self.completeness, FederatedCompletenessV2::Complete) && self.items.is_empty() {
            return Err(FederationV2Error::InvalidCompleteness);
        }
        if matches!(self.completeness, FederatedCompletenessV2::Indeterminate) {
            return Err(FederationV2Error::InvalidCompleteness);
        }
        validate_unique_items(&self.items)
    }

    fn validate_shape(&self) -> Result<(), FederationV2Error> {
        self.validate_unsigned_shape()?;
        ensure_digest("response", self.response_digest)?;
        if self.response_digest != self.compute_response_digest() {
            return Err(FederationV2Error::DigestMismatch("response"));
        }
        Ok(())
    }

    fn validate_for_query(&self, query: &FederatedQueryV2) -> Result<(), FederationV2Error> {
        self.validate_shape()?;
        if self.peer_id != query.peer_id {
            return Err(FederationV2Error::IdentityMismatch("response_peer"));
        }
        if self.query_binding_digest != query.binding_digest() {
            return Err(FederationV2Error::DigestMismatch("response_query_binding"));
        }
        if self.scope_digest != query.scope_digest {
            return Err(FederationV2Error::DigestMismatch("response_scope"));
        }
        if self.purpose_digest != query.purpose_digest {
            return Err(FederationV2Error::DigestMismatch("response_purpose"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_response_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(RESPONSE_DOMAIN);
        push_id(&mut bytes, &self.peer_id);
        push_digest(&mut bytes, self.query_binding_digest);
        push_digest(&mut bytes, self.scope_digest);
        push_digest(&mut bytes, self.purpose_digest);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_u64(&mut bytes, self.observed_frontier);
        push_u64(&mut bytes, self.expires_unix_ms);
        push_items(&mut bytes, &self.items);
        bytes.push(completeness_code(self.completeness));
        bytes.push(u8::from(self.terminal_observed));
        Digest32::of_bytes(&bytes)
    }

    pub fn seal(mut self) -> Result<Self, FederationV2Error> {
        self.validate_unsigned_shape()?;
        self.response_digest = self.compute_response_digest();
        Ok(self)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationTransportOutcomeV2 {
    Unavailable,
    TimedOut,
    NoTerminalObservation,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FederationTransportResultV2 {
    Terminal(RemoteFederatedResponseV2),
    NonTerminal(FederationTransportOutcomeV2),
}

pub type FederationTransportFuture<'a> = Pin<
    Box<dyn Future<Output = Result<FederationTransportResultV2, FederationV2Error>> + Send + 'a>,
>;

/// One enrolled, authenticated transport attempt.
///
/// `execute_once` invokes this method exactly once. Any retry policy belongs to
/// a separately authorized caller and must allocate a new nonce and attempt ID.
/// Dropping the returned future is the cancellation boundary for an in-flight
/// attempt; production transports must make a dropped future stop further I/O.
pub trait FederationTransportV2: Send + Sync {
    fn send_once<'a>(&'a self, query: &'a FederatedQueryV2) -> FederationTransportFuture<'a>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationAuthorityStateV2 {
    Current,
    Revoked,
    StaleGeneration,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationAuthorityObservationV2 {
    pub query_binding_digest: Digest32,
    pub lease_epoch: u64,
    pub observed_unix_ms: u64,
    pub state: FederationAuthorityStateV2,
}

impl FederationAuthorityObservationV2 {
    pub fn validate_for(
        &self,
        query: &FederatedQueryV2,
        lease: &FederatedLeaseV2,
    ) -> Result<(), FederationV2Error> {
        ensure_digest("authority_query_binding", self.query_binding_digest)?;
        if self.query_binding_digest != query.binding_digest() {
            return Err(FederationV2Error::DigestMismatch("authority_query_binding"));
        }
        if self.lease_epoch == 0 || self.lease_epoch != query.lease_epoch {
            return Err(FederationV2Error::LeaseEpochMismatch);
        }
        if self.lease_epoch != lease.lease_epoch {
            return Err(FederationV2Error::LeaseEpochMismatch);
        }
        if self.observed_unix_ms == 0 {
            return Err(FederationV2Error::ZeroValue("authority_observed_at"));
        }
        Ok(())
    }

    #[must_use]
    pub fn binding_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(AUTHORITY_OBSERVATION_DOMAIN);
        push_digest(&mut bytes, self.query_binding_digest);
        push_u64(&mut bytes, self.lease_epoch);
        push_u64(&mut bytes, self.observed_unix_ms);
        bytes.push(authority_state_code(self.state));
        Digest32::of_bytes(&bytes)
    }
}

pub type FederationAuthorityFuture<'a> = Pin<
    Box<
        dyn Future<Output = Result<FederationAuthorityObservationV2, FederationV2Error>>
            + Send
            + 'a,
    >,
>;

/// Current authority observation performed after remote I/O and before evidence
/// becomes eligible for use.
pub trait FederationAuthorityV2: Send + Sync {
    fn revalidate<'a>(
        &'a self,
        query: &'a FederatedQueryV2,
        lease: &'a FederatedLeaseV2,
    ) -> FederationAuthorityFuture<'a>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationStopReasonV2 {
    Cancelled,
    DeadlineExpired,
}

pub type FederationStopFuture<'a> =
    Pin<Box<dyn Future<Output = FederationStopReasonV2> + Send + 'a>>;

/// Product-host cancellation/deadline source. The engine races this future
/// against both transport and post-I/O authority revalidation.
pub trait FederationAttemptControlV2: Send + Sync {
    fn wait_for_stop<'a>(&'a self, query: &'a FederatedQueryV2) -> FederationStopFuture<'a>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedCoverageV2 {
    pub requested_peers: u32,
    pub completed_peers: u32,
    pub failed_peers: u32,
    pub truncated_items: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedResultV2 {
    pub query_id: StableId,
    pub peer_id: StableId,
    pub query_binding_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub observed_frontier: Option<u64>,
    pub expires_unix_ms: u64,
    pub items: Vec<FederatedEvidenceItemV2>,
    pub coverage: FederatedCoverageV2,
    pub completeness: FederatedCompletenessV2,
    pub validity: FederatedValidityV2,
    pub remote_response_digest: Option<Digest32>,
    pub authority_observation_digest: Option<Digest32>,
    pub result_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl FederatedResultV2 {
    pub fn validate(&self) -> Result<(), FederationV2Error> {
        ensure_digest("query_binding", self.query_binding_digest)?;
        ensure_digest("generation_vector", self.generation_vector_digest)?;
        if self.expires_unix_ms == 0 {
            return Err(FederationV2Error::ZeroValue("result_expiry"));
        }
        if self.coverage.requested_peers != 1
            || u64::from(self.coverage.completed_peers) + u64::from(self.coverage.failed_peers) != 1
        {
            return Err(FederationV2Error::InvalidCoverage);
        }
        if self.items.len() > MAX_FEDERATED_RESULTS_V2 {
            return Err(FederationV2Error::ResultLimitExceeded);
        }
        let indeterminate = matches!(self.completeness, FederatedCompletenessV2::Indeterminate);
        if indeterminate != matches!(self.validity, FederatedValidityV2::Indeterminate) {
            return Err(FederationV2Error::InvalidCompleteness);
        }
        if indeterminate {
            if !self.items.is_empty()
                || self.observed_frontier.is_some()
                || self.remote_response_digest.is_some()
                || self.authority_observation_digest.is_some()
                || self.coverage.failed_peers != 1
            {
                return Err(FederationV2Error::InvalidCompleteness);
            }
        } else {
            if self.observed_frontier.is_none()
                || self.remote_response_digest.is_none()
                || self.authority_observation_digest.is_none()
                || self.coverage.completed_peers != 1
            {
                return Err(FederationV2Error::InvalidCoverage);
            }
            if matches!(
                self.validity,
                FederatedValidityV2::StaleGeneration | FederatedValidityV2::Revoked
            ) && !self.items.is_empty()
            {
                return Err(FederationV2Error::StaleEvidenceExposed);
            }
        }
        validate_unique_items(&self.items)?;
        if let Some(digest) = self.remote_response_digest {
            ensure_digest("remote_response", digest)?;
        }
        if let Some(digest) = self.authority_observation_digest {
            ensure_digest("authority_observation", digest)?;
        }
        if self.authority.grants_any() {
            return Err(FederationV2Error::AuthorityGranted);
        }
        if self.result_digest != self.compute_result_digest() {
            return Err(FederationV2Error::DigestMismatch("result"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_result_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(RESULT_DOMAIN);
        push_id(&mut bytes, &self.query_id);
        push_id(&mut bytes, &self.peer_id);
        push_digest(&mut bytes, self.query_binding_digest);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_optional_u64(&mut bytes, self.observed_frontier);
        push_u64(&mut bytes, self.expires_unix_ms);
        push_items(&mut bytes, &self.items);
        push_u64(&mut bytes, u64::from(self.coverage.requested_peers));
        push_u64(&mut bytes, u64::from(self.coverage.completed_peers));
        push_u64(&mut bytes, u64::from(self.coverage.failed_peers));
        push_u64(&mut bytes, u64::from(self.coverage.truncated_items));
        bytes.push(completeness_code(self.completeness));
        bytes.push(validity_code(self.validity));
        push_optional_digest(&mut bytes, self.remote_response_digest);
        push_optional_digest(&mut bytes, self.authority_observation_digest);
        Digest32::of_bytes(&bytes)
    }
}

pub async fn execute_once<T, A, C>(
    transport: &T,
    authority: &A,
    control: &C,
    now_unix_ms: u64,
    query: FederatedQueryV2,
    lease: &FederatedLeaseV2,
) -> Result<FederatedResultV2, FederationV2Error>
where
    T: FederationTransportV2 + ?Sized,
    A: FederationAuthorityV2 + ?Sized,
    C: FederationAttemptControlV2 + ?Sized,
{
    query.validate(now_unix_ms)?;
    lease.validate_for_query(now_unix_ms, &query)?;
    let query_binding_digest = query.binding_digest();
    let transport_result = send_with_control(transport, control, &query).await?;
    let mut result = match transport_result {
        FederationTransportResultV2::NonTerminal(_) => FederatedResultV2 {
            query_id: query.query_id,
            peer_id: query.peer_id,
            query_binding_digest,
            generation_vector_digest: query.generation_vector_digest,
            observed_frontier: None,
            expires_unix_ms: query.deadline_unix_ms.min(lease.expires_unix_ms),
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
            authority_observation_digest: None,
            result_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        },
        FederationTransportResultV2::Terminal(response) => {
            response.validate_for_query(&query)?;
            let authority_observation =
                revalidate_with_control(authority, control, &query, lease).await?;
            authority_observation.validate_for(&query, lease)?;
            if authority_observation.observed_unix_ms < now_unix_ms {
                return Err(FederationV2Error::AuthorityObservationRegressed);
            }
            ensure_post_io_horizon(
                authority_observation.observed_unix_ms,
                &query,
                lease,
                &response,
            )?;

            let stale_generation = response.generation_vector_digest
                != query.generation_vector_digest
                || matches!(
                    authority_observation.state,
                    FederationAuthorityStateV2::StaleGeneration
                );
            let revoked = matches!(
                authority_observation.state,
                FederationAuthorityStateV2::Revoked
            );
            let maximum_results =
                usize::try_from(query.maximum_results).unwrap_or(MAX_FEDERATED_RESULTS_V2);
            let remote_item_count = response.items.len();
            let mut items = if stale_generation || revoked {
                Vec::new()
            } else {
                response.items
            };
            items.truncate(maximum_results);
            let truncated_items = if stale_generation || revoked {
                0
            } else {
                remote_item_count.saturating_sub(items.len())
            };
            let completeness = if stale_generation || revoked {
                FederatedCompletenessV2::Partial
            } else if items.is_empty() {
                FederatedCompletenessV2::Empty
            } else if truncated_items > 0
                || matches!(response.completeness, FederatedCompletenessV2::Partial)
            {
                FederatedCompletenessV2::Partial
            } else {
                response.completeness
            };
            let validity = if revoked {
                FederatedValidityV2::Revoked
            } else if stale_generation {
                FederatedValidityV2::StaleGeneration
            } else {
                FederatedValidityV2::Valid
            };
            FederatedResultV2 {
                query_id: query.query_id,
                peer_id: query.peer_id,
                query_binding_digest,
                generation_vector_digest: query.generation_vector_digest,
                observed_frontier: Some(response.observed_frontier),
                expires_unix_ms: response
                    .expires_unix_ms
                    .min(lease.expires_unix_ms)
                    .min(query.deadline_unix_ms),
                items,
                coverage: FederatedCoverageV2 {
                    requested_peers: 1,
                    completed_peers: 1,
                    failed_peers: 0,
                    truncated_items: u32::try_from(truncated_items).unwrap_or(u32::MAX),
                },
                completeness,
                validity,
                remote_response_digest: Some(response.response_digest),
                authority_observation_digest: Some(authority_observation.binding_digest()),
                result_digest: Digest32::ZERO,
                authority: AuthorityPosture::DENY_ALL,
            }
        }
    };
    result.result_digest = result.compute_result_digest();
    result.validate()?;
    Ok(result)
}

async fn send_with_control<T, C>(
    transport: &T,
    control: &C,
    query: &FederatedQueryV2,
) -> Result<FederationTransportResultV2, FederationV2Error>
where
    T: FederationTransportV2 + ?Sized,
    C: FederationAttemptControlV2 + ?Sized,
{
    let mut transport_future = transport.send_once(query);
    let mut stop_future = control.wait_for_stop(query);
    poll_fn(|context| {
        if let Poll::Ready(reason) = stop_future.as_mut().poll(context) {
            return Poll::Ready(Err(stop_reason_error(reason)));
        }
        match transport_future.as_mut().poll(context) {
            Poll::Ready(result) => Poll::Ready(result),
            Poll::Pending => Poll::Pending,
        }
    })
    .await
}

async fn revalidate_with_control<A, C>(
    authority: &A,
    control: &C,
    query: &FederatedQueryV2,
    lease: &FederatedLeaseV2,
) -> Result<FederationAuthorityObservationV2, FederationV2Error>
where
    A: FederationAuthorityV2 + ?Sized,
    C: FederationAttemptControlV2 + ?Sized,
{
    let mut authority_future = authority.revalidate(query, lease);
    let mut stop_future = control.wait_for_stop(query);
    poll_fn(|context| {
        if let Poll::Ready(reason) = stop_future.as_mut().poll(context) {
            return Poll::Ready(Err(stop_reason_error(reason)));
        }
        match authority_future.as_mut().poll(context) {
            Poll::Ready(result) => Poll::Ready(result),
            Poll::Pending => Poll::Pending,
        }
    })
    .await
}

fn ensure_post_io_horizon(
    observed_unix_ms: u64,
    query: &FederatedQueryV2,
    lease: &FederatedLeaseV2,
    response: &RemoteFederatedResponseV2,
) -> Result<(), FederationV2Error> {
    if observed_unix_ms >= query.deadline_unix_ms {
        return Err(FederationV2Error::DeadlineExpired);
    }
    if observed_unix_ms >= lease.expires_unix_ms {
        return Err(FederationV2Error::LeaseExpired);
    }
    if observed_unix_ms >= response.expires_unix_ms {
        return Err(FederationV2Error::ResponseExpired);
    }
    Ok(())
}

const fn stop_reason_error(reason: FederationStopReasonV2) -> FederationV2Error {
    match reason {
        FederationStopReasonV2::Cancelled => FederationV2Error::AttemptCancelled,
        FederationStopReasonV2::DeadlineExpired => FederationV2Error::DeadlineExpired,
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationCancellationRequestV2 {
    pub cancellation_id: StableId,
    pub query_id: StableId,
    pub peer_id: StableId,
    pub query_binding_digest: Digest32,
    pub lease_epoch: u64,
    pub cancellation_nonce_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationCancellationReceiptV2 {
    pub cancellation_id: StableId,
    pub query_id: StableId,
    pub terminal_observed: bool,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn observe_cancellation(
    request: FederationCancellationRequestV2,
    terminal_observed: bool,
) -> Result<FederationCancellationReceiptV2, FederationV2Error> {
    ensure_digest("query_binding", request.query_binding_digest)?;
    ensure_digest("cancellation_nonce", request.cancellation_nonce_digest)?;
    if request.lease_epoch == 0 {
        return Err(FederationV2Error::ZeroValue("lease_epoch"));
    }
    let mut bytes = Vec::new();
    bytes.extend_from_slice(CANCELLATION_DOMAIN);
    push_id(&mut bytes, &request.cancellation_id);
    push_id(&mut bytes, &request.query_id);
    push_id(&mut bytes, &request.peer_id);
    push_digest(&mut bytes, request.query_binding_digest);
    push_u64(&mut bytes, request.lease_epoch);
    push_digest(&mut bytes, request.cancellation_nonce_digest);
    bytes.push(u8::from(terminal_observed));
    Ok(FederationCancellationReceiptV2 {
        cancellation_id: request.cancellation_id,
        query_id: request.query_id,
        terminal_observed,
        receipt_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FederationV2Error {
    ZeroValue(&'static str),
    EmptyDigest(&'static str),
    InvalidMaximumResults,
    DeadlineExpired,
    AttemptCancelled,
    LeaseExpired,
    LeaseRevoked,
    LeaseEpochMismatch,
    IdentityMismatch(&'static str),
    DigestMismatch(&'static str),
    MissingTerminalObservation,
    ResponseExpired,
    ResultLimitExceeded,
    DuplicateResultIdentity,
    InvalidCompleteness,
    InvalidCoverage,
    StaleEvidenceExposed,
    AuthorityObservationRegressed,
    AuthorityGranted,
    AuthorityRevalidationFailed,
    TransportRejected,
}

impl fmt::Display for FederationV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for FederationV2Error {}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), FederationV2Error> {
    if digest.is_zero() {
        return Err(FederationV2Error::EmptyDigest(name));
    }
    Ok(())
}

fn validate_unique_items(items: &[FederatedEvidenceItemV2]) -> Result<(), FederationV2Error> {
    let mut identities = BTreeSet::new();
    for item in items {
        item.validate()?;
        let identity = (
            item.source_owner_id.clone(),
            item.record_id.clone(),
            item.record_revision,
        );
        if !identities.insert(identity) {
            return Err(FederationV2Error::DuplicateResultIdentity);
        }
    }
    Ok(())
}

fn push_items(bytes: &mut Vec<u8>, items: &[FederatedEvidenceItemV2]) {
    let mut items = items.iter().collect::<Vec<_>>();
    items.sort_by(|left, right| {
        left.source_owner_id
            .cmp(&right.source_owner_id)
            .then_with(|| left.record_id.cmp(&right.record_id))
            .then_with(|| left.record_revision.cmp(&right.record_revision))
    });
    push_len(bytes, items.len());
    for item in items {
        push_id(bytes, &item.source_owner_id);
        push_id(bytes, &item.record_id);
        push_u64(bytes, item.record_revision.get());
        push_digest(bytes, item.record_digest);
        push_digest(bytes, item.support_digest);
        push_digest(bytes, item.validity_digest);
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_digest(bytes, value);
        }
        None => bytes.push(0),
    }
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
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

const fn completeness_code(value: FederatedCompletenessV2) -> u8 {
    match value {
        FederatedCompletenessV2::Complete => 0,
        FederatedCompletenessV2::Partial => 1,
        FederatedCompletenessV2::Empty => 2,
        FederatedCompletenessV2::Indeterminate => 3,
    }
}

const fn validity_code(value: FederatedValidityV2) -> u8 {
    match value {
        FederatedValidityV2::Valid => 0,
        FederatedValidityV2::StaleGeneration => 1,
        FederatedValidityV2::Revoked => 2,
        FederatedValidityV2::Indeterminate => 3,
    }
}

const fn authority_state_code(value: FederationAuthorityStateV2) -> u8 {
    match value {
        FederationAuthorityStateV2::Current => 0,
        FederationAuthorityStateV2::Revoked => 1,
        FederationAuthorityStateV2::StaleGeneration => 2,
    }
}

#[cfg(test)]
#[path = "v2_tests.rs"]
mod tests;
