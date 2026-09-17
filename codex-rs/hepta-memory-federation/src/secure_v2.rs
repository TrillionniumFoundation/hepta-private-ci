//! Security-closed V2 execution boundary layered over the original V2 data model.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::time::{SystemTime, UNIX_EPOCH};

use codex_hepta_types::{AuthorityPosture, Digest32, StableId};

use crate::v2::{
    FederatedCompletenessV2, FederatedCoverageV2, FederatedEvidenceItemV2, FederatedLeaseV2,
    FederatedQueryV2, FederatedValidityV2, FederationTransportOutcomeV2, MAX_FEDERATED_RESULTS_V2,
};

const PAYLOAD_DOMAIN: &[u8] = b"hepta.memory-federation.response-payload.v2\0";
const ENVELOPE_DOMAIN: &[u8] = b"hepta.memory-federation.response-envelope.v2\0";
const AUTHORITY_DOMAIN: &[u8] = b"hepta.memory-federation.authority.v2\0";
const RESULT_DOMAIN: &[u8] = b"hepta.memory-federation.verified-result.v2\0";

pub trait FederationClockV2: Send + Sync {
    fn now_unix_ms(&self) -> Result<u64, FederationV2Error>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SystemFederationClockV2;

impl FederationClockV2 for SystemFederationClockV2 {
    fn now_unix_ms(&self) -> Result<u64, FederationV2Error> {
        let elapsed = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| FederationV2Error::Clock)?;
        u64::try_from(elapsed.as_millis()).map_err(|_| FederationV2Error::Clock)
    }
}

/// Fresh authority proof derived from `authority_leaseV1` plus
/// `capability_revocationV1`. The verifier, not `FederatedLeaseV2::revoked`, is
/// the trust source for revocation state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedFederationAuthorityV2 {
    pub issuer_id: StableId,
    pub key_id: StableId,
    pub grant_id: StableId,
    pub lease_id: StableId,
    pub peer_id: StableId,
    pub principal_id: StableId,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub lease_epoch: u64,
    pub revocation_epoch: u64,
    pub observed_at_unix_ms: u64,
    pub revocation_fresh_until_unix_ms: u64,
    pub expires_unix_ms: u64,
    pub proof_digest: Digest32,
}

impl VerifiedFederationAuthorityV2 {
    fn validate(
        &self,
        now_unix_ms: u64,
        query: &FederatedQueryV2,
        lease: &FederatedLeaseV2,
    ) -> Result<(), FederationV2Error> {
        if self.lease_epoch == 0 || self.revocation_epoch == 0 {
            return Err(FederationV2Error::AuthorityRejected);
        }
        if self.observed_at_unix_ms > now_unix_ms
            || self.expires_unix_ms != lease.expires_unix_ms
            || self.revocation_fresh_until_unix_ms > self.expires_unix_ms
        {
            return Err(FederationV2Error::AuthorityRejected);
        }
        if now_unix_ms >= self.expires_unix_ms {
            return Err(FederationV2Error::LeaseExpired);
        }
        if now_unix_ms >= self.revocation_fresh_until_unix_ms {
            return Err(FederationV2Error::AuthorityStale);
        }
        ensure_digest("authority_proof", self.proof_digest)?;
        for (name, left, right) in [
            ("lease", self.lease_id.as_str(), lease.lease_id.as_str()),
            ("peer", self.peer_id.as_str(), query.peer_id.as_str()),
            ("principal", self.principal_id.as_str(), query.principal_id.as_str()),
        ] {
            if left != right {
                return Err(FederationV2Error::IdentityMismatch(name));
            }
        }
        if self.lease_epoch != query.lease_epoch
            || self.scope_digest != query.scope_digest
            || self.purpose_digest != query.purpose_digest
        {
            return Err(FederationV2Error::AuthorityRejected);
        }
        Ok(())
    }

    #[must_use]
    pub fn verification_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(AUTHORITY_DOMAIN);
        for id in [
            &self.issuer_id,
            &self.key_id,
            &self.grant_id,
            &self.lease_id,
            &self.peer_id,
            &self.principal_id,
        ] {
            push_id(&mut bytes, id);
        }
        for digest in [self.scope_digest, self.purpose_digest, self.proof_digest] {
            push_digest(&mut bytes, digest);
        }
        for value in [
            self.lease_epoch,
            self.revocation_epoch,
            self.observed_at_unix_ms,
            self.revocation_fresh_until_unix_ms,
            self.expires_unix_ms,
        ] {
            push_u64(&mut bytes, value);
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Mandatory host boundary for canonical lease and revocation verification.
pub trait FederationAuthorityVerifierV2: Send + Sync {
    fn verify(
        &self,
        query: &FederatedQueryV2,
        lease: &FederatedLeaseV2,
        now_unix_ms: u64,
    ) -> Result<VerifiedFederationAuthorityV2, FederationV2Error>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RemoteFederatedResponseV2 {
    pub peer_id: StableId,
    pub signer_key_id: StableId,
    pub query_binding_digest: Digest32,
    pub request_nonce_digest: Digest32,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub grant_id: StableId,
    pub lease_id: StableId,
    pub lease_epoch: u64,
    pub response_nonce_digest: Digest32,
    pub payload_digest: Digest32,
    pub observed_frontier: u64,
    pub expires_unix_ms: u64,
    pub items: Vec<FederatedEvidenceItemV2>,
    pub completeness: FederatedCompletenessV2,
    pub terminal_observed: bool,
    pub signature: Vec<u8>,
}

impl RemoteFederatedResponseV2 {
    fn validate_shape(&self) -> Result<(), FederationV2Error> {
        if !self.terminal_observed {
            return Err(FederationV2Error::MissingTerminalObservation);
        }
        if self.lease_epoch == 0 || self.observed_frontier == 0 || self.expires_unix_ms == 0 {
            return Err(FederationV2Error::ZeroValue("response_fence"));
        }
        if self.signature.is_empty() || self.signature.len() > 1_024 {
            return Err(FederationV2Error::InvalidSignature);
        }
        if self.items.len() > MAX_FEDERATED_RESULTS_V2 {
            return Err(FederationV2Error::ResultLimitExceeded);
        }
        if self.completeness == FederatedCompletenessV2::Indeterminate
            || (self.completeness == FederatedCompletenessV2::Empty && !self.items.is_empty())
            || (self.completeness == FederatedCompletenessV2::Complete && self.items.is_empty())
        {
            return Err(FederationV2Error::InvalidCompleteness);
        }
        let mut identities = BTreeSet::new();
        for item in &self.items {
            for (name, digest) in [
                ("record", item.record_digest),
                ("support", item.support_digest),
                ("validity", item.validity_digest),
            ] {
                ensure_digest(name, digest)?;
            }
            if !identities.insert((
                item.source_owner_id.clone(),
                item.record_id.clone(),
                item.record_revision,
            )) {
                return Err(FederationV2Error::DuplicateResultIdentity);
            }
        }
        Ok(())
    }

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
        bytes.extend_from_slice(PAYLOAD_DOMAIN);
        push_id(&mut bytes, &self.peer_id);
        for digest in [
            self.scope_digest,
            self.purpose_digest,
            self.generation_vector_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.observed_frontier);
        push_u64(&mut bytes, self.expires_unix_ms);
        push_u64(&mut bytes, u64::try_from(items.len()).unwrap_or(u64::MAX));
        for item in items {
            push_item(&mut bytes, item);
        }
        bytes.push(completeness_code(self.completeness));
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn signing_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ENVELOPE_DOMAIN);
        push_id(&mut bytes, &self.peer_id);
        push_id(&mut bytes, &self.signer_key_id);
        for digest in [
            self.query_binding_digest,
            self.request_nonce_digest,
            self.response_nonce_digest,
            self.payload_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_id(&mut bytes, &self.grant_id);
        push_id(&mut bytes, &self.lease_id);
        push_u64(&mut bytes, self.lease_epoch);
        push_u64(&mut bytes, self.expires_unix_ms);
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn envelope_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        push_digest(&mut bytes, self.signing_digest());
        push_u64(&mut bytes, u64::try_from(self.signature.len()).unwrap_or(u64::MAX));
        bytes.extend_from_slice(&self.signature);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PeerAuthenticationReceiptV2 {
    pub peer_id: StableId,
    pub key_id: StableId,
    pub signing_digest: Digest32,
    pub proof_digest: Digest32,
}

/// Mandatory peer boundary. Implementations must resolve only enrolled peers
/// and cryptographically verify the signature over `signing_digest()`.
pub trait FederationPeerSignatureVerifierV2: Send + Sync {
    fn verify(
        &self,
        response: &RemoteFederatedResponseV2,
    ) -> Result<PeerAuthenticationReceiptV2, FederationV2Error>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FederationTransportResultV2 {
    Terminal(RemoteFederatedResponseV2),
    NonTerminal(FederationTransportOutcomeV2),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationTransportRequestV2 {
    pub query: FederatedQueryV2,
    pub grant_id: StableId,
    pub lease_id: StableId,
    pub authority_verification_digest: Digest32,
}

/// One attempt only. Retry remains an explicitly authorized caller decision.
pub trait FederationTransportV2: Send + Sync {
    fn send_once(
        &self,
        request: &FederationTransportRequestV2,
    ) -> Result<FederationTransportResultV2, FederationV2Error>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedResultV2 {
    pub query_id: StableId,
    pub peer_id: StableId,
    pub grant_id: StableId,
    pub lease_id: StableId,
    pub query_binding_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub observed_frontier: Option<u64>,
    pub expires_unix_ms: u64,
    pub revocation_epoch: u64,
    pub items: Vec<FederatedEvidenceItemV2>,
    pub coverage: FederatedCoverageV2,
    pub completeness: FederatedCompletenessV2,
    pub validity: FederatedValidityV2,
    pub authority_verification_digest: Digest32,
    pub peer_authentication_digest: Option<Digest32>,
    pub remote_response_digest: Option<Digest32>,
    pub result_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl FederatedResultV2 {
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
        for id in [&self.query_id, &self.peer_id, &self.grant_id, &self.lease_id] {
            push_id(&mut bytes, id);
        }
        for digest in [self.query_binding_digest, self.generation_vector_digest] {
            push_digest(&mut bytes, digest);
        }
        push_optional_u64(&mut bytes, self.observed_frontier);
        push_u64(&mut bytes, self.expires_unix_ms);
        push_u64(&mut bytes, self.revocation_epoch);
        push_u64(&mut bytes, u64::try_from(items.len()).unwrap_or(u64::MAX));
        for item in items {
            push_item(&mut bytes, item);
        }
        for value in [
            self.coverage.requested_peers,
            self.coverage.completed_peers,
            self.coverage.failed_peers,
            self.coverage.truncated_items,
        ] {
            push_u64(&mut bytes, u64::from(value));
        }
        bytes.push(completeness_code(self.completeness));
        bytes.push(validity_code(self.validity));
        push_digest(&mut bytes, self.authority_verification_digest);
        push_optional_digest(&mut bytes, self.peer_authentication_digest);
        push_optional_digest(&mut bytes, self.remote_response_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FederationV2Error {
    Legacy(crate::v2::FederationV2Error),
    ZeroValue(&'static str),
    EmptyDigest(&'static str),
    LeaseExpired,
    LeaseEpochMismatch,
    AuthorityRejected,
    AuthorityRevoked,
    AuthorityStale,
    AuthorityChangedDuringRead,
    IdentityMismatch(&'static str),
    DigestMismatch(&'static str),
    MissingTerminalObservation,
    ResponseExpired,
    ResultLimitExceeded,
    DuplicateResultIdentity,
    InvalidCompleteness,
    InvalidSignature,
    PeerNotEnrolled,
    TransportRejected,
    Clock,
}

impl fmt::Display for FederationV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for FederationV2Error {}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), FederationV2Error> {
    if digest.is_zero() {
        Err(FederationV2Error::EmptyDigest(name))
    } else {
        Ok(())
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_u64(bytes, u64::try_from(value.as_str().len()).unwrap_or(u64::MAX));
    bytes.extend_from_slice(value.as_str().as_bytes());
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}
fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
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

fn push_optional_u64(bytes: &mut Vec<u8>, value: Option<u64>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_u64(bytes, value);
        }
        None => bytes.push(0),
    }
}

fn push_item(bytes: &mut Vec<u8>, item: &FederatedEvidenceItemV2) {
    push_id(bytes, &item.source_owner_id);
    push_id(bytes, &item.record_id);
    push_u64(bytes, item.record_revision.get());
    for digest in [item.record_digest, item.support_digest, item.validity_digest] {
        push_digest(bytes, digest);
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

#[path = "secure_v2_execute.rs"]
mod execute;

pub use execute::execute_once;

#[cfg(test)]
#[path = "secure_v2_tests.rs"]
mod tests;
