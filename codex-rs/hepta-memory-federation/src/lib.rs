//! Scoped, fail-closed remote cognitive read verification.

#![forbid(unsafe_code)]

mod v2;
mod v3;

use std::cell::RefCell;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub use v2::FederatedCompletenessV2;
pub use v2::FederatedCoverageV2;
pub use v2::FederatedEvidenceItemV2;
pub use v2::FederatedLeaseV2;
pub use v2::FederatedQueryV2;
pub use v2::FederatedResultV2;
pub use v2::FederatedValidityV2;
pub use v2::FederationCancellationReceiptV2;
pub use v2::FederationCancellationRequestV2;
pub use v2::FederationTransportOutcomeV2;
pub use v2::FederationTransportResultV2;
pub use v2::FederationTransportV2;
pub use v2::FederationV2Error;
pub use v2::MAX_FEDERATED_RESULTS_V2;
pub use v2::RemoteFederatedResponseV2;
pub use v2::observe_cancellation;

pub use v3::FederatedAggregateResultV3;
pub use v3::FederatedAttemptV3;
pub use v3::FederatedCoverageV3;
pub use v3::FederatedPeerCoverageV3;
pub use v3::FederatedPeerEnrollmentV3;
pub use v3::FederatedPeerPermitV3;
pub use v3::FederatedPeerQueryV3;
pub use v3::FederatedPeerResultV3;
pub use v3::FederatedPeerTargetV3;
pub use v3::FederatedReadPlanV3;
pub use v3::FederatedReadSpecV3;
pub use v3::FederationCacheKeyV3;
pub use v3::FederationCancellationTokenV3;
pub use v3::FederationClientV3;
pub use v3::FederationClockV3;
pub use v3::FederationPeerFailureV3;
pub use v3::FederationPeerRegistryV3;
pub use v3::FederationResultCacheV3;
pub use v3::FederationTransportOutcomeV3;
pub use v3::FederationTransportResultV3;
pub use v3::FederationTransportV3;
pub use v3::FederationV3Error;
pub use v3::MAX_FEDERATED_PEERS_V3;
pub use v3::MAX_FEDERATION_CACHE_ENTRIES_V3;
pub use v3::MAX_FEDERATION_QUERY_LIFETIME_MS_V3;
pub use v3::MAX_FEDERATION_RESPONSE_BYTES_V3;
pub use v3::PinnedHttpsFederationTransportV3;
pub use v3::RemoteFederatedEnvelopeV3;
pub use v3::SystemFederationClockV3;
pub use v3::VerifiedFederationAuthorityReceiptV3;

/// Compatibility V2 entrypoint with corrected completeness and lifetime
/// semantics. V3 is the authenticated, post-I/O-revalidated production path.
pub fn execute_once<T: FederationTransportV2>(
    transport: &T,
    now_unix_ms: u64,
    query: FederatedQueryV2,
    lease: &FederatedLeaseV2,
) -> Result<FederatedResultV2, FederationV2Error> {
    struct CapturingTransport<'a, T> {
        inner: &'a T,
        observed: RefCell<Option<FederationTransportResultV2>>,
    }

    impl<T: FederationTransportV2> FederationTransportV2 for CapturingTransport<'_, T> {
        fn send_once(
            &self,
            query: &FederatedQueryV2,
        ) -> Result<FederationTransportResultV2, FederationV2Error> {
            let result = self.inner.send_once(query)?;
            self.observed.replace(Some(result.clone()));
            Ok(result)
        }
    }

    let deadline_unix_ms = query.deadline_unix_ms;
    let lease_expires_unix_ms = lease.expires_unix_ms;
    let capturing = CapturingTransport {
        inner: transport,
        observed: RefCell::new(None),
    };
    let mut result = v2::execute_once(&capturing, now_unix_ms, query, lease)?;
    let observed = capturing.observed.into_inner();

    if let Some(FederationTransportResultV2::Terminal(response)) = observed
        && matches!(response.completeness, FederatedCompletenessV2::Partial)
        && matches!(result.validity, FederatedValidityV2::Valid)
        && result.items.is_empty()
    {
        result.completeness = FederatedCompletenessV2::Partial;
    }

    result.expires_unix_ms = result
        .expires_unix_ms
        .min(lease_expires_unix_ms)
        .min(deadline_unix_ms);
    result.result_digest = result.compute_result_digest();
    result.validate()?;
    Ok(result)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedReadRequest {
    pub request_id: StableId,
    pub peer_id: StableId,
    pub scope_digest: Digest32,
    pub source_snapshot_digest: Digest32,
    pub request_digest: Digest32,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedReadLease {
    pub lease_id: StableId,
    pub request_id: StableId,
    pub peer_id: StableId,
    pub scope_digest: Digest32,
    pub source_snapshot_digest: Digest32,
    pub request_digest: Digest32,
    pub expires_at_ms: u64,
    pub revoked: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RemoteObservation {
    pub response_digest: Digest32,
    pub terminal_observed: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederatedStatus {
    Succeeded,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedReadReceipt {
    pub request_id: StableId,
    pub lease_id: StableId,
    pub status: FederatedStatus,
    pub response_digest: Option<Digest32>,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    DeadlineExpired,
    LeaseExpired,
    LeaseRevoked,
    IdentityMismatch(&'static str),
    DigestMismatch(&'static str),
    MissingTerminalResponse,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn observe(
    now_ms: u64,
    request: FederatedReadRequest,
    lease: FederatedReadLease,
    observation: Option<RemoteObservation>,
) -> Result<FederatedReadReceipt, Error> {
    for (name, digest) in [
        ("scope", request.scope_digest),
        ("snapshot", request.source_snapshot_digest),
        ("request", request.request_digest),
    ] {
        if digest.is_zero() {
            return Err(Error::EmptyDigest(name));
        }
    }
    if now_ms >= request.deadline_ms {
        return Err(Error::DeadlineExpired);
    }
    if lease.revoked {
        return Err(Error::LeaseRevoked);
    }
    if now_ms >= lease.expires_at_ms {
        return Err(Error::LeaseExpired);
    }
    if lease.request_id != request.request_id {
        return Err(Error::IdentityMismatch("request"));
    }
    if lease.peer_id != request.peer_id {
        return Err(Error::IdentityMismatch("peer"));
    }
    for (name, left, right) in [
        ("scope", lease.scope_digest, request.scope_digest),
        (
            "snapshot",
            lease.source_snapshot_digest,
            request.source_snapshot_digest,
        ),
        ("request", lease.request_digest, request.request_digest),
    ] {
        if left != right {
            return Err(Error::DigestMismatch(name));
        }
    }

    let (status, response_digest) = match observation {
        None => (FederatedStatus::Indeterminate, None),
        Some(value) if !value.terminal_observed => (FederatedStatus::Indeterminate, None),
        Some(value) => {
            if value.response_digest.is_zero() {
                return Err(Error::MissingTerminalResponse);
            }
            (FederatedStatus::Succeeded, Some(value.response_digest))
        }
    };
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.memory.federation.receipt.v1");
    push_id(&mut bytes, &request.request_id);
    push_id(&mut bytes, &lease.lease_id);
    bytes.push(match status {
        FederatedStatus::Succeeded => 0,
        FederatedStatus::Indeterminate => 1,
    });
    if let Some(digest) = response_digest {
        bytes.extend_from_slice(digest.as_array());
    }

    Ok(FederatedReadReceipt {
        request_id: request.request_id,
        lease_id: lease.lease_id,
        status,
        response_digest,
        receipt_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
