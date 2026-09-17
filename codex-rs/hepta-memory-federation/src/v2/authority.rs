use std::collections::BTreeMap;
use std::future::Future;
use std::pin::Pin;
use std::time::{SystemTime, UNIX_EPOCH};

use codex_hepta_types::{Digest32, StableId};
use ed25519_dalek::VerifyingKey;

use super::model::{
    FederatedLeaseV2, FederatedQueryV2, FederationV2Error, ensure_digest, push_digest, push_id,
    push_u64, require_nonzero,
};

const CAPABILITY_RECEIPT_DOMAIN: &[u8] = b"hepta.memory-federation.capability-receipt.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedCapabilityReceiptV2 {
    pub issuer_id: StableId,
    pub issuer_key_id: StableId,
    pub grant_id: StableId,
    pub lease_id: StableId,
    pub peer_id: StableId,
    pub principal_id: StableId,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub query_binding_digest: Digest32,
    pub grant_epoch: u64,
    pub lease_epoch: u64,
    pub revocation_epoch: u64,
    pub expires_unix_ms: u64,
    pub verification_digest: Digest32,
}

impl VerifiedCapabilityReceiptV2 {
    pub fn validate_for_query(
        &self,
        now_unix_ms: u64,
        query: &FederatedQueryV2,
        lease: &FederatedLeaseV2,
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
        require_nonzero("revocation_epoch", self.revocation_epoch)?;
        for (name, left, right) in [
            (
                "issuer_id",
                self.issuer_id.as_str(),
                lease.issuer_id.as_str(),
            ),
            (
                "issuer_key_id",
                self.issuer_key_id.as_str(),
                lease.issuer_key_id.as_str(),
            ),
            ("grant_id", self.grant_id.as_str(), query.grant_id.as_str()),
            ("lease_id", self.lease_id.as_str(), lease.lease_id.as_str()),
            ("peer_id", self.peer_id.as_str(), query.peer_id.as_str()),
            (
                "principal_id",
                self.principal_id.as_str(),
                query.principal_id.as_str(),
            ),
        ] {
            if left != right {
                return Err(FederationV2Error::CapabilityReceiptMismatch(name));
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
        ensure_digest("authority_verification", self.verification_digest)
    }

    #[must_use]
    pub fn binding_digest(&self) -> Digest32 {
        let mut bytes = Vec::with_capacity(640);
        bytes.extend_from_slice(CAPABILITY_RECEIPT_DOMAIN);
        for value in [
            &self.issuer_id,
            &self.issuer_key_id,
            &self.grant_id,
            &self.lease_id,
            &self.peer_id,
            &self.principal_id,
        ] {
            push_id(&mut bytes, value);
        }
        for digest in [
            self.scope_digest,
            self.purpose_digest,
            self.generation_vector_digest,
            self.query_binding_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.grant_epoch);
        push_u64(&mut bytes, self.lease_epoch);
        push_u64(&mut bytes, self.revocation_epoch);
        push_u64(&mut bytes, self.expires_unix_ms);
        push_digest(&mut bytes, self.verification_digest);
        Digest32::of_bytes(&bytes)
    }
}

pub type FederationAuthorityFutureV2<'a> = Pin<
    Box<dyn Future<Output = Result<VerifiedCapabilityReceiptV2, FederationV2Error>> + Send + 'a>,
>;

/// Boundary to the authoritative lease/revocation owner. Implementations must
/// verify issuer/key authenticity, proof binding and the current revocation
/// frontier; callers never infer authority from raw lease fields.
pub trait FederationAuthorityV2: Send + Sync {
    fn verify_for_query<'a>(
        &'a self,
        now_unix_ms: u64,
        query: &'a FederatedQueryV2,
        lease: &'a FederatedLeaseV2,
    ) -> FederationAuthorityFutureV2<'a>;

    fn revalidate<'a>(
        &'a self,
        now_unix_ms: u64,
        query: &'a FederatedQueryV2,
        lease: &'a FederatedLeaseV2,
        previous: &'a VerifiedCapabilityReceiptV2,
    ) -> FederationAuthorityFutureV2<'a>;
}

pub trait FederationClockV2: Send + Sync {
    fn now_unix_ms(&self) -> Result<u64, FederationV2Error>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SystemFederationClockV2;

impl FederationClockV2 for SystemFederationClockV2 {
    fn now_unix_ms(&self) -> Result<u64, FederationV2Error> {
        let duration = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| FederationV2Error::ClockUnavailable)?;
        u64::try_from(duration.as_millis()).map_err(|_| FederationV2Error::ClockUnavailable)
    }
}

#[derive(Clone)]
pub struct PeerTrustV2 {
    pub peer_id: StableId,
    pub key_id: StableId,
    pub key_epoch: u64,
    pub verifying_key: VerifyingKey,
    pub enabled: bool,
}

pub trait FederationPeerDirectoryV2: Send + Sync {
    fn resolve_peer(&self, peer_id: &StableId) -> Result<PeerTrustV2, FederationV2Error>;
}

/// Read-only snapshot supplied by a trusted product peer registry. This module
/// never enrolls peers or stores private credentials.
#[derive(Clone, Default)]
pub struct TrustedPeerSnapshotV2 {
    peers: BTreeMap<StableId, PeerTrustV2>,
}

impl TrustedPeerSnapshotV2 {
    pub fn from_records(records: Vec<PeerTrustV2>) -> Result<Self, FederationV2Error> {
        let mut peers = BTreeMap::new();
        for record in records {
            require_nonzero("peer_key_epoch", record.key_epoch)?;
            if peers.insert(record.peer_id.clone(), record).is_some() {
                return Err(FederationV2Error::DuplicatePeerIdentity);
            }
        }
        Ok(Self { peers })
    }
}

impl FederationPeerDirectoryV2 for TrustedPeerSnapshotV2 {
    fn resolve_peer(&self, peer_id: &StableId) -> Result<PeerTrustV2, FederationV2Error> {
        let trust = self
            .peers
            .get(peer_id)
            .cloned()
            .ok_or(FederationV2Error::PeerNotEnrolled)?;
        if !trust.enabled {
            return Err(FederationV2Error::PeerDisabled);
        }
        Ok(trust)
    }
}

pub(crate) fn ensure_same_capability(
    previous: &VerifiedCapabilityReceiptV2,
    refreshed: &VerifiedCapabilityReceiptV2,
) -> Result<(), FederationV2Error> {
    for (name, left, right) in [
        (
            "issuer_id",
            previous.issuer_id.as_str(),
            refreshed.issuer_id.as_str(),
        ),
        (
            "issuer_key_id",
            previous.issuer_key_id.as_str(),
            refreshed.issuer_key_id.as_str(),
        ),
        (
            "grant_id",
            previous.grant_id.as_str(),
            refreshed.grant_id.as_str(),
        ),
        (
            "lease_id",
            previous.lease_id.as_str(),
            refreshed.lease_id.as_str(),
        ),
        (
            "peer_id",
            previous.peer_id.as_str(),
            refreshed.peer_id.as_str(),
        ),
        (
            "principal_id",
            previous.principal_id.as_str(),
            refreshed.principal_id.as_str(),
        ),
    ] {
        if left != right {
            return Err(FederationV2Error::CapabilityReceiptMismatch(name));
        }
    }
    for (name, left, right) in [
        ("scope", previous.scope_digest, refreshed.scope_digest),
        ("purpose", previous.purpose_digest, refreshed.purpose_digest),
        (
            "generation_vector",
            previous.generation_vector_digest,
            refreshed.generation_vector_digest,
        ),
        (
            "query_binding",
            previous.query_binding_digest,
            refreshed.query_binding_digest,
        ),
    ] {
        if left != right {
            return Err(FederationV2Error::DigestMismatch(name));
        }
    }
    if previous.grant_epoch != refreshed.grant_epoch {
        return Err(FederationV2Error::GrantEpochMismatch);
    }
    if previous.lease_epoch != refreshed.lease_epoch {
        return Err(FederationV2Error::LeaseEpochMismatch);
    }
    Ok(())
}
