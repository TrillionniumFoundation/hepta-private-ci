//! Authoritative snapshot acquisition boundary for `cognitive.read`.
//!
//! The lower-level V2 projection validates caller-supplied snapshot bytes. This
//! module adds the owner/provider boundary needed by product callers: one
//! immutable, scope/purpose-bound owner cut plus a bounded lease and a final-use
//! revalidation contract.
//!
//! `CognitiveReadGenerationVectorV1` is the explicitly documented Lane-C
//! subset required by this module. It intentionally contains only facts that
//! the cognitive owner and the serving host can authoritatively provide. Product
//! callers must not invent unrelated prompt/model/compact generations merely to
//! satisfy a wider Lane-C vector.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ReadRequestV2;
use crate::ReadResultV2;
use crate::ReadV2Error;
use crate::read_v2;

const GENERATION_VECTOR_DOMAIN: &[u8] = b"hepta.cognitive.read-generation-vector.v1";
const SNAPSHOT_RECEIPT_DOMAIN: &[u8] = b"hepta.cognitive.authoritative-snapshot.v1";
const AUTHORITATIVE_READ_DOMAIN: &[u8] = b"hepta.cognitive.authoritative-read.v1";

/// Exact authoritative subset needed by cognitive.read.
///
/// The owner supplies every cognitive frontier/generation. The host supplies
/// the serving generation and authority epoch. Equality of this digest at final
/// use is the closed-world proof that neither side silently moved.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveReadGenerationVectorV1 {
    pub scope_id: StableId,
    pub purpose_id: StableId,
    pub memory_ledger_frontier: u64,
    pub source_ledger_frontier: u64,
    pub tombstone_frontier: u64,
    pub knowledge_fact_frontier: u64,
    pub knowledge_graph_generation: Generation,
    pub host_generation: Generation,
    pub authority_epoch: u64,
}

impl CognitiveReadGenerationVectorV1 {
    pub fn validate(&self) -> Result<(), SnapshotProviderError> {
        if self.authority_epoch == 0 {
            return Err(SnapshotProviderError::InvalidRequest("authority_epoch"));
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(GENERATION_VECTOR_DOMAIN);
        push_id(&mut bytes, &self.scope_id);
        push_id(&mut bytes, &self.purpose_id);
        for frontier in [
            self.memory_ledger_frontier,
            self.source_ledger_frontier,
            self.tombstone_frontier,
            self.knowledge_fact_frontier,
        ] {
            push_u64(&mut bytes, frontier);
        }
        push_u64(&mut bytes, self.knowledge_graph_generation.get());
        push_u64(&mut bytes, self.host_generation.get());
        push_u64(&mut bytes, self.authority_epoch);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SnapshotAcquisitionRequestV1 {
    pub request_id: StableId,
    pub scope_id: StableId,
    pub purpose_id: StableId,
    pub minimum_memory_frontier: u64,
    pub minimum_source_frontier: u64,
    pub minimum_tombstone_frontier: u64,
    pub minimum_knowledge_fact_frontier: u64,
    pub host_generation: Generation,
    pub authority_epoch: u64,
    pub deadline_unix_ms: u64,
}

impl SnapshotAcquisitionRequestV1 {
    pub fn validate(&self, now_unix_ms: u64) -> Result<(), SnapshotProviderError> {
        if self.authority_epoch == 0 {
            return Err(SnapshotProviderError::InvalidRequest("authority_epoch"));
        }
        if self.deadline_unix_ms == 0 || now_unix_ms >= self.deadline_unix_ms {
            return Err(SnapshotProviderError::DeadlineExpired);
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.cognitive.snapshot-acquisition-request.v1".to_vec();
        push_id(&mut bytes, &self.request_id);
        push_id(&mut bytes, &self.scope_id);
        push_id(&mut bytes, &self.purpose_id);
        push_u64(&mut bytes, self.minimum_memory_frontier);
        push_u64(&mut bytes, self.minimum_source_frontier);
        push_u64(&mut bytes, self.minimum_tombstone_frontier);
        push_u64(&mut bytes, self.minimum_knowledge_fact_frontier);
        push_u64(&mut bytes, self.host_generation.get());
        push_u64(&mut bytes, self.authority_epoch);
        push_u64(&mut bytes, self.deadline_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

/// Product adapters implement this trait against the canonical cognitive owner.
///
/// Implementations must not manufacture a snapshot from independent reads. They
/// acquire one owner-defined immutable cut and return it with a bounded lease
/// and receipt.
pub trait AuthoritativeCognitiveSnapshotProvider {
    fn acquire(
        &self,
        request: &SnapshotAcquisitionRequestV1,
    ) -> Result<AuthoritativeSnapshotV1, SnapshotProviderError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthoritativeSnapshotV1 {
    provider_id: StableId,
    generation_vector: CognitiveReadGenerationVectorV1,
    generation_vector_digest: Digest32,
    snapshot: CognitiveSnapshot,
    acquired_at_unix_ms: u64,
    lease_expires_unix_ms: u64,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl AuthoritativeSnapshotV1 {
    pub fn new(
        provider_id: StableId,
        generation_vector: CognitiveReadGenerationVectorV1,
        snapshot: CognitiveSnapshot,
        acquired_at_unix_ms: u64,
        lease_expires_unix_ms: u64,
    ) -> Result<Self, SnapshotProviderError> {
        generation_vector.validate()?;
        snapshot
            .validate_integrity()
            .map_err(|_| SnapshotProviderError::SnapshotIntegrity)?;
        if acquired_at_unix_ms == 0 || lease_expires_unix_ms <= acquired_at_unix_ms {
            return Err(SnapshotProviderError::InvalidLeaseWindow);
        }
        let generation_vector_digest = generation_vector.digest();
        let receipt_digest = compute_snapshot_receipt_digest(
            &provider_id,
            generation_vector_digest,
            &snapshot,
            acquired_at_unix_ms,
            lease_expires_unix_ms,
        );
        Ok(Self {
            provider_id,
            generation_vector,
            generation_vector_digest,
            snapshot,
            acquired_at_unix_ms,
            lease_expires_unix_ms,
            receipt_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    pub fn validate_for_request(
        &self,
        now_unix_ms: u64,
        request: &SnapshotAcquisitionRequestV1,
    ) -> Result<(), SnapshotProviderError> {
        request.validate(now_unix_ms)?;
        self.generation_vector.validate()?;
        self.snapshot
            .validate_integrity()
            .map_err(|_| SnapshotProviderError::SnapshotIntegrity)?;
        if self.authority.grants_any() {
            return Err(SnapshotProviderError::AuthorityGranted);
        }
        if self.acquired_at_unix_ms > now_unix_ms {
            return Err(SnapshotProviderError::AcquiredInFuture);
        }
        if now_unix_ms >= self.lease_expires_unix_ms {
            return Err(SnapshotProviderError::LeaseExpired);
        }
        if self.generation_vector.scope_id != request.scope_id {
            return Err(SnapshotProviderError::ScopeMismatch);
        }
        if self.generation_vector.purpose_id != request.purpose_id {
            return Err(SnapshotProviderError::PurposeMismatch);
        }
        if self.generation_vector.host_generation != request.host_generation {
            return Err(SnapshotProviderError::HostGenerationMismatch);
        }
        if self.generation_vector.authority_epoch != request.authority_epoch {
            return Err(SnapshotProviderError::AuthorityEpochMismatch);
        }
        if self.generation_vector.memory_ledger_frontier < request.minimum_memory_frontier {
            return Err(SnapshotProviderError::StaleMemoryFrontier);
        }
        if self.generation_vector.source_ledger_frontier < request.minimum_source_frontier {
            return Err(SnapshotProviderError::StaleSourceFrontier);
        }
        if self.generation_vector.tombstone_frontier < request.minimum_tombstone_frontier {
            return Err(SnapshotProviderError::StaleTombstoneFrontier);
        }
        if self.generation_vector.knowledge_fact_frontier
            < request.minimum_knowledge_fact_frontier
        {
            return Err(SnapshotProviderError::StaleKnowledgeFactFrontier);
        }
        if self.generation_vector_digest != self.generation_vector.digest() {
            return Err(SnapshotProviderError::GenerationVectorDigestMismatch);
        }
        let expected = compute_snapshot_receipt_digest(
            &self.provider_id,
            self.generation_vector_digest,
            &self.snapshot,
            self.acquired_at_unix_ms,
            self.lease_expires_unix_ms,
        );
        if expected != self.receipt_digest {
            return Err(SnapshotProviderError::ReceiptDigestMismatch);
        }
        Ok(())
    }

    #[must_use]
    pub fn provider_id(&self) -> &StableId {
        &self.provider_id
    }

    #[must_use]
    pub const fn generation_vector(&self) -> &CognitiveReadGenerationVectorV1 {
        &self.generation_vector
    }

    #[must_use]
    pub const fn generation_vector_digest(&self) -> Digest32 {
        self.generation_vector_digest
    }

    #[must_use]
    pub const fn snapshot(&self) -> &CognitiveSnapshot {
        &self.snapshot
    }

    #[must_use]
    pub const fn acquired_at_unix_ms(&self) -> u64 {
        self.acquired_at_unix_ms
    }

    #[must_use]
    pub const fn lease_expires_unix_ms(&self) -> u64 {
        self.lease_expires_unix_ms
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthoritativeReadResultV1 {
    pub provider_id: StableId,
    pub request_digest: Digest32,
    pub snapshot_receipt_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub lease_expires_unix_ms: u64,
    pub read_result: ReadResultV2,
    pub binding_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl AuthoritativeReadResultV1 {
    pub fn validate(&self) -> Result<(), SnapshotProviderError> {
        if self.request_digest.is_zero()
            || self.snapshot_receipt_digest.is_zero()
            || self.generation_vector_digest.is_zero()
            || self.binding_digest.is_zero()
            || self.lease_expires_unix_ms == 0
        {
            return Err(SnapshotProviderError::EmptyDigest);
        }
        if self.authority.grants_any() {
            return Err(SnapshotProviderError::AuthorityGranted);
        }
        let expected = compute_authoritative_read_digest(
            &self.provider_id,
            self.request_digest,
            self.snapshot_receipt_digest,
            self.generation_vector_digest,
            self.lease_expires_unix_ms,
            self.read_result.receipt_digest(),
        );
        if expected != self.binding_digest {
            return Err(SnapshotProviderError::ReceiptDigestMismatch);
        }
        Ok(())
    }

    /// Revalidate immediately before final context consumption/publication.
    ///
    /// The current snapshot may have a new acquisition receipt/time, but it
    /// must resolve to the same provider, immutable owner snapshot and exact
    /// generation vector. The original lease must also still be live.
    pub fn revalidate_for_current_snapshot(
        &self,
        now_unix_ms: u64,
        request: &SnapshotAcquisitionRequestV1,
        current: &AuthoritativeSnapshotV1,
    ) -> Result<(), SnapshotProviderError> {
        self.validate()?;
        if now_unix_ms >= self.lease_expires_unix_ms {
            return Err(SnapshotProviderError::LeaseExpired);
        }
        if self.request_digest != request.digest() {
            return Err(SnapshotProviderError::RequestBindingMismatch);
        }
        current.validate_for_request(now_unix_ms, request)?;
        if &self.provider_id != current.provider_id() {
            return Err(SnapshotProviderError::ProviderMismatch);
        }
        if self.generation_vector_digest != current.generation_vector_digest() {
            return Err(SnapshotProviderError::GenerationGone);
        }
        if self.read_result.snapshot_digest() != current.snapshot().snapshot_digest {
            return Err(SnapshotProviderError::SnapshotChanged);
        }
        Ok(())
    }
}

pub fn read_authoritative<P: AuthoritativeCognitiveSnapshotProvider>(
    provider: &P,
    now_unix_ms: u64,
    acquisition_request: SnapshotAcquisitionRequestV1,
    read_request: ReadRequestV2,
) -> Result<AuthoritativeReadResultV1, SnapshotProviderError> {
    acquisition_request.validate(now_unix_ms)?;
    let envelope = provider.acquire(&acquisition_request)?;
    envelope.validate_for_request(now_unix_ms, &acquisition_request)?;
    if read_request.read_request.snapshot_digest != envelope.snapshot.snapshot_digest {
        return Err(SnapshotProviderError::ReadSnapshotMismatch);
    }
    let request_digest = acquisition_request.digest();
    let read_result =
        read_v2(&envelope.snapshot, read_request).map_err(SnapshotProviderError::Read)?;
    let provider_id = envelope.provider_id.clone();
    let generation_vector_digest = envelope.generation_vector_digest;
    let snapshot_receipt_digest = envelope.receipt_digest;
    let lease_expires_unix_ms = envelope.lease_expires_unix_ms;
    let binding_digest = compute_authoritative_read_digest(
        &provider_id,
        request_digest,
        snapshot_receipt_digest,
        generation_vector_digest,
        lease_expires_unix_ms,
        read_result.receipt_digest(),
    );
    let result = AuthoritativeReadResultV1 {
        provider_id,
        request_digest,
        snapshot_receipt_digest,
        generation_vector_digest,
        lease_expires_unix_ms,
        read_result,
        binding_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.validate()?;
    Ok(result)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SnapshotProviderError {
    Read(ReadV2Error),
    InvalidRequest(&'static str),
    InvalidLeaseWindow,
    DeadlineExpired,
    LeaseExpired,
    AcquiredInFuture,
    ScopeMismatch,
    PurposeMismatch,
    HostGenerationMismatch,
    AuthorityEpochMismatch,
    StaleMemoryFrontier,
    StaleSourceFrontier,
    StaleTombstoneFrontier,
    StaleKnowledgeFactFrontier,
    SnapshotIntegrity,
    ReadSnapshotMismatch,
    SnapshotChanged,
    RequestBindingMismatch,
    ProviderMismatch,
    GenerationVectorDigestMismatch,
    ReceiptDigestMismatch,
    AuthorityGranted,
    EmptyDigest,
    Unavailable,
    Revoked,
    GenerationGone,
    Indeterminate,
}

impl fmt::Display for SnapshotProviderError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for SnapshotProviderError {}

fn compute_snapshot_receipt_digest(
    provider_id: &StableId,
    generation_vector_digest: Digest32,
    snapshot: &CognitiveSnapshot,
    acquired_at_unix_ms: u64,
    lease_expires_unix_ms: u64,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(SNAPSHOT_RECEIPT_DOMAIN);
    push_id(&mut bytes, provider_id);
    bytes.extend_from_slice(generation_vector_digest.as_array());
    bytes.extend_from_slice(snapshot.snapshot_digest.as_array());
    push_u64(&mut bytes, acquired_at_unix_ms);
    push_u64(&mut bytes, lease_expires_unix_ms);
    Digest32::of_bytes(&bytes)
}

fn compute_authoritative_read_digest(
    provider_id: &StableId,
    request_digest: Digest32,
    snapshot_receipt_digest: Digest32,
    generation_vector_digest: Digest32,
    lease_expires_unix_ms: u64,
    read_receipt_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(AUTHORITATIVE_READ_DOMAIN);
    push_id(&mut bytes, provider_id);
    for digest in [
        request_digest,
        snapshot_receipt_digest,
        generation_vector_digest,
        read_receipt_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_u64(&mut bytes, lease_expires_unix_ms);
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u64::try_from(raw.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

#[cfg(test)]
#[path = "authoritative_tests.rs"]
mod tests;
