use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{AuthorityPosture, Digest32, Revision, StableId};

pub const MAX_FEDERATED_RESULTS_V2: usize = 512;
pub const MAX_FEDERATED_PEERS_V2: usize = 16;
pub const MAX_FEDERATION_CONCURRENCY_V2: usize = 16;

pub(crate) const QUERY_DOMAIN: &[u8] = b"hepta.memory-federation.query.v2";
pub(crate) const RESULT_DOMAIN: &[u8] = b"hepta.memory-federation.result.v2";
pub(crate) const BATCH_DOMAIN: &[u8] = b"hepta.memory-federation.batch.v2";
pub(crate) const CANCELLATION_DOMAIN: &[u8] = b"hepta.memory-federation.cancellation.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedQueryV2 {
    pub query_id: StableId,
    pub peer_id: StableId,
    pub principal_id: StableId,
    pub grant_id: StableId,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub query_digest: Digest32,
    pub maximum_results: u32,
    pub deadline_unix_ms: u64,
    pub grant_epoch: u64,
    pub lease_epoch: u64,
    pub nonce_digest: Digest32,
}

impl FederatedQueryV2 {
    pub fn validate(&self, now_unix_ms: u64) -> Result<(), FederationV2Error> {
        if now_unix_ms >= self.deadline_unix_ms {
            return Err(FederationV2Error::DeadlineExpired);
        }
        require_nonzero("grant_epoch", self.grant_epoch)?;
        require_nonzero("lease_epoch", self.lease_epoch)?;
        let maximum = usize::try_from(self.maximum_results).unwrap_or(usize::MAX);
        if maximum == 0 || maximum > MAX_FEDERATED_RESULTS_V2 {
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
        let mut bytes = Vec::with_capacity(640);
        bytes.extend_from_slice(QUERY_DOMAIN);
        for value in [&self.query_id, &self.peer_id, &self.principal_id, &self.grant_id] {
            push_id(&mut bytes, value);
        }
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
        push_u64(&mut bytes, self.grant_epoch);
        push_u64(&mut bytes, self.lease_epoch);
        push_digest(&mut bytes, self.nonce_digest);
        Digest32::of_bytes(&bytes)
    }
}

/// Untrusted claims supplied by the product host. Only an authority adapter can
/// convert these claims into `VerifiedCapabilityReceiptV2`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedLeaseV2 {
    pub lease_id: StableId,
    pub grant_id: StableId,
    pub issuer_id: StableId,
    pub issuer_key_id: StableId,
    pub query_id: StableId,
    pub peer_id: StableId,
    pub principal_id: StableId,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub query_binding_digest: Digest32,
    pub grant_epoch: u64,
    pub lease_epoch: u64,
    pub expires_unix_ms: u64,
    pub authority_proof_digest: Digest32,
}

impl FederatedLeaseV2 {
    pub fn validate_claims_for_query(
        &self,
        now_unix_ms: u64,
        query: &FederatedQueryV2,
    ) -> Result<(), FederationV2Error> {
        if now_unix_ms >= self.expires_unix_ms {
            return Err(FederationV2Error::LeaseExpired);
        }
        if self.grant_epoch == 0 || self.grant_epoch != query.grant_epoch {
            return Err(FederationV2Error::GrantEpochMismatch);
        }
        if self.lease_epoch == 0 || self.lease_epoch != query.lease_epoch {
            return Err(FederationV2Error::LeaseEpochMismatch);
        }
        for (name, left, right) in [
            ("query_id", self.query_id.as_str(), query.query_id.as_str()),
            ("peer_id", self.peer_id.as_str(), query.peer_id.as_str()),
            ("principal_id", self.principal_id.as_str(), query.principal_id.as_str()),
            ("grant_id", self.grant_id.as_str(), query.grant_id.as_str()),
        ] {
            if left != right {
                return Err(FederationV2Error::IdentityMismatch(name));
            }
        }
        for (name, left, right) in [
            ("scope", self.scope_digest, query.scope_digest),
            ("purpose", self.purpose_digest, query.purpose_digest),
            ("generation_vector", self.generation_vector_digest, query.generation_vector_digest),
            ("query_binding", self.query_binding_digest, query.binding_digest()),
        ] {
            ensure_digest(name, left)?;
            if left != right {
                return Err(FederationV2Error::DigestMismatch(name));
            }
        }
        ensure_digest("authority_proof", self.authority_proof_digest)
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
    pub(crate) fn validate(&self) -> Result<(), FederationV2Error> {
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
pub struct FederatedCoverageV2 {
    pub requested_peers: u32,
    pub completed_peers: u32,
    pub failed_peers: u32,
    pub truncated_items: u32,
}

impl FederatedCoverageV2 {
    pub(crate) fn validate(&self) -> Result<(), FederationV2Error> {
        if self.requested_peers == 0
            || self.completed_peers > self.requested_peers
            || self.failed_peers > self.requested_peers
            || self.completed_peers.saturating_add(self.failed_peers) > self.requested_peers
        {
            return Err(FederationV2Error::InvalidCoverage);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedResultV2 {
    pub query_id: StableId,
    pub peer_id: StableId,
    pub grant_id: StableId,
    pub lease_id: StableId,
    pub query_binding_digest: Digest32,
    pub capability_receipt_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub observed_frontier: Option<u64>,
    pub expires_unix_ms: u64,
    pub items: Vec<FederatedEvidenceItemV2>,
    pub coverage: FederatedCoverageV2,
    pub completeness: FederatedCompletenessV2,
    pub validity: FederatedValidityV2,
    pub remote_response_digest: Option<Digest32>,
    pub response_nonce_digest: Option<Digest32>,
    pub result_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl FederatedResultV2 {
    pub fn validate(&self) -> Result<(), FederationV2Error> {
        ensure_digest("query_binding", self.query_binding_digest)?;
        ensure_digest("capability_receipt", self.capability_receipt_digest)?;
        ensure_digest("generation_vector", self.generation_vector_digest)?;
        require_nonzero("result_expiry", self.expires_unix_ms)?;
        self.coverage.validate()?;
        if self.coverage.requested_peers != 1 {
            return Err(FederationV2Error::InvalidCoverage);
        }
        if self.items.len() > MAX_FEDERATED_RESULTS_V2 {
            return Err(FederationV2Error::ResultLimitExceeded);
        }
        if matches!(self.completeness, FederatedCompletenessV2::Complete) && self.items.is_empty() {
            return Err(FederationV2Error::InvalidCompleteness);
        }
        if matches!(self.completeness, FederatedCompletenessV2::Empty) && !self.items.is_empty() {
            return Err(FederationV2Error::InvalidCompleteness);
        }
        let indeterminate = matches!(self.completeness, FederatedCompletenessV2::Indeterminate);
        if indeterminate != matches!(self.validity, FederatedValidityV2::Indeterminate) {
            return Err(FederationV2Error::InvalidCompleteness);
        }
        if indeterminate
            && (!self.items.is_empty()
                || self.observed_frontier.is_some()
                || self.remote_response_digest.is_some()
                || self.response_nonce_digest.is_some())
        {
            return Err(FederationV2Error::InvalidCompleteness);
        }
        if matches!(self.validity, FederatedValidityV2::StaleGeneration | FederatedValidityV2::Revoked)
            && !self.items.is_empty()
        {
            return Err(FederationV2Error::StaleEvidenceExposed);
        }
        ensure_unique_items(&self.items)?;
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
        let mut items = self.items.iter().collect::<Vec<_>>();
        items.sort_by_key(|item| evidence_identity(item));
        let mut bytes = Vec::with_capacity(1024);
        bytes.extend_from_slice(RESULT_DOMAIN);
        for value in [&self.query_id, &self.peer_id, &self.grant_id, &self.lease_id] {
            push_id(&mut bytes, value);
        }
        for digest in [
            self.query_binding_digest,
            self.capability_receipt_digest,
            self.generation_vector_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_optional_u64(&mut bytes, self.observed_frontier);
        push_u64(&mut bytes, self.expires_unix_ms);
        push_len(&mut bytes, items.len());
        for item in items {
            push_evidence_item(&mut bytes, item);
        }
        push_coverage(&mut bytes, &self.coverage);
        bytes.push(completeness_code(self.completeness));
        bytes.push(validity_code(self.validity));
        push_optional_digest(&mut bytes, self.remote_response_digest);
        push_optional_digest(&mut bytes, self.response_nonce_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationAttemptV2 {
    pub query: FederatedQueryV2,
    pub lease: FederatedLeaseV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationPeerFailureV2 {
    pub peer_id: StableId,
    pub query_id: StableId,
    pub error: FederationV2Error,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedBatchResultV2 {
    pub results: Vec<FederatedResultV2>,
    pub failures: Vec<FederationPeerFailureV2>,
    pub items: Vec<FederatedEvidenceItemV2>,
    pub coverage: FederatedCoverageV2,
    pub completeness: FederatedCompletenessV2,
    pub result_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl FederatedBatchResultV2 {
    pub fn validate(&self) -> Result<(), FederationV2Error> {
        self.coverage.validate()?;
        let requested = usize::try_from(self.coverage.requested_peers).unwrap_or(usize::MAX);
        if requested > MAX_FEDERATED_PEERS_V2 || requested != self.results.len() + self.failures.len() {
            return Err(FederationV2Error::InvalidPeerCount);
        }
        if self.coverage.completed_peers.saturating_add(self.coverage.failed_peers)
            != self.coverage.requested_peers
        {
            return Err(FederationV2Error::InvalidCoverage);
        }
        if self.items.len() > MAX_FEDERATED_RESULTS_V2 {
            return Err(FederationV2Error::ResultLimitExceeded);
        }
        if matches!(self.completeness, FederatedCompletenessV2::Complete)
            && (self.items.is_empty() || self.coverage.failed_peers != 0 || self.coverage.truncated_items != 0)
        {
            return Err(FederationV2Error::InvalidCompleteness);
        }
        if matches!(self.completeness, FederatedCompletenessV2::Empty)
            && (!self.items.is_empty() || self.coverage.failed_peers != 0)
        {
            return Err(FederationV2Error::InvalidCompleteness);
        }
        if matches!(self.completeness, FederatedCompletenessV2::Indeterminate)
            && self.coverage.completed_peers != 0
        {
            return Err(FederationV2Error::InvalidCompleteness);
        }
        ensure_unique_items(&self.items)?;
        if self.authority.grants_any() {
            return Err(FederationV2Error::AuthorityGranted);
        }
        if self.result_digest != self.compute_result_digest() {
            return Err(FederationV2Error::DigestMismatch("batch_result"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_result_digest(&self) -> Digest32 {
        let mut bytes = Vec::with_capacity(1024);
        bytes.extend_from_slice(BATCH_DOMAIN);
        let mut results = self.results.iter().collect::<Vec<_>>();
        results.sort_by(|a, b| a.peer_id.cmp(&b.peer_id).then_with(|| a.query_id.cmp(&b.query_id)));
        push_len(&mut bytes, results.len());
        for result in results {
            push_digest(&mut bytes, result.result_digest);
        }
        let mut failures = self.failures.iter().collect::<Vec<_>>();
        failures.sort_by(|a, b| a.peer_id.cmp(&b.peer_id).then_with(|| a.query_id.cmp(&b.query_id)));
        push_len(&mut bytes, failures.len());
        for failure in failures {
            push_id(&mut bytes, &failure.peer_id);
            push_id(&mut bytes, &failure.query_id);
            push_bytes(&mut bytes, format!("{:?}", failure.error).as_bytes());
        }
        let mut items = self.items.iter().collect::<Vec<_>>();
        items.sort_by_key(|item| evidence_identity(item));
        push_len(&mut bytes, items.len());
        for item in items {
            push_evidence_item(&mut bytes, item);
        }
        push_coverage(&mut bytes, &self.coverage);
        bytes.push(completeness_code(self.completeness));
        Digest32::of_bytes(&bytes)
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
    require_nonzero("lease_epoch", request.lease_epoch)?;
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
    InvalidPeerCount,
    InvalidConcurrencyLimit,
    DeadlineExpired,
    LeaseExpired,
    LeaseRevoked,
    GrantEpochMismatch,
    LeaseEpochMismatch,
    RevocationEpochRegressed,
    IdentityMismatch(&'static str),
    CapabilityReceiptMismatch(&'static str),
    DigestMismatch(&'static str),
    MissingTerminalObservation,
    ResponseExpired,
    ResultExpired,
    ResultLimitExceeded,
    DuplicateResultIdentity,
    ConflictingResultIdentity,
    DuplicatePeerIdentity,
    PeerNotEnrolled,
    PeerDisabled,
    PeerKeyEpochMismatch,
    InvalidPeerSignature,
    InvalidCompleteness,
    InvalidCoverage,
    StaleEvidenceExposed,
    AuthorityGranted,
    AuthorityRejected,
    TransportRejected,
    Cancelled,
    ClockUnavailable,
    CachePoisoned,
    CacheMiss,
    InvalidCacheEntry,
}

impl fmt::Display for FederationV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for FederationV2Error {}

pub(crate) fn normalize_completeness(
    stale_generation: bool,
    remote: FederatedCompletenessV2,
    items_empty: bool,
    truncated_items: usize,
) -> FederatedCompletenessV2 {
    if stale_generation || truncated_items > 0 || matches!(remote, FederatedCompletenessV2::Partial) {
        return FederatedCompletenessV2::Partial;
    }
    if items_empty {
        FederatedCompletenessV2::Empty
    } else {
        remote
    }
}

pub(crate) fn ensure_unique_items(items: &[FederatedEvidenceItemV2]) -> Result<(), FederationV2Error> {
    let mut identities = BTreeSet::new();
    for item in items {
        item.validate()?;
        if !identities.insert(evidence_identity(item)) {
            return Err(FederationV2Error::DuplicateResultIdentity);
        }
    }
    Ok(())
}

pub(crate) fn evidence_identity(item: &FederatedEvidenceItemV2) -> (StableId, StableId, Revision) {
    (item.source_owner_id.clone(), item.record_id.clone(), item.record_revision)
}

pub(crate) fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), FederationV2Error> {
    if digest.is_zero() {
        return Err(FederationV2Error::EmptyDigest(name));
    }
    Ok(())
}

pub(crate) fn require_nonzero(name: &'static str, value: u64) -> Result<(), FederationV2Error> {
    if value == 0 {
        return Err(FederationV2Error::ZeroValue(name));
    }
    Ok(())
}

pub(crate) fn push_evidence_item(bytes: &mut Vec<u8>, item: &FederatedEvidenceItemV2) {
    push_id(bytes, &item.source_owner_id);
    push_id(bytes, &item.record_id);
    push_u64(bytes, item.record_revision.get());
    push_digest(bytes, item.record_digest);
    push_digest(bytes, item.support_digest);
    push_digest(bytes, item.validity_digest);
}

pub(crate) fn push_coverage(bytes: &mut Vec<u8>, coverage: &FederatedCoverageV2) {
    push_u64(bytes, u64::from(coverage.requested_peers));
    push_u64(bytes, u64::from(coverage.completed_peers));
    push_u64(bytes, u64::from(coverage.failed_peers));
    push_u64(bytes, u64::from(coverage.truncated_items));
}

pub(crate) fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_bytes(bytes, value.as_str().as_bytes());
}

pub(crate) fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) {
    push_len(bytes, value.len());
    bytes.extend_from_slice(value);
}

pub(crate) fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

pub(crate) fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_digest(bytes, value);
        }
        None => bytes.push(0),
    }
}

pub(crate) fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
}

pub(crate) fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

pub(crate) fn push_optional_u64(bytes: &mut Vec<u8>, value: Option<u64>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_u64(bytes, value);
        }
        None => bytes.push(0),
    }
}

pub(crate) const fn completeness_code(value: FederatedCompletenessV2) -> u8 {
    match value {
        FederatedCompletenessV2::Complete => 0,
        FederatedCompletenessV2::Partial => 1,
        FederatedCompletenessV2::Empty => 2,
        FederatedCompletenessV2::Indeterminate => 3,
    }
}

pub(crate) const fn validity_code(value: FederatedValidityV2) -> u8 {
    match value {
        FederatedValidityV2::Valid => 0,
        FederatedValidityV2::StaleGeneration => 1,
        FederatedValidityV2::Revoked => 2,
        FederatedValidityV2::Indeterminate => 3,
    }
}
