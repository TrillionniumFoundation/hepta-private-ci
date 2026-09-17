use std::collections::BTreeSet;

use codex_hepta_types::{Digest32, StableId};
use ed25519_dalek::{Signature, VerifyingKey};

use super::authority::{PeerTrustV2, VerifiedCapabilityReceiptV2};
use super::model::{
    FederatedCompletenessV2, FederatedEvidenceItemV2, FederatedLeaseV2, FederatedQueryV2,
    FederationV2Error, MAX_FEDERATED_RESULTS_V2, completeness_code, ensure_digest,
    evidence_identity, push_digest, push_evidence_item, push_id, push_len, push_u64,
    require_nonzero,
};

const RESPONSE_PAYLOAD_DOMAIN: &[u8] = b"hepta.memory-federation.response-payload.v2";
const RESPONSE_DOMAIN: &[u8] = b"hepta.memory-federation.response.v2";
const RESPONSE_SIGNATURE_DOMAIN: &[u8] = b"hepta.memory-federation.response-signature.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RemoteFederatedResponseV2 {
    pub peer_id: StableId,
    pub peer_key_id: StableId,
    pub peer_key_epoch: u64,
    pub query_binding_digest: Digest32,
    pub request_nonce_digest: Digest32,
    pub grant_id: StableId,
    pub lease_id: StableId,
    pub grant_epoch: u64,
    pub lease_epoch: u64,
    pub revocation_epoch: u64,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub response_nonce_digest: Digest32,
    pub payload_digest: Digest32,
    pub response_digest: Digest32,
    pub observed_frontier: u64,
    pub expires_unix_ms: u64,
    pub items: Vec<FederatedEvidenceItemV2>,
    pub completeness: FederatedCompletenessV2,
    pub terminal_observed: bool,
    pub signature: [u8; 64],
}

impl RemoteFederatedResponseV2 {
    #[must_use]
    pub fn compute_payload_digest(&self) -> Digest32 {
        let mut items = self.items.iter().collect::<Vec<_>>();
        items.sort_by_key(|item| evidence_identity(item));
        let mut bytes = Vec::with_capacity(1024);
        bytes.extend_from_slice(RESPONSE_PAYLOAD_DOMAIN);
        push_u64(&mut bytes, self.observed_frontier);
        push_u64(&mut bytes, self.expires_unix_ms);
        bytes.push(completeness_code(self.completeness));
        bytes.push(u8::from(self.terminal_observed));
        push_len(&mut bytes, items.len());
        for item in items {
            push_evidence_item(&mut bytes, item);
        }
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn compute_response_digest(&self) -> Digest32 {
        let mut bytes = Vec::with_capacity(1024);
        bytes.extend_from_slice(RESPONSE_DOMAIN);
        for value in [&self.peer_id, &self.peer_key_id, &self.grant_id, &self.lease_id] {
            push_id(&mut bytes, value);
        }
        push_u64(&mut bytes, self.peer_key_epoch);
        for digest in [
            self.query_binding_digest,
            self.request_nonce_digest,
            self.scope_digest,
            self.purpose_digest,
            self.generation_vector_digest,
            self.response_nonce_digest,
            self.payload_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.grant_epoch);
        push_u64(&mut bytes, self.lease_epoch);
        push_u64(&mut bytes, self.revocation_epoch);
        push_u64(&mut bytes, self.observed_frontier);
        push_u64(&mut bytes, self.expires_unix_ms);
        bytes.push(completeness_code(self.completeness));
        bytes.push(u8::from(self.terminal_observed));
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(96);
        bytes.extend_from_slice(RESPONSE_SIGNATURE_DOMAIN);
        push_digest(&mut bytes, self.response_digest);
        bytes
    }

    fn validate_shape(&self) -> Result<(), FederationV2Error> {
        if !self.terminal_observed {
            return Err(FederationV2Error::MissingTerminalObservation);
        }
        require_nonzero("peer_key_epoch", self.peer_key_epoch)?;
        require_nonzero("response_grant_epoch", self.grant_epoch)?;
        require_nonzero("response_lease_epoch", self.lease_epoch)?;
        require_nonzero("response_revocation_epoch", self.revocation_epoch)?;
        require_nonzero("observed_frontier", self.observed_frontier)?;
        require_nonzero("response_expiry", self.expires_unix_ms)?;
        for (name, digest) in [
            ("response_query_binding", self.query_binding_digest),
            ("response_request_nonce", self.request_nonce_digest),
            ("response_scope", self.scope_digest),
            ("response_purpose", self.purpose_digest),
            ("response_generation_vector", self.generation_vector_digest),
            ("response_nonce", self.response_nonce_digest),
            ("payload", self.payload_digest),
            ("response", self.response_digest),
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
        let mut identities = BTreeSet::new();
        for item in &self.items {
            item.validate()?;
            if !identities.insert(evidence_identity(item)) {
                return Err(FederationV2Error::DuplicateResultIdentity);
            }
        }
        if self.payload_digest != self.compute_payload_digest() {
            return Err(FederationV2Error::DigestMismatch("response_payload"));
        }
        if self.response_digest != self.compute_response_digest() {
            return Err(FederationV2Error::DigestMismatch("response"));
        }
        Ok(())
    }

    pub(super) fn verify_for_request(
        &self,
        query: &FederatedQueryV2,
        lease: &FederatedLeaseV2,
        capability: &VerifiedCapabilityReceiptV2,
        peer: &PeerTrustV2,
    ) -> Result<(), FederationV2Error> {
        self.validate_shape()?;
        for (name, left, right) in [
            ("response_peer", self.peer_id.as_str(), query.peer_id.as_str()),
            ("response_peer_key", self.peer_key_id.as_str(), peer.key_id.as_str()),
            ("response_grant", self.grant_id.as_str(), query.grant_id.as_str()),
            ("response_lease", self.lease_id.as_str(), lease.lease_id.as_str()),
        ] {
            if left != right {
                return Err(FederationV2Error::IdentityMismatch(name));
            }
        }
        if self.peer_key_epoch != peer.key_epoch {
            return Err(FederationV2Error::PeerKeyEpochMismatch);
        }
        if self.grant_epoch != capability.grant_epoch {
            return Err(FederationV2Error::GrantEpochMismatch);
        }
        if self.lease_epoch != capability.lease_epoch {
            return Err(FederationV2Error::LeaseEpochMismatch);
        }
        if self.revocation_epoch < capability.revocation_epoch {
            return Err(FederationV2Error::RevocationEpochRegressed);
        }
        for (name, left, right) in [
            ("response_query_binding", self.query_binding_digest, query.binding_digest()),
            ("response_request_nonce", self.request_nonce_digest, query.nonce_digest),
            ("response_scope", self.scope_digest, query.scope_digest),
            ("response_purpose", self.purpose_digest, query.purpose_digest),
        ] {
            if left != right {
                return Err(FederationV2Error::DigestMismatch(name));
            }
        }
        verify_signature(&peer.verifying_key, &self.signing_bytes(), &self.signature)
    }
}

fn verify_signature(
    key: &VerifyingKey,
    message: &[u8],
    signature: &[u8; 64],
) -> Result<(), FederationV2Error> {
    key.verify_strict(message, &Signature::from_bytes(signature))
        .map_err(|_| FederationV2Error::InvalidPeerSignature)
}
