//! Authenticated, capability-scoped federated memory reads.
//!
//! V3 keeps the V2 source contract intact while closing the security and
//! composition gaps required for a deployable federation boundary: signed
//! authority receipts, live revocation revalidation, signed remote envelopes,
//! post-I/O clock checks, bounded multi-peer fan-out, explicit cancellation,
//! deterministic aggregation, and revocation-addressable result caching.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use codex_hepta_types::{AuthorityPosture, Digest32, Revision, StableId};
use ed25519_dalek::{Signature, Verifier, VerifyingKey};

pub const MAX_FEDERATION_PEERS_V3: usize = 16;
pub const MAX_FEDERATED_RESULTS_V3: usize = 512;

const QUERY_DOMAIN: &[u8] = b"hepta.memory-federation.query.v3";
const AUTHORITY_DOMAIN: &[u8] = b"hepta.memory-federation.authority.v3";
const REVOCATION_DOMAIN: &[u8] = b"hepta.memory-federation.revocation.v3";
const RESPONSE_DOMAIN: &[u8] = b"hepta.memory-federation.response.v3";
const RESULT_DOMAIN: &[u8] = b"hepta.memory-federation.result.v3";
const AGGREGATE_DOMAIN: &[u8] = b"hepta.memory-federation.aggregate.v3";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedEvidenceItemV3 {
    pub source_owner_id: StableId,
    pub record_id: StableId,
    pub record_revision: Revision,
    pub record_digest: Digest32,
    pub support_digest: Digest32,
    pub validity_digest: Digest32,
}

impl FederatedEvidenceItemV3 {
    fn validate(&self) -> Result<(), FederationV3Error> {
        ensure_digest("record", self.record_digest)?;
        ensure_digest("support", self.support_digest)?;
        ensure_digest("validity", self.validity_digest)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederatedCompletenessV3 {
    Complete,
    Partial,
    Empty,
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederatedValidityV3 {
    Valid,
    StaleGeneration,
    Revoked,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedQueryV3 {
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
    pub request_nonce_digest: Digest32,
}

impl FederatedQueryV3 {
    pub fn validate(&self, now_unix_ms: u64) -> Result<(), FederationV3Error> {
        if now_unix_ms >= self.deadline_unix_ms {
            return Err(FederationV3Error::DeadlineExpired);
        }
        if self.lease_epoch == 0 {
            return Err(FederationV3Error::ZeroValue("lease_epoch"));
        }
        let maximum_results = usize::try_from(self.maximum_results).unwrap_or(usize::MAX);
        if maximum_results == 0 || maximum_results > MAX_FEDERATED_RESULTS_V3 {
            return Err(FederationV3Error::InvalidMaximumResults);
        }
        for (name, digest) in [
            ("scope", self.scope_digest),
            ("purpose", self.purpose_digest),
            ("generation_vector", self.generation_vector_digest),
            ("query", self.query_digest),
            ("request_nonce", self.request_nonce_digest),
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
        push_digest(&mut bytes, self.scope_digest);
        push_digest(&mut bytes, self.purpose_digest);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_digest(&mut bytes, self.query_digest);
        push_u64(&mut bytes, u64::from(self.maximum_results));
        push_u64(&mut bytes, self.deadline_unix_ms);
        push_u64(&mut bytes, self.lease_epoch);
        push_digest(&mut bytes, self.request_nonce_digest);
        Digest32::of_bytes(&bytes)
    }
}

/// Signed representation of the authority lease consumed by federation.
///
/// The signature covers every semantic field below through `proof_digest`.
/// The verifier resolves `issuer_id` + `key_id` from a trust store; callers
/// cannot self-authorize by constructing this value.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CapabilityAuthorityEnvelopeV3 {
    pub issuer_id: StableId,
    pub key_id: StableId,
    pub grant_id: StableId,
    pub lease_id: StableId,
    pub query_id: StableId,
    pub peer_id: StableId,
    pub principal_id: StableId,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub query_binding_digest: Digest32,
    pub lease_epoch: u64,
    pub revocation_epoch: u64,
    pub expires_unix_ms: u64,
    pub proof_digest: Digest32,
    pub signature: [u8; 64],
}

impl CapabilityAuthorityEnvelopeV3 {
    #[must_use]
    pub fn compute_proof_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(AUTHORITY_DOMAIN);
        for id in [
            &self.issuer_id,
            &self.key_id,
            &self.grant_id,
            &self.lease_id,
            &self.query_id,
            &self.peer_id,
            &self.principal_id,
        ] {
            push_id(&mut bytes, id);
        }
        for digest in [
            self.scope_digest,
            self.purpose_digest,
            self.generation_vector_digest,
            self.query_binding_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.lease_epoch);
        push_u64(&mut bytes, self.revocation_epoch);
        push_u64(&mut bytes, self.expires_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CapabilityRevocationObservationV3 {
    pub issuer_id: StableId,
    pub key_id: StableId,
    pub grant_id: StableId,
    pub observed_revocation_epoch: u64,
    pub revoked: bool,
    pub observed_unix_ms: u64,
    pub proof_digest: Digest32,
    pub signature: [u8; 64],
}

impl CapabilityRevocationObservationV3 {
    #[must_use]
    pub fn compute_proof_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(REVOCATION_DOMAIN);
        push_id(&mut bytes, &self.issuer_id);
        push_id(&mut bytes, &self.key_id);
        push_id(&mut bytes, &self.grant_id);
        push_u64(&mut bytes, self.observed_revocation_epoch);
        bytes.push(u8::from(self.revoked));
        push_u64(&mut bytes, self.observed_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

pub trait FederationKeyResolverV3: Send + Sync {
    fn verification_key(
        &self,
        issuer_id: &StableId,
        key_id: &StableId,
    ) -> Option<[u8; 32]>;
}

pub trait CapabilityRevocationSourceV3: Send + Sync {
    fn current_revocation(
        &self,
        grant_id: &StableId,
    ) -> Result<CapabilityRevocationObservationV3, FederationV3Error>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedCapabilityV3 {
    pub issuer_id: StableId,
    pub key_id: StableId,
    pub grant_id: StableId,
    pub lease_id: StableId,
    pub lease_epoch: u64,
    pub revocation_epoch: u64,
    pub expires_unix_ms: u64,
    pub authority_proof_digest: Digest32,
    pub revocation_proof_digest: Digest32,
}

pub trait CapabilityVerifierV3: Send + Sync {
    fn verify_current(
        &self,
        now_unix_ms: u64,
        query: &FederatedQueryV3,
        authority: &CapabilityAuthorityEnvelopeV3,
    ) -> Result<VerifiedCapabilityV3, FederationV3Error>;
}

pub struct SignedCapabilityVerifierV3<'a, K, R> {
    pub keys: &'a K,
    pub revocations: &'a R,
    /// Maximum age of a revocation observation at the instant it is consumed.
    pub max_revocation_age_ms: u64,
}

impl<K, R> CapabilityVerifierV3 for SignedCapabilityVerifierV3<'_, K, R>
where
    K: FederationKeyResolverV3,
    R: CapabilityRevocationSourceV3,
{
    fn verify_current(
        &self,
        now_unix_ms: u64,
        query: &FederatedQueryV3,
        authority: &CapabilityAuthorityEnvelopeV3,
    ) -> Result<VerifiedCapabilityV3, FederationV3Error> {
        query.validate(now_unix_ms)?;
        if now_unix_ms >= authority.expires_unix_ms {
            return Err(FederationV3Error::LeaseExpired);
        }
        if authority.lease_epoch == 0 || authority.lease_epoch != query.lease_epoch {
            return Err(FederationV3Error::LeaseEpochMismatch);
        }
        for (name, left, right) in [
            ("query_id", authority.query_id.as_str(), query.query_id.as_str()),
            ("peer_id", authority.peer_id.as_str(), query.peer_id.as_str()),
            (
                "principal_id",
                authority.principal_id.as_str(),
                query.principal_id.as_str(),
            ),
        ] {
            if left != right {
                return Err(FederationV3Error::IdentityMismatch(name));
            }
        }
        for (name, left, right) in [
            ("scope", authority.scope_digest, query.scope_digest),
            ("purpose", authority.purpose_digest, query.purpose_digest),
            (
                "generation_vector",
                authority.generation_vector_digest,
                query.generation_vector_digest,
            ),
            (
                "query_binding",
                authority.query_binding_digest,
                query.binding_digest(),
            ),
        ] {
            ensure_digest(name, left)?;
            if left != right {
                return Err(FederationV3Error::DigestMismatch(name));
            }
        }
        let authority_digest = authority.compute_proof_digest();
        if authority.proof_digest != authority_digest {
            return Err(FederationV3Error::DigestMismatch("authority_proof"));
        }
        verify_signature(
            self.keys,
            &authority.issuer_id,
            &authority.key_id,
            authority_digest,
            authority.signature,
        )?;

        let revocation = self.revocations.current_revocation(&authority.grant_id)?;
        if revocation.grant_id != authority.grant_id || revocation.issuer_id != authority.issuer_id {
            return Err(FederationV3Error::IdentityMismatch("revocation_grant"));
        }
        let revocation_digest = revocation.compute_proof_digest();
        if revocation.proof_digest != revocation_digest {
            return Err(FederationV3Error::DigestMismatch("revocation_proof"));
        }
        verify_signature(
            self.keys,
            &revocation.issuer_id,
            &revocation.key_id,
            revocation_digest,
            revocation.signature,
        )?;
        if revocation.observed_unix_ms > now_unix_ms
            || now_unix_ms.saturating_sub(revocation.observed_unix_ms) > self.max_revocation_age_ms
        {
            return Err(FederationV3Error::StaleRevocationObservation);
        }
        if revocation.observed_revocation_epoch < authority.revocation_epoch {
            return Err(FederationV3Error::StaleRevocationObservation);
        }
        if revocation.revoked || revocation.observed_revocation_epoch > authority.revocation_epoch {
            return Err(FederationV3Error::LeaseRevoked);
        }

        Ok(VerifiedCapabilityV3 {
            issuer_id: authority.issuer_id.clone(),
            key_id: authority.key_id.clone(),
            grant_id: authority.grant_id.clone(),
            lease_id: authority.lease_id.clone(),
            lease_epoch: authority.lease_epoch,
            revocation_epoch: authority.revocation_epoch,
            expires_unix_ms: authority.expires_unix_ms,
            authority_proof_digest: authority.proof_digest,
            revocation_proof_digest: revocation.proof_digest,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RemoteFederatedResponseV3 {
    pub peer_id: StableId,
    pub principal_id: StableId,
    pub grant_id: StableId,
    pub key_id: StableId,
    pub query_binding_digest: Digest32,
    pub request_nonce_digest: Digest32,
    pub response_nonce_digest: Digest32,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub lease_epoch: u64,
    pub observed_frontier: u64,
    pub expires_unix_ms: u64,
    pub items: Vec<FederatedEvidenceItemV3>,
    pub completeness: FederatedCompletenessV3,
    pub terminal_observed: bool,
    pub payload_digest: Digest32,
    pub signature: [u8; 64],
}

impl RemoteFederatedResponseV3 {
    #[must_use]
    pub fn compute_payload_digest(&self) -> Digest32 {
        let mut items = self.items.iter().collect::<Vec<_>>();
        items.sort_by(|left, right| {
            left.source_owner_id
                .cmp(&right.source_owner_id)
                .then_with(|| left.record_id.cmp(&right.record_id))
                .then_with(|| left.record_revision.cmp(&right.record_revision))
        });
        let mut bytes = Vec::new();
        bytes.extend_from_slice(RESPONSE_DOMAIN);
        for id in [&self.peer_id, &self.principal_id, &self.grant_id, &self.key_id] {
            push_id(&mut bytes, id);
        }
        for digest in [
            self.query_binding_digest,
            self.request_nonce_digest,
            self.response_nonce_digest,
            self.scope_digest,
            self.purpose_digest,
            self.generation_vector_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.lease_epoch);
        push_u64(&mut bytes, self.observed_frontier);
        push_u64(&mut bytes, self.expires_unix_ms);
        push_len(&mut bytes, items.len());
        for item in items {
            push_item(&mut bytes, item);
        }
        bytes.push(completeness_code(self.completeness));
        bytes.push(u8::from(self.terminal_observed));
        Digest32::of_bytes(&bytes)
    }

    fn validate_shape(&self) -> Result<(), FederationV3Error> {
        if !self.terminal_observed {
            return Err(FederationV3Error::MissingTerminalObservation);
        }
        if self.lease_epoch == 0 || self.observed_frontier == 0 || self.expires_unix_ms == 0 {
            return Err(FederationV3Error::ZeroValue("remote_response"));
        }
        for (name, digest) in [
            ("query_binding", self.query_binding_digest),
            ("request_nonce", self.request_nonce_digest),
            ("response_nonce", self.response_nonce_digest),
            ("scope", self.scope_digest),
            ("purpose", self.purpose_digest),
            ("generation_vector", self.generation_vector_digest),
            ("payload", self.payload_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.items.len() > MAX_FEDERATED_RESULTS_V3 {
            return Err(FederationV3Error::ResultLimitExceeded);
        }
        if matches!(self.completeness, FederatedCompletenessV3::Empty) && !self.items.is_empty() {
            return Err(FederationV3Error::InvalidCompleteness);
        }
        if matches!(self.completeness, FederatedCompletenessV3::Indeterminate) {
            return Err(FederationV3Error::InvalidCompleteness);
        }
        let mut identities = BTreeSet::new();
        for item in &self.items {
            item.validate()?;
            if !identities.insert((
                item.source_owner_id.clone(),
                item.record_id.clone(),
                item.record_revision,
            )) {
                return Err(FederationV3Error::DuplicateResultIdentity);
            }
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationTransportOutcomeV3 {
    Unavailable,
    TimedOut,
    Cancelled,
    NoTerminalObservation,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FederationTransportResultV3 {
    Terminal(RemoteFederatedResponseV3),
    NonTerminal(FederationTransportOutcomeV3),
}

#[derive(Clone, Debug, Default)]
pub struct FederationCancellationTokenV3 {
    cancelled: Arc<AtomicBool>,
}

impl FederationCancellationTokenV3 {
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::SeqCst);
    }

    #[must_use]
    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::SeqCst)
    }
}

pub trait FederationClockV3: Send + Sync {
    fn now_unix_ms(&self) -> u64;
}

pub trait FederationTransportV3: Send + Sync {
    /// Transport implementations MUST enforce `deadline_unix_ms` and observe
    /// `cancellation` while I/O is in flight. Returning after either condition
    /// became true is allowed, but the caller will revalidate and discard it.
    fn send_once(
        &self,
        query: &FederatedQueryV3,
        deadline_unix_ms: u64,
        cancellation: &FederationCancellationTokenV3,
    ) -> Result<FederationTransportResultV3, FederationV3Error>;
}

pub type FederationTransportFutureV3<'a> = Pin<
    Box<dyn Future<Output = Result<FederationTransportResultV3, FederationV3Error>> + Send + 'a>,
>;

pub trait AsyncFederationTransportV3: Send + Sync {
    fn send_once_async<'a>(
        &'a self,
        query: &'a FederatedQueryV3,
        deadline_unix_ms: u64,
        cancellation: &'a FederationCancellationTokenV3,
    ) -> FederationTransportFutureV3<'a>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedCoverageV3 {
    pub requested_peers: u32,
    pub completed_peers: u32,
    pub failed_peers: u32,
    pub truncated_items: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedResultV3 {
    pub query_id: StableId,
    pub peer_id: StableId,
    pub grant_id: StableId,
    pub authority_key_id: StableId,
    pub query_binding_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub observed_frontier: Option<u64>,
    pub expires_unix_ms: u64,
    pub items: Vec<FederatedEvidenceItemV3>,
    pub coverage: FederatedCoverageV3,
    pub completeness: FederatedCompletenessV3,
    pub validity: FederatedValidityV3,
    pub remote_payload_digest: Option<Digest32>,
    pub result_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl FederatedResultV3 {
    pub fn validate(&self) -> Result<(), FederationV3Error> {
        ensure_digest("query_binding", self.query_binding_digest)?;
        ensure_digest("generation_vector", self.generation_vector_digest)?;
        if self.expires_unix_ms == 0 {
            return Err(FederationV3Error::ZeroValue("result_expiry"));
        }
        if self.coverage.requested_peers != 1
            || u64::from(self.coverage.completed_peers) + u64::from(self.coverage.failed_peers) != 1
        {
            return Err(FederationV3Error::InvalidCoverage);
        }
        let indeterminate = matches!(self.completeness, FederatedCompletenessV3::Indeterminate);
        if indeterminate != matches!(self.validity, FederatedValidityV3::Indeterminate) {
            return Err(FederationV3Error::InvalidCompleteness);
        }
        if indeterminate
            && (!self.items.is_empty()
                || self.observed_frontier.is_some()
                || self.remote_payload_digest.is_some())
        {
            return Err(FederationV3Error::InvalidCompleteness);
        }
        if matches!(self.validity, FederatedValidityV3::StaleGeneration) && !self.items.is_empty() {
            return Err(FederationV3Error::StaleEvidenceExposed);
        }
        if matches!(self.completeness, FederatedCompletenessV3::Empty) && !self.items.is_empty() {
            return Err(FederationV3Error::InvalidCompleteness);
        }
        if self.authority.grants_any() {
            return Err(FederationV3Error::AuthorityGranted);
        }
        if self.result_digest != self.compute_result_digest() {
            return Err(FederationV3Error::DigestMismatch("result"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_result_digest(&self) -> Digest32 {
        let mut items = self.items.iter().collect::<Vec<_>>();
        items.sort_by(|left, right| {
            left.source_owner_id
                .cmp(&right.source_owner_id)
                .then_with(|| left.record_id.cmp(&right.record_id))
                .then_with(|| left.record_revision.cmp(&right.record_revision))
        });
        let mut bytes = Vec::new();
        bytes.extend_from_slice(RESULT_DOMAIN);
        for id in [
            &self.query_id,
            &self.peer_id,
            &self.grant_id,
            &self.authority_key_id,
        ] {
            push_id(&mut bytes, id);
        }
        push_digest(&mut bytes, self.query_binding_digest);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_optional_u64(&mut bytes, self.observed_frontier);
        push_u64(&mut bytes, self.expires_unix_ms);
        push_len(&mut bytes, items.len());
        for item in items {
            push_item(&mut bytes, item);
        }
        push_u64(&mut bytes, u64::from(self.coverage.requested_peers));
        push_u64(&mut bytes, u64::from(self.coverage.completed_peers));
        push_u64(&mut bytes, u64::from(self.coverage.failed_peers));
        push_u64(&mut bytes, u64::from(self.coverage.truncated_items));
        bytes.push(completeness_code(self.completeness));
        bytes.push(validity_code(self.validity));
        push_optional_digest(&mut bytes, self.remote_payload_digest);
        Digest32::of_bytes(&bytes)
    }
}

pub fn execute_once_v3<T, C, V, K>(
    transport: &T,
    clock: &C,
    capability_verifier: &V,
    peer_keys: &K,
    query: FederatedQueryV3,
    authority: &CapabilityAuthorityEnvelopeV3,
    cancellation: &FederationCancellationTokenV3,
) -> Result<FederatedResultV3, FederationV3Error>
where
    T: FederationTransportV3,
    C: FederationClockV3,
    V: CapabilityVerifierV3,
    K: FederationKeyResolverV3,
{
    let before_send = clock.now_unix_ms();
    query.validate(before_send)?;
    let verified_before = capability_verifier.verify_current(before_send, &query, authority)?;
    if cancellation.is_cancelled() {
        return Ok(indeterminate_result(&query, &verified_before, FederationTransportOutcomeV3::Cancelled));
    }

    let transport_result = transport.send_once(&query, query.deadline_unix_ms, cancellation)?;

    // Fresh time and live revocation are deliberately re-read after I/O. This
    // closes lease/deadline/revocation TOCTOU even if the transport returns late.
    let after_send = clock.now_unix_ms();
    if after_send >= query.deadline_unix_ms {
        return Err(FederationV3Error::DeadlineExpired);
    }
    let verified_after = capability_verifier.verify_current(after_send, &query, authority)?;
    if verified_after.grant_id != verified_before.grant_id
        || verified_after.lease_epoch != verified_before.lease_epoch
        || verified_after.revocation_epoch != verified_before.revocation_epoch
    {
        return Err(FederationV3Error::CapabilityChangedDuringRead);
    }
    if cancellation.is_cancelled() {
        return Ok(indeterminate_result(&query, &verified_after, FederationTransportOutcomeV3::Cancelled));
    }

    let mut result = match transport_result {
        FederationTransportResultV3::NonTerminal(outcome) => {
            indeterminate_result(&query, &verified_after, outcome)
        }
        FederationTransportResultV3::Terminal(response) => {
            response.validate_shape()?;
            validate_remote_binding(&query, &verified_after, &response)?;
            if after_send >= response.expires_unix_ms {
                return Err(FederationV3Error::ResponseExpired);
            }
            let computed_payload = response.compute_payload_digest();
            if response.payload_digest != computed_payload {
                return Err(FederationV3Error::DigestMismatch("remote_payload"));
            }
            verify_signature(
                peer_keys,
                &response.peer_id,
                &response.key_id,
                computed_payload,
                response.signature,
            )?;

            let stale_generation = response.generation_vector_digest != query.generation_vector_digest;
            let maximum_results = usize::try_from(query.maximum_results)
                .unwrap_or(MAX_FEDERATED_RESULTS_V3);
            let remote_item_count = response.items.len();
            let remote_completeness = response.completeness;
            let mut items = if stale_generation { Vec::new() } else { response.items };
            items.truncate(maximum_results);
            let truncated_items = remote_item_count.saturating_sub(items.len());
            let completeness = if stale_generation {
                FederatedCompletenessV3::Partial
            } else if truncated_items > 0 || matches!(remote_completeness, FederatedCompletenessV3::Partial) {
                // Preserve partial even when the peer returned zero items.
                FederatedCompletenessV3::Partial
            } else if items.is_empty() {
                FederatedCompletenessV3::Empty
            } else {
                remote_completeness
            };
            let effective_expiry = response
                .expires_unix_ms
                .min(verified_after.expires_unix_ms)
                .min(query.deadline_unix_ms);
            FederatedResultV3 {
                query_id: query.query_id.clone(),
                peer_id: query.peer_id.clone(),
                grant_id: verified_after.grant_id.clone(),
                authority_key_id: verified_after.key_id.clone(),
                query_binding_digest: query.binding_digest(),
                generation_vector_digest: query.generation_vector_digest,
                observed_frontier: Some(response.observed_frontier),
                expires_unix_ms: effective_expiry,
                items,
                coverage: FederatedCoverageV3 {
                    requested_peers: 1,
                    completed_peers: 1,
                    failed_peers: 0,
                    truncated_items: u32::try_from(truncated_items).unwrap_or(u32::MAX),
                },
                completeness,
                validity: if stale_generation {
                    FederatedValidityV3::StaleGeneration
                } else {
                    FederatedValidityV3::Valid
                },
                remote_payload_digest: Some(response.payload_digest),
                result_digest: Digest32::ZERO,
                authority: AuthorityPosture::DENY_ALL,
            }
        }
    };
    result.result_digest = result.compute_result_digest();
    result.validate()?;
    Ok(result)
}

fn indeterminate_result(
    query: &FederatedQueryV3,
    capability: &VerifiedCapabilityV3,
    _outcome: FederationTransportOutcomeV3,
) -> FederatedResultV3 {
    let mut result = FederatedResultV3 {
        query_id: query.query_id.clone(),
        peer_id: query.peer_id.clone(),
        grant_id: capability.grant_id.clone(),
        authority_key_id: capability.key_id.clone(),
        query_binding_digest: query.binding_digest(),
        generation_vector_digest: query.generation_vector_digest,
        observed_frontier: None,
        expires_unix_ms: query.deadline_unix_ms.min(capability.expires_unix_ms),
        items: Vec::new(),
        coverage: FederatedCoverageV3 {
            requested_peers: 1,
            completed_peers: 0,
            failed_peers: 1,
            truncated_items: 0,
        },
        completeness: FederatedCompletenessV3::Indeterminate,
        validity: FederatedValidityV3::Indeterminate,
        remote_payload_digest: None,
        result_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.result_digest = result.compute_result_digest();
    result
}

fn validate_remote_binding(
    query: &FederatedQueryV3,
    capability: &VerifiedCapabilityV3,
    response: &RemoteFederatedResponseV3,
) -> Result<(), FederationV3Error> {
    if response.peer_id != query.peer_id {
        return Err(FederationV3Error::IdentityMismatch("response_peer"));
    }
    if response.principal_id != query.principal_id {
        return Err(FederationV3Error::IdentityMismatch("response_principal"));
    }
    if response.grant_id != capability.grant_id {
        return Err(FederationV3Error::IdentityMismatch("response_grant"));
    }
    if response.query_binding_digest != query.binding_digest() {
        return Err(FederationV3Error::DigestMismatch("response_query_binding"));
    }
    if response.request_nonce_digest != query.request_nonce_digest {
        return Err(FederationV3Error::DigestMismatch("response_request_nonce"));
    }
    if response.scope_digest != query.scope_digest {
        return Err(FederationV3Error::DigestMismatch("response_scope"));
    }
    if response.purpose_digest != query.purpose_digest {
        return Err(FederationV3Error::DigestMismatch("response_purpose"));
    }
    if response.lease_epoch != capability.lease_epoch {
        return Err(FederationV3Error::LeaseEpochMismatch);
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedAggregateV3 {
    pub results: Vec<FederatedResultV3>,
    pub items: Vec<FederatedEvidenceItemV3>,
    pub coverage: FederatedCoverageV3,
    pub completeness: FederatedCompletenessV3,
    pub expires_unix_ms: u64,
    pub aggregate_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn execute_federation_v3<T, C, V, K>(
    transport: &T,
    clock: &C,
    capability_verifier: &V,
    peer_keys: &K,
    requests: Vec<(FederatedQueryV3, CapabilityAuthorityEnvelopeV3)>,
) -> Result<FederatedAggregateV3, FederationV3Error>
where
    T: FederationTransportV3,
    C: FederationClockV3,
    V: CapabilityVerifierV3,
    K: FederationKeyResolverV3,
{
    if requests.is_empty() || requests.len() > MAX_FEDERATION_PEERS_V3 {
        return Err(FederationV3Error::InvalidPeerCount);
    }
    let requested_peers = u32::try_from(requests.len()).unwrap_or(u32::MAX);
    let mut results = std::thread::scope(|scope| {
        let mut handles = Vec::with_capacity(requests.len());
        for (query, authority) in requests {
            handles.push(scope.spawn(move || {
                let cancellation = FederationCancellationTokenV3::default();
                execute_once_v3(
                    transport,
                    clock,
                    capability_verifier,
                    peer_keys,
                    query,
                    &authority,
                    &cancellation,
                )
            }));
        }
        let mut collected = Vec::new();
        for handle in handles {
            collected.push(handle.join().map_err(|_| FederationV3Error::WorkerPanicked)??);
        }
        Ok::<_, FederationV3Error>(collected)
    })?;

    results.sort_by(|left, right| left.peer_id.cmp(&right.peer_id));
    let completed_peers = results
        .iter()
        .filter(|result| result.coverage.completed_peers == 1)
        .count();
    let failed_peers = results.len().saturating_sub(completed_peers);
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
    let any_indeterminate = results
        .iter()
        .any(|result| matches!(result.completeness, FederatedCompletenessV3::Indeterminate));
    let any_partial = results
        .iter()
        .any(|result| matches!(result.completeness, FederatedCompletenessV3::Partial));
    let all_empty = results
        .iter()
        .all(|result| matches!(result.completeness, FederatedCompletenessV3::Empty));
    let completeness = if any_indeterminate || any_partial || failed_peers > 0 || truncated_items > 0 {
        FederatedCompletenessV3::Partial
    } else if all_empty {
        FederatedCompletenessV3::Empty
    } else {
        FederatedCompletenessV3::Complete
    };
    let expires_unix_ms = results
        .iter()
        .map(|result| result.expires_unix_ms)
        .min()
        .ok_or(FederationV3Error::InvalidPeerCount)?;
    let coverage = FederatedCoverageV3 {
        requested_peers,
        completed_peers: u32::try_from(completed_peers).unwrap_or(u32::MAX),
        failed_peers: u32::try_from(failed_peers).unwrap_or(u32::MAX),
        truncated_items: u32::try_from(truncated_items).unwrap_or(u32::MAX),
    };
    let aggregate_digest = compute_aggregate_digest(&results, &items, &coverage, completeness, expires_unix_ms);
    Ok(FederatedAggregateV3 {
        results,
        items,
        coverage,
        completeness,
        expires_unix_ms,
        aggregate_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn compute_aggregate_digest(
    results: &[FederatedResultV3],
    items: &[FederatedEvidenceItemV3],
    coverage: &FederatedCoverageV3,
    completeness: FederatedCompletenessV3,
    expires_unix_ms: u64,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(AGGREGATE_DOMAIN);
    push_len(&mut bytes, results.len());
    for result in results {
        push_digest(&mut bytes, result.result_digest);
    }
    push_len(&mut bytes, items.len());
    for item in items {
        push_item(&mut bytes, item);
    }
    push_u64(&mut bytes, u64::from(coverage.requested_peers));
    push_u64(&mut bytes, u64::from(coverage.completed_peers));
    push_u64(&mut bytes, u64::from(coverage.failed_peers));
    push_u64(&mut bytes, u64::from(coverage.truncated_items));
    bytes.push(completeness_code(completeness));
    push_u64(&mut bytes, expires_unix_ms);
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedCacheEntryV3 {
    pub cache_id: StableId,
    pub query: FederatedQueryV3,
    pub authority: CapabilityAuthorityEnvelopeV3,
    pub result: FederatedResultV3,
}

#[derive(Debug, Default)]
pub struct FederatedResultCacheV3 {
    entries: BTreeMap<StableId, FederatedCacheEntryV3>,
    by_grant: BTreeMap<StableId, BTreeSet<StableId>>,
    by_key: BTreeMap<StableId, BTreeSet<StableId>>,
    by_peer: BTreeMap<StableId, BTreeSet<StableId>>,
}

impl FederatedResultCacheV3 {
    pub fn insert(&mut self, entry: FederatedCacheEntryV3) -> Result<(), FederationV3Error> {
        if entry.result.expires_unix_ms > entry.authority.expires_unix_ms
            || entry.result.expires_unix_ms > entry.query.deadline_unix_ms
        {
            return Err(FederationV3Error::CacheExpiryExceedsAuthority);
        }
        self.remove(&entry.cache_id);
        index_insert(&mut self.by_grant, &entry.authority.grant_id, &entry.cache_id);
        index_insert(&mut self.by_key, &entry.authority.key_id, &entry.cache_id);
        index_insert(&mut self.by_peer, &entry.query.peer_id, &entry.cache_id);
        self.entries.insert(entry.cache_id.clone(), entry);
        Ok(())
    }

    pub fn get_revalidated<V: CapabilityVerifierV3>(
        &mut self,
        cache_id: &StableId,
        now_unix_ms: u64,
        verifier: &V,
    ) -> Result<Option<FederatedResultV3>, FederationV3Error> {
        let Some(entry) = self.entries.get(cache_id).cloned() else {
            return Ok(None);
        };
        if now_unix_ms >= entry.result.expires_unix_ms {
            self.remove(cache_id);
            return Ok(None);
        }
        if verifier
            .verify_current(now_unix_ms, &entry.query, &entry.authority)
            .is_err()
        {
            self.remove(cache_id);
            return Ok(None);
        }
        Ok(Some(entry.result))
    }

    pub fn purge_grant(&mut self, grant_id: &StableId) -> usize {
        purge_index(&mut self.entries, &mut self.by_grant, grant_id)
    }

    pub fn purge_key(&mut self, key_id: &StableId) -> usize {
        purge_index(&mut self.entries, &mut self.by_key, key_id)
    }

    pub fn purge_peer(&mut self, peer_id: &StableId) -> usize {
        purge_index(&mut self.entries, &mut self.by_peer, peer_id)
    }

    pub fn remove(&mut self, cache_id: &StableId) -> bool {
        let Some(entry) = self.entries.remove(cache_id) else {
            return false;
        };
        index_remove(&mut self.by_grant, &entry.authority.grant_id, cache_id);
        index_remove(&mut self.by_key, &entry.authority.key_id, cache_id);
        index_remove(&mut self.by_peer, &entry.query.peer_id, cache_id);
        true
    }
}

pub trait PeerEnrollmentRegistryV3: Send + Sync {
    fn is_enrolled(&self, peer_id: &StableId) -> bool;
}

/// Product-facing composition boundary. It refuses unenrolled peers, performs
/// live authority verification before and after transport, and optionally caches
/// only authority-bounded results.
pub struct FederationServiceV3<T, C, V, K, P> {
    transport: T,
    clock: C,
    capability_verifier: V,
    peer_keys: K,
    peers: P,
    cache: Mutex<FederatedResultCacheV3>,
}

impl<T, C, V, K, P> FederationServiceV3<T, C, V, K, P>
where
    T: FederationTransportV3,
    C: FederationClockV3,
    V: CapabilityVerifierV3,
    K: FederationKeyResolverV3,
    P: PeerEnrollmentRegistryV3,
{
    pub fn new(transport: T, clock: C, capability_verifier: V, peer_keys: K, peers: P) -> Self {
        Self {
            transport,
            clock,
            capability_verifier,
            peer_keys,
            peers,
            cache: Mutex::new(FederatedResultCacheV3::default()),
        }
    }

    pub fn query_peer(
        &self,
        query: FederatedQueryV3,
        authority: CapabilityAuthorityEnvelopeV3,
        cancellation: &FederationCancellationTokenV3,
    ) -> Result<FederatedResultV3, FederationV3Error> {
        if !self.peers.is_enrolled(&query.peer_id) {
            return Err(FederationV3Error::PeerNotEnrolled);
        }
        execute_once_v3(
            &self.transport,
            &self.clock,
            &self.capability_verifier,
            &self.peer_keys,
            query,
            &authority,
            cancellation,
        )
    }

    pub fn cache_result(
        &self,
        cache_id: StableId,
        query: FederatedQueryV3,
        authority: CapabilityAuthorityEnvelopeV3,
        result: FederatedResultV3,
    ) -> Result<(), FederationV3Error> {
        let mut cache = self.cache.lock().map_err(|_| FederationV3Error::CachePoisoned)?;
        cache.insert(FederatedCacheEntryV3 {
            cache_id,
            query,
            authority,
            result,
        })
    }

    pub fn revalidate_remote(
        &self,
        cache_id: &StableId,
    ) -> Result<Option<FederatedResultV3>, FederationV3Error> {
        let now = self.clock.now_unix_ms();
        let mut cache = self.cache.lock().map_err(|_| FederationV3Error::CachePoisoned)?;
        cache.get_revalidated(cache_id, now, &self.capability_verifier)
    }

    pub fn purge_grant(&self, grant_id: &StableId) -> Result<usize, FederationV3Error> {
        let mut cache = self.cache.lock().map_err(|_| FederationV3Error::CachePoisoned)?;
        Ok(cache.purge_grant(grant_id))
    }

    pub fn purge_key(&self, key_id: &StableId) -> Result<usize, FederationV3Error> {
        let mut cache = self.cache.lock().map_err(|_| FederationV3Error::CachePoisoned)?;
        Ok(cache.purge_key(key_id))
    }

    pub fn purge_peer(&self, peer_id: &StableId) -> Result<usize, FederationV3Error> {
        let mut cache = self.cache.lock().map_err(|_| FederationV3Error::CachePoisoned)?;
        Ok(cache.purge_peer(peer_id))
    }
}

fn verify_signature<K: FederationKeyResolverV3>(
    keys: &K,
    issuer_id: &StableId,
    key_id: &StableId,
    digest: Digest32,
    signature_bytes: [u8; 64],
) -> Result<(), FederationV3Error> {
    let key_bytes = keys
        .verification_key(issuer_id, key_id)
        .ok_or(FederationV3Error::UnknownVerificationKey)?;
    let key = VerifyingKey::from_bytes(&key_bytes)
        .map_err(|_| FederationV3Error::InvalidVerificationKey)?;
    let signature = Signature::from_bytes(&signature_bytes);
    key.verify(digest.as_array(), &signature)
        .map_err(|_| FederationV3Error::InvalidSignature)
}

fn index_insert(
    index: &mut BTreeMap<StableId, BTreeSet<StableId>>,
    key: &StableId,
    cache_id: &StableId,
) {
    index.entry(key.clone()).or_default().insert(cache_id.clone());
}

fn index_remove(
    index: &mut BTreeMap<StableId, BTreeSet<StableId>>,
    key: &StableId,
    cache_id: &StableId,
) {
    if let Some(values) = index.get_mut(key) {
        values.remove(cache_id);
        if values.is_empty() {
            index.remove(key);
        }
    }
}

fn purge_index(
    entries: &mut BTreeMap<StableId, FederatedCacheEntryV3>,
    index: &mut BTreeMap<StableId, BTreeSet<StableId>>,
    key: &StableId,
) -> usize {
    let Some(ids) = index.remove(key) else {
        return 0;
    };
    let mut removed = 0;
    for id in ids {
        if entries.remove(&id).is_some() {
            removed += 1;
        }
    }
    removed
}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), FederationV3Error> {
    if digest.is_zero() {
        return Err(FederationV3Error::EmptyDigest(name));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, digest: Digest32) {
    bytes.extend_from_slice(digest.as_array());
}

fn push_optional_digest(bytes: &mut Vec<u8>, digest: Option<Digest32>) {
    match digest {
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

fn push_item(bytes: &mut Vec<u8>, item: &FederatedEvidenceItemV3) {
    push_id(bytes, &item.source_owner_id);
    push_id(bytes, &item.record_id);
    push_u64(bytes, item.record_revision.get());
    push_digest(bytes, item.record_digest);
    push_digest(bytes, item.support_digest);
    push_digest(bytes, item.validity_digest);
}

const fn completeness_code(value: FederatedCompletenessV3) -> u8 {
    match value {
        FederatedCompletenessV3::Complete => 0,
        FederatedCompletenessV3::Partial => 1,
        FederatedCompletenessV3::Empty => 2,
        FederatedCompletenessV3::Indeterminate => 3,
    }
}

const fn validity_code(value: FederatedValidityV3) -> u8 {
    match value {
        FederatedValidityV3::Valid => 0,
        FederatedValidityV3::StaleGeneration => 1,
        FederatedValidityV3::Revoked => 2,
        FederatedValidityV3::Indeterminate => 3,
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FederationV3Error {
    ZeroValue(&'static str),
    EmptyDigest(&'static str),
    InvalidMaximumResults,
    InvalidPeerCount,
    DeadlineExpired,
    LeaseExpired,
    LeaseRevoked,
    LeaseEpochMismatch,
    StaleRevocationObservation,
    CapabilityChangedDuringRead,
    IdentityMismatch(&'static str),
    DigestMismatch(&'static str),
    MissingTerminalObservation,
    ResponseExpired,
    ResultLimitExceeded,
    DuplicateResultIdentity,
    InvalidCompleteness,
    InvalidCoverage,
    StaleEvidenceExposed,
    AuthorityGranted,
    UnknownVerificationKey,
    InvalidVerificationKey,
    InvalidSignature,
    PeerNotEnrolled,
    CacheExpiryExceedsAuthority,
    CachePoisoned,
    TransportRejected,
    WorkerPanicked,
}

impl fmt::Display for FederationV3Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for FederationV3Error {}

#[cfg(test)]
#[path = "v3_tests.rs"]
mod tests;
