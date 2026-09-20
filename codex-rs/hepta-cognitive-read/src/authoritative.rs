//! Authoritative snapshot acquisition boundary for `cognitive.read`.
//!
//! The legacy read functions intentionally validate only caller-supplied bytes.
//! This module adds the missing provider boundary: a product adapter must acquire
//! one coherent, scope-bound generation vector from an authoritative owner before
//! any read result can be attached to downstream context.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf::MemoryEventV1;
use codex_hepta_cognitive_types::hnmf::MemoryLifecycleV1;
use codex_hepta_cognitive_types::wire::canonical_contract_digest_v1;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCContractError;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ReadRequestV2;
use crate::ReadResultV2;
use crate::ReadV2Error;
use crate::read_v2;

const SNAPSHOT_RECEIPT_DOMAIN: &[u8] = b"hepta.cognitive.authoritative-snapshot.v1";
const AUTHORITATIVE_READ_DOMAIN: &[u8] = b"hepta.cognitive.authoritative-read.v1";
const CANONICAL_READ_SHADOW_DOMAIN: &[u8] =
    b"hepta.cognitive.authoritative-read.canonical-shadow.v1";

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

/// Product adapters implement this trait against the canonical cognitive owner.
///
/// Implementations must not manufacture a snapshot from independent reads. They
/// acquire one owner-defined cut and return it with a lease and receipt.
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
    pub request_digest: Digest32,
    pub snapshot_receipt_digest: Digest32,
    pub generation_vector_digest: Digest32,
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
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalReadRecordBindingV1 {
    pub legacy_record_id: StableId,
    pub legacy_record_revision: codex_hepta_types::Revision,
    pub legacy_record_digest: Digest32,
    pub event: MemoryEventV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalReadShadowRowV1 {
    pub legacy_record_id: StableId,
    pub legacy_record_revision: codex_hepta_types::Revision,
    pub legacy_record_digest: Digest32,
    pub event_id: ContractIdV1,
    pub event_digest: Digest32,
    pub event: MemoryEventV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalAuthoritativeReadShadowV1 {
    pub request_digest: Digest32,
    pub snapshot_receipt_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub read_receipt_digest: Digest32,
    pub rows: Vec<CanonicalReadShadowRowV1>,
    pub omitted_count: usize,
    pub binding_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CanonicalAuthoritativeReadShadowV1 {
    #[must_use]
    pub fn compute_binding_digest(&self) -> Digest32 {
        let mut bytes = CANONICAL_READ_SHADOW_DOMAIN.to_vec();
        for digest in [
            self.request_digest,
            self.snapshot_receipt_digest,
            self.generation_vector_digest,
            self.read_receipt_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(
            &u64::try_from(self.omitted_count)
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        bytes.extend_from_slice(
            &u64::try_from(self.rows.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        for row in &self.rows {
            push_stable_id(&mut bytes, &row.legacy_record_id);
            bytes.extend_from_slice(&row.legacy_record_revision.get().to_be_bytes());
            bytes.extend_from_slice(row.legacy_record_digest.as_array());
            push_raw_id(&mut bytes, row.event_id.as_str());
            bytes.extend_from_slice(row.event_digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), CanonicalReadShadowError> {
        for digest in [
            self.request_digest,
            self.snapshot_receipt_digest,
            self.generation_vector_digest,
            self.read_receipt_digest,
            self.binding_digest,
        ] {
            if digest.is_zero() {
                return Err(CanonicalReadShadowError::EmptyDigest);
            }
        }
        if self.authority.grants_any() {
            return Err(CanonicalReadShadowError::AuthorityGranted);
        }
        if self.binding_digest != self.compute_binding_digest() {
            return Err(CanonicalReadShadowError::BindingDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalReadShadowError {
    Authoritative(SnapshotProviderError),
    CanonicalContract(String),
    BindingCountMismatch,
    MissingExactRecordBinding(String),
    DuplicateRecordBinding(String),
    CitationProvenanceMismatch(String),
    LifecycleMismatch(String),
    EmptyDigest,
    BindingDigestMismatch,
    AuthorityGranted,
}

impl fmt::Display for CanonicalReadShadowError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CanonicalReadShadowError {}

/// Project an already-authoritative legacy read into canonical MemoryEventV1
/// rows using an explicit exact record-to-event bridge.
///
/// The caller supplies complete canonical events. This function never derives a
/// canonical event identity from a legacy record identity and never treats a
/// legacy record digest as a canonical event digest.
pub fn adapt_authoritative_read_to_canonical_shadow_v1(
    read: &AuthoritativeReadResultV1,
    bindings: Vec<CanonicalReadRecordBindingV1>,
) -> Result<CanonicalAuthoritativeReadShadowV1, CanonicalReadShadowError> {
    read.validate()
        .map_err(CanonicalReadShadowError::Authoritative)?;
    let records = read.read_result.records();
    if bindings.len() != records.len() {
        return Err(CanonicalReadShadowError::BindingCountMismatch);
    }

    let mut used = vec![false; bindings.len()];
    let mut rows = Vec::with_capacity(records.len());
    for record in records {
        let record_digest = record.record_digest();
        let Some((index, binding)) = bindings.iter().enumerate().find(|(index, binding)| {
            !used[*index]
                && binding.legacy_record_id == record.record_id
                && binding.legacy_record_revision == record.revision
                && binding.legacy_record_digest == record_digest
        }) else {
            return Err(CanonicalReadShadowError::MissingExactRecordBinding(
                record.record_id.to_string(),
            ));
        };
        used[index] = true;
        validate_read_record_event_binding(record, &binding.event)?;
        let event_digest = canonical_contract_digest_v1(&binding.event)
            .map_err(|error| CanonicalReadShadowError::CanonicalContract(error.to_string()))?;
        rows.push(CanonicalReadShadowRowV1 {
            legacy_record_id: record.record_id.clone(),
            legacy_record_revision: record.revision,
            legacy_record_digest: record_digest,
            event_id: binding.event.event_id.clone(),
            event_digest,
            event: binding.event.clone(),
        });
    }
    if used.iter().any(|used| !*used) {
        return Err(CanonicalReadShadowError::DuplicateRecordBinding(
            "unused canonical binding".to_string(),
        ));
    }

    let mut result = CanonicalAuthoritativeReadShadowV1 {
        request_digest: read.request_digest,
        snapshot_receipt_digest: read.snapshot_receipt_digest,
        generation_vector_digest: read.generation_vector_digest,
        read_receipt_digest: read.read_result.receipt_digest(),
        rows,
        omitted_count: read.read_result.omitted_count(),
        binding_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.binding_digest = result.compute_binding_digest();
    Ok(result)
}

fn validate_read_record_event_binding(
    record: &MemoryRecord,
    event: &MemoryEventV1,
) -> Result<(), CanonicalReadShadowError> {
    event
        .validate()
        .map_err(|error| CanonicalReadShadowError::CanonicalContract(error.to_string()))?;

    let lifecycle_matches = match record.state {
        RecordState::Live => !matches!(event.lifecycle, MemoryLifecycleV1::Tombstoned { .. }),
        RecordState::Tombstone => matches!(event.lifecycle, MemoryLifecycleV1::Tombstoned { .. }),
    };
    if !lifecycle_matches {
        return Err(CanonicalReadShadowError::LifecycleMismatch(
            record.record_id.to_string(),
        ));
    }

    let mut citation_sources = BTreeMap::<String, Digest32>::new();
    for citation in &record.citations {
        if citation_sources
            .insert(citation.source_id.to_string(), citation.source_digest)
            .is_some()
        {
            return Err(CanonicalReadShadowError::CitationProvenanceMismatch(
                record.record_id.to_string(),
            ));
        }
    }
    let mut provenance_sources = BTreeMap::<String, Digest32>::new();
    for provenance in &event.provenance {
        if provenance_sources
            .insert(
                provenance.source_id.to_string(),
                provenance.source_sha256.digest(),
            )
            .is_some()
        {
            return Err(CanonicalReadShadowError::CitationProvenanceMismatch(
                record.record_id.to_string(),
            ));
        }
    }
    if citation_sources != provenance_sources {
        return Err(CanonicalReadShadowError::CitationProvenanceMismatch(
            record.record_id.to_string(),
        ));
    }
    Ok(())
}

fn push_stable_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_raw_id(bytes, value.as_str());
}

fn push_raw_id(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(
        &u32::try_from(value.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
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
    Ok(result)
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
