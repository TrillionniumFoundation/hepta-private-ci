//! Revision-bound canonical shadow reads.
//!
//! V1 legacy citations carry source identity and digest but no source revision.
//! This V2 shadow therefore requires an explicit owner-issued revision bridge
//! for every legacy citation and binds that bridge to the canonical
//! `MemoryEventV1` provenance. The result remains authority-free local integrity
//! evidence. It is not a wire protocol, a cache of current authorization, or
//! final-use authority.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf::MemoryEventV1;
use codex_hepta_cognitive_types::hnmf::MemoryLifecycleV1;
use codex_hepta_cognitive_types::wire::canonical_contract_digest_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::AuthoritativeReadResultV1;
use crate::SnapshotProviderError;

const CANONICAL_READ_SHADOW_V2_DOMAIN: &[u8] =
    b"hepta.cognitive.authoritative-read.canonical-shadow.v2";

/// Exact owner-issued source revision corresponding to one legacy citation.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct CanonicalSourceRevisionBindingV2 {
    pub source_id: StableId,
    pub source_revision: u64,
    pub source_digest: Digest32,
}

/// Exact legacy record-to-event bridge plus source revision bindings.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalReadRecordBindingV2 {
    pub legacy_record_id: StableId,
    pub legacy_record_revision: Revision,
    pub legacy_record_digest: Digest32,
    pub source_revisions: Vec<CanonicalSourceRevisionBindingV2>,
    pub event: MemoryEventV1,
}

/// Canonical row produced only after exact record and source revision validation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalReadShadowRowV2 {
    pub legacy_record_id: StableId,
    pub legacy_record_revision: Revision,
    pub legacy_record_digest: Digest32,
    pub source_revisions: Vec<CanonicalSourceRevisionBindingV2>,
    pub event_id: ContractIdV1,
    pub event_digest: Digest32,
    pub event: MemoryEventV1,
}

/// Authority-free, revision-bound canonical shadow for one authoritative read.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalAuthoritativeReadShadowV2 {
    pub request_digest: Digest32,
    pub snapshot_receipt_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub read_receipt_digest: Digest32,
    pub rows: Vec<CanonicalReadShadowRowV2>,
    pub omitted_count: usize,
    pub binding_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CanonicalAuthoritativeReadShadowV2 {
    #[must_use]
    pub fn compute_binding_digest(&self) -> Digest32 {
        let mut bytes = CANONICAL_READ_SHADOW_V2_DOMAIN.to_vec();
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
            bytes.extend_from_slice(
                &u32::try_from(row.source_revisions.len())
                    .unwrap_or(u32::MAX)
                    .to_be_bytes(),
            );
            for source in &row.source_revisions {
                push_stable_id(&mut bytes, &source.source_id);
                bytes.extend_from_slice(&source.source_revision.to_be_bytes());
                bytes.extend_from_slice(source.source_digest.as_array());
            }
            push_raw_id(&mut bytes, row.event_id.as_str());
            bytes.extend_from_slice(row.event_digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), CanonicalReadShadowV2Error> {
        for digest in [
            self.request_digest,
            self.snapshot_receipt_digest,
            self.generation_vector_digest,
            self.read_receipt_digest,
            self.binding_digest,
        ] {
            if digest.is_zero() {
                return Err(CanonicalReadShadowV2Error::EmptyDigest);
            }
        }
        if self.authority.grants_any() {
            return Err(CanonicalReadShadowV2Error::AuthorityGranted);
        }
        for row in &self.rows {
            validate_source_revision_bindings(
                &row.legacy_record_id,
                &row.source_revisions,
                &row.event,
            )?;
            let digest = canonical_contract_digest_v1(&row.event)
                .map_err(|error| CanonicalReadShadowV2Error::CanonicalContract(error.to_string()))?;
            if row.event_id != row.event.event_id || row.event_digest != digest {
                return Err(CanonicalReadShadowV2Error::EventDigestMismatch(
                    row.legacy_record_id.to_string(),
                ));
            }
        }
        if self.binding_digest != self.compute_binding_digest() {
            return Err(CanonicalReadShadowV2Error::BindingDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalReadShadowV2Error {
    Authoritative(SnapshotProviderError),
    CanonicalContract(String),
    BindingCountMismatch,
    MissingExactRecordBinding(String),
    DuplicateRecordBinding(String),
    MissingSourceRevisionBinding(String),
    DuplicateSourceRevisionBinding(String),
    CitationProvenanceMismatch(String),
    SourceRevisionMismatch(String),
    LifecycleMismatch(String),
    EventDigestMismatch(String),
    EmptyDigest,
    BindingDigestMismatch,
    AuthorityGranted,
}

impl fmt::Display for CanonicalReadShadowV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CanonicalReadShadowV2Error {}

/// Project an authoritative legacy read into revision-bound canonical rows.
///
/// V1 remains unchanged for compatibility. This V2 adapter requires one exact
/// source revision binding for every legacy citation, validates identity and
/// digest against the legacy record, and validates identity, revision and
/// digest against the canonical event provenance.
pub fn adapt_authoritative_read_to_revision_bound_canonical_shadow_v2(
    read: &AuthoritativeReadResultV1,
    bindings: Vec<CanonicalReadRecordBindingV2>,
) -> Result<CanonicalAuthoritativeReadShadowV2, CanonicalReadShadowV2Error> {
    read.validate()
        .map_err(CanonicalReadShadowV2Error::Authoritative)?;
    let records = read.read_result.records();
    if bindings.len() != records.len() {
        return Err(CanonicalReadShadowV2Error::BindingCountMismatch);
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
            return Err(CanonicalReadShadowV2Error::MissingExactRecordBinding(
                record.record_id.to_string(),
            ));
        };
        used[index] = true;
        validate_read_record_event_binding_v2(
            record,
            &binding.source_revisions,
            &binding.event,
        )?;
        let event_digest = canonical_contract_digest_v1(&binding.event)
            .map_err(|error| CanonicalReadShadowV2Error::CanonicalContract(error.to_string()))?;
        let mut source_revisions = binding.source_revisions.clone();
        source_revisions.sort();
        rows.push(CanonicalReadShadowRowV2 {
            legacy_record_id: record.record_id.clone(),
            legacy_record_revision: record.revision,
            legacy_record_digest: record_digest,
            source_revisions,
            event_id: binding.event.event_id.clone(),
            event_digest,
            event: binding.event.clone(),
        });
    }
    if used.iter().any(|used| !*used) {
        return Err(CanonicalReadShadowV2Error::DuplicateRecordBinding(
            "unused canonical binding".to_string(),
        ));
    }

    let mut result = CanonicalAuthoritativeReadShadowV2 {
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
    result.validate()?;
    Ok(result)
}

fn validate_read_record_event_binding_v2(
    record: &MemoryRecord,
    source_revisions: &[CanonicalSourceRevisionBindingV2],
    event: &MemoryEventV1,
) -> Result<(), CanonicalReadShadowV2Error> {
    event
        .validate()
        .map_err(|error| CanonicalReadShadowV2Error::CanonicalContract(error.to_string()))?;

    let lifecycle_matches = match record.state {
        RecordState::Live => !matches!(event.lifecycle, MemoryLifecycleV1::Tombstoned { .. }),
        RecordState::Tombstone => matches!(event.lifecycle, MemoryLifecycleV1::Tombstoned { .. }),
    };
    if !lifecycle_matches {
        return Err(CanonicalReadShadowV2Error::LifecycleMismatch(
            record.record_id.to_string(),
        ));
    }

    let mut citation_sources = BTreeMap::<String, Digest32>::new();
    for citation in &record.citations {
        if citation_sources
            .insert(citation.source_id.to_string(), citation.source_digest)
            .is_some()
        {
            return Err(CanonicalReadShadowV2Error::CitationProvenanceMismatch(
                record.record_id.to_string(),
            ));
        }
    }

    let revision_sources =
        source_revision_map(&record.record_id, source_revisions)?;
    let revision_digests = revision_sources
        .iter()
        .map(|(source_id, (_, digest))| (source_id.clone(), *digest))
        .collect::<BTreeMap<_, _>>();
    if citation_sources != revision_digests {
        return Err(CanonicalReadShadowV2Error::CitationProvenanceMismatch(
            record.record_id.to_string(),
        ));
    }

    validate_source_revision_bindings(&record.record_id, source_revisions, event)
}

fn validate_source_revision_bindings(
    record_id: &StableId,
    source_revisions: &[CanonicalSourceRevisionBindingV2],
    event: &MemoryEventV1,
) -> Result<(), CanonicalReadShadowV2Error> {
    event
        .validate()
        .map_err(|error| CanonicalReadShadowV2Error::CanonicalContract(error.to_string()))?;
    let revision_sources = source_revision_map(record_id, source_revisions)?;
    let mut provenance_sources = BTreeMap::<String, (u64, Digest32)>::new();
    for provenance in &event.provenance {
        if provenance_sources
            .insert(
                provenance.source_id.to_string(),
                (
                    provenance.source_revision,
                    provenance.source_sha256.digest(),
                ),
            )
            .is_some()
        {
            return Err(CanonicalReadShadowV2Error::SourceRevisionMismatch(
                record_id.to_string(),
            ));
        }
    }
    if revision_sources != provenance_sources {
        return Err(CanonicalReadShadowV2Error::SourceRevisionMismatch(
            record_id.to_string(),
        ));
    }
    Ok(())
}

fn source_revision_map(
    record_id: &StableId,
    source_revisions: &[CanonicalSourceRevisionBindingV2],
) -> Result<BTreeMap<String, (u64, Digest32)>, CanonicalReadShadowV2Error> {
    if source_revisions.is_empty() {
        return Err(CanonicalReadShadowV2Error::MissingSourceRevisionBinding(
            record_id.to_string(),
        ));
    }
    let mut values = BTreeMap::new();
    for source in source_revisions {
        if source.source_revision == 0 {
            return Err(CanonicalReadShadowV2Error::MissingSourceRevisionBinding(
                record_id.to_string(),
            ));
        }
        if values
            .insert(
                source.source_id.to_string(),
                (source.source_revision, source.source_digest),
            )
            .is_some()
        {
            return Err(CanonicalReadShadowV2Error::DuplicateSourceRevisionBinding(
                record_id.to_string(),
            ));
        }
    }
    Ok(values)
}

fn push_stable_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_raw_id(bytes, value.as_str());
}

fn push_raw_id(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}
