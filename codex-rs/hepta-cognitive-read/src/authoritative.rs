//! Authoritative snapshot acquisition boundary for `cognitive.read`.
//!
//! Low-level read functions intentionally validate only caller-supplied bytes.
//! Product callers use this module instead: acquire one coherent, scope-bound
//! owner cut, perform the bounded projection against that exact snapshot, then
//! reacquire and revalidate the authoritative provider immediately before use.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCContractError;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ReadRequest;
use crate::ReadRequestV2;
use crate::ReadResultV2;
use crate::ReadV2Error;
use crate::v2::read_v2;

const SNAPSHOT_RECEIPT_DOMAIN: &[u8] = b"hepta.cognitive.authoritative-snapshot.v1";
const AUTHORITATIVE_READ_DOMAIN: &[u8] = b"hepta.cognitive.authoritative-read.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SnapshotAcquisitionRequestV1 {
    pub request_id: StableId,
    pub scope_id: StableId,
    pub purpose_id: StableId,
    pub minimum_memory_frontier: u64,
    pub minimum_tombstone_frontier: u64,
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
        push_u64(&mut bytes, self.minimum_tombstone_frontier);
        push_u64(&mut bytes, self.authority_epoch);
        push_u64(&mut bytes, self.deadline_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

/// Product-level bounded read selector. The authoritative provider supplies the
/// snapshot digest; callers cannot substitute a different caller-owned snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthoritativeReadRequestV1 {
    pub allowed_kinds: Vec<MemoryKind>,
    pub maximum_results: usize,
    pub include_tombstones: bool,
    pub maximum_encoded_bytes: usize,
}

/// Product adapters implement this trait against one canonical cognitive owner.
///
/// Implementations must not manufacture a snapshot from independent reads. Each
/// provider value represents one owner-defined frozen cut. Delivery code creates
/// a fresh provider from the current owner and passes it to
/// [`AuthoritativeReadGuardV1::revalidate`] immediately before consumption.
pub trait AuthoritativeCognitiveSnapshotProvider {
    fn acquire(
        &self,
        request: &SnapshotAcquisitionRequestV1,
    ) -> Result<AuthoritativeSnapshotV1, SnapshotProviderError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthoritativeSnapshotV1 {
    provider_id: StableId,
    snapshot_key: CognitiveSnapshotKeyV1,
    snapshot: CognitiveSnapshot,
    acquired_at_unix_ms: u64,
    lease_expires_unix_ms: u64,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl AuthoritativeSnapshotV1 {
    pub fn new(
        provider_id: StableId,
        snapshot_key: CognitiveSnapshotKeyV1,
        snapshot: CognitiveSnapshot,
        acquired_at_unix_ms: u64,
        lease_expires_unix_ms: u64,
    ) -> Result<Self, SnapshotProviderError> {
        snapshot_key
            .validate()
            .map_err(SnapshotProviderError::Contract)?;
        snapshot
            .validate_integrity()
            .map_err(|_| SnapshotProviderError::SnapshotIntegrity)?;
        if acquired_at_unix_ms == 0 || lease_expires_unix_ms <= acquired_at_unix_ms {
            return Err(SnapshotProviderError::InvalidLeaseWindow);
        }
        let receipt_digest = compute_snapshot_receipt_digest(
            &provider_id,
            &snapshot_key,
            &snapshot,
            acquired_at_unix_ms,
            lease_expires_unix_ms,
        );
        Ok(Self {
            provider_id,
            snapshot_key,
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
        self.snapshot_key
            .validate()
            .map_err(SnapshotProviderError::Contract)?;
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
        if self.snapshot_key.vector.scope_id != request.scope_id {
            return Err(SnapshotProviderError::ScopeMismatch);
        }
        if self.snapshot_key.vector.purpose_id != request.purpose_id {
            return Err(SnapshotProviderError::PurposeMismatch);
        }
        if self.snapshot_key.vector.authority_epoch != request.authority_epoch {
            return Err(SnapshotProviderError::AuthorityEpochMismatch);
        }
        if self.snapshot_key.vector.memory_ledger_frontier < request.minimum_memory_frontier {
            return Err(SnapshotProviderError::StaleMemoryFrontier);
        }
        if self.snapshot_key.vector.tombstone_frontier < request.minimum_tombstone_frontier {
            return Err(SnapshotProviderError::StaleTombstoneFrontier);
        }
        let expected = compute_snapshot_receipt_digest(
            &self.provider_id,
            &self.snapshot_key,
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
    pub const fn snapshot_key(&self) -> &CognitiveSnapshotKeyV1 {
        &self.snapshot_key
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
    request_digest: Digest32,
    snapshot_receipt_digest: Digest32,
    generation_vector_digest: Digest32,
    read_result: ReadResultV2,
    binding_digest: Digest32,
    authority: AuthorityPosture,
}

impl AuthoritativeReadResultV1 {
    pub fn validate(&self) -> Result<(), SnapshotProviderError> {
        if self.request_digest.is_zero()
            || self.snapshot_receipt_digest.is_zero()
            || self.generation_vector_digest.is_zero()
            || self.binding_digest.is_zero()
        {
            return Err(SnapshotProviderError::EmptyDigest);
        }
        if self.authority.grants_any() {
            return Err(SnapshotProviderError::AuthorityGranted);
        }
        let expected = compute_authoritative_read_digest(
            self.request_digest,
            self.snapshot_receipt_digest,
            self.generation_vector_digest,
            self.read_result.receipt_digest(),
        );
        if expected != self.binding_digest {
            return Err(SnapshotProviderError::ReceiptDigestMismatch);
        }
        Ok(())
    }

    #[must_use]
    pub const fn request_digest(&self) -> Digest32 {
        self.request_digest
    }

    #[must_use]
    pub const fn snapshot_receipt_digest(&self) -> Digest32 {
        self.snapshot_receipt_digest
    }

    #[must_use]
    pub const fn generation_vector_digest(&self) -> Digest32 {
        self.generation_vector_digest
    }

    #[must_use]
    pub const fn read_result(&self) -> &ReadResultV2 {
        &self.read_result
    }

    #[must_use]
    pub const fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}

/// A read result plus the exact authoritative envelope that produced it.
///
/// The lower-level result may be used for bounded local computation, but must
/// not be attached to downstream context until [`Self::revalidate`] succeeds
/// against a freshly acquired provider at the final-use boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthoritativeReadGuardV1 {
    acquisition_request: SnapshotAcquisitionRequestV1,
    snapshot: AuthoritativeSnapshotV1,
    result: AuthoritativeReadResultV1,
}

impl AuthoritativeReadGuardV1 {
    #[must_use]
    pub const fn result(&self) -> &AuthoritativeReadResultV1 {
        &self.result
    }

    #[must_use]
    pub const fn read_result(&self) -> &ReadResultV2 {
        self.result.read_result()
    }

    #[must_use]
    pub const fn snapshot_key(&self) -> &CognitiveSnapshotKeyV1 {
        self.snapshot.snapshot_key()
    }

    /// Revalidate the original lease/receipt and compare it to a newly acquired
    /// current provider. Any provider identity, generation-vector or snapshot
    /// change rejects before delivery.
    pub fn revalidate<P: AuthoritativeCognitiveSnapshotProvider>(
        &self,
        current_provider: &P,
        now_unix_ms: u64,
    ) -> Result<(), SnapshotProviderError> {
        self.acquisition_request.validate(now_unix_ms)?;
        self.snapshot
            .validate_for_request(now_unix_ms, &self.acquisition_request)?;
        self.result.validate()?;

        let current = current_provider.acquire(&self.acquisition_request)?;
        current.validate_for_request(now_unix_ms, &self.acquisition_request)?;
        if current.provider_id != self.snapshot.provider_id {
            return Err(SnapshotProviderError::ProviderMismatch);
        }
        if current.snapshot_key.vector_digest != self.snapshot.snapshot_key.vector_digest
            || current.snapshot.snapshot_digest != self.snapshot.snapshot.snapshot_digest
        {
            return Err(SnapshotProviderError::GenerationGone);
        }
        Ok(())
    }
}

pub fn read_authoritative<P: AuthoritativeCognitiveSnapshotProvider>(
    provider: &P,
    now_unix_ms: u64,
    acquisition_request: SnapshotAcquisitionRequestV1,
    read_request: AuthoritativeReadRequestV1,
) -> Result<AuthoritativeReadGuardV1, SnapshotProviderError> {
    acquisition_request.validate(now_unix_ms)?;
    let envelope = provider.acquire(&acquisition_request)?;
    envelope.validate_for_request(now_unix_ms, &acquisition_request)?;

    let request_digest = acquisition_request.digest();
    let read_result = read_v2(
        &envelope.snapshot,
        ReadRequestV2 {
            read_request: ReadRequest {
                snapshot_digest: envelope.snapshot.snapshot_digest,
                allowed_kinds: read_request.allowed_kinds,
                maximum_results: read_request.maximum_results,
                include_tombstones: read_request.include_tombstones,
            },
            maximum_encoded_bytes: read_request.maximum_encoded_bytes,
        },
    )
    .map_err(SnapshotProviderError::Read)?;
    let generation_vector_digest = envelope.snapshot_key.vector_digest;
    let snapshot_receipt_digest = envelope.receipt_digest;
    let binding_digest = compute_authoritative_read_digest(
        request_digest,
        snapshot_receipt_digest,
        generation_vector_digest,
        read_result.receipt_digest(),
    );
    let result = AuthoritativeReadResultV1 {
        request_digest,
        snapshot_receipt_digest,
        generation_vector_digest,
        read_result,
        binding_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.validate()?;
    Ok(AuthoritativeReadGuardV1 {
        acquisition_request,
        snapshot: envelope,
        result,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SnapshotProviderError {
    Contract(LaneCContractError),
    Read(ReadV2Error),
    InvalidRequest(&'static str),
    InvalidLeaseWindow,
    DeadlineExpired,
    LeaseExpired,
    AcquiredInFuture,
    ScopeMismatch,
    PurposeMismatch,
    AuthorityEpochMismatch,
    StaleMemoryFrontier,
    StaleTombstoneFrontier,
    SnapshotIntegrity,
    ReadSnapshotMismatch,
    ReceiptDigestMismatch,
    ProviderMismatch,
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
    snapshot_key: &CognitiveSnapshotKeyV1,
    snapshot: &CognitiveSnapshot,
    acquired_at_unix_ms: u64,
    lease_expires_unix_ms: u64,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(SNAPSHOT_RECEIPT_DOMAIN);
    push_id(&mut bytes, provider_id);
    bytes.extend_from_slice(snapshot_key.vector_digest.as_array());
    bytes.extend_from_slice(snapshot.snapshot_digest.as_array());
    push_u64(&mut bytes, acquired_at_unix_ms);
    push_u64(&mut bytes, lease_expires_unix_ms);
    Digest32::of_bytes(&bytes)
}

fn compute_authoritative_read_digest(
    request_digest: Digest32,
    snapshot_receipt_digest: Digest32,
    generation_vector_digest: Digest32,
    read_receipt_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(AUTHORITATIVE_READ_DOMAIN);
    for digest in [
        request_digest,
        snapshot_receipt_digest,
        generation_vector_digest,
        read_receipt_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
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
