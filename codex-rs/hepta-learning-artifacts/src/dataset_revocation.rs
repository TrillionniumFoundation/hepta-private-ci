//! Prepare owner-local revocations for one explicitly dataset-bound support digest.
//! No source ledger write, durable acknowledgement, selection or erasure occurs here.

use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactEvent;
use crate::ArtifactRegistry;
use crate::ArtifactRegistryError;
use crate::ArtifactState;
use crate::RegistryAppendDisposition;
use crate::StateChange;

const MAX_PREPARED_RECORDS: usize = 4096;
const MAX_DIRECT_TARGETS: usize = 256;

/// A host-authenticated notice delivered to the artifact owner. The host must
/// establish that dataset_digest is the EXACT manifest support_digest, not an
/// inferred relationship, and verify source notice, scope and evaluator identity.
/// Operation identity is scoped by dataset; these fields are not credentials.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetRevocationRequest {
    pub operation_id: StableId,
    pub dataset_digest: Digest32,
    pub source_revocation_digest: Digest32,
    pub evaluator_id: StableId,
}

/// A preparation result, never proof that a new registry or witness was persisted.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetRevocationSummary {
    pub before_head: Digest32,
    pub after_head: Digest32,
    pub request_digest: Digest32,
    pub direct_artifacts: Vec<StableId>,
    pub appended: usize,
    pub replayed: usize,
    pub already_revoked: usize,
    pub authority: AuthorityPosture,
}

/// A fully validated successor kept separate from the caller's current registry.
/// Persist this candidate with write_registry_snapshot, publish a current external
/// witness under the host fence, then acknowledge. Preparation alone does not commit.
#[derive(Debug)]
pub struct PreparedDatasetRevocation {
    registry: ArtifactRegistry,
    summary: DatasetRevocationSummary,
}

impl PreparedDatasetRevocation {
    #[must_use]
    pub fn registry(&self) -> &ArtifactRegistry {
        &self.registry
    }

    #[must_use]
    pub fn summary(&self) -> &DatasetRevocationSummary {
        &self.summary
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DatasetRevocationError {
    EmptyDigest,
    StaleSnapshot,
    NoMatchingArtifacts,
    Capacity,
    Registry(ArtifactRegistryError),
}

impl fmt::Display for DatasetRevocationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl Error for DatasetRevocationError {}

/// Revoke all directly bound artifacts in this exact snapshot. Existing registry
/// ancestry rules also make their descendants ineligible. Reuse existing Revoke
/// events and digests: there is no new on-disk variant or authority source.
/// A stale head, identity conflict, quota or self-evaluation failure drops the
/// entire preparation without changing the input registry, files or witnesses.
pub fn prepare_dataset_revocation(
    registry: &ArtifactRegistry,
    expected_head: Digest32,
    request: &DatasetRevocationRequest,
) -> Result<PreparedDatasetRevocation, DatasetRevocationError> {
    if request.dataset_digest.is_zero() || request.source_revocation_digest.is_zero() {
        return Err(DatasetRevocationError::EmptyDigest);
    }
    if registry.records().len() > MAX_PREPARED_RECORDS {
        return Err(DatasetRevocationError::Capacity);
    }
    let before_head = registry
        .records()
        .last()
        .map_or(Digest32::ZERO, |r| r.chain_digest);
    if before_head != expected_head {
        return Err(DatasetRevocationError::StaleSnapshot);
    }
    let mut targets: Vec<StableId> = registry
        .records()
        .iter()
        .filter_map(|record| match &record.event {
            ArtifactEvent::Register { manifest, .. } => (manifest.support_digest
                == request.dataset_digest)
                .then(|| manifest.artifact_id.clone()),
            ArtifactEvent::Quarantine(_) | ArtifactEvent::Revoke(_) => None,
        })
        .collect();
    targets.sort();
    if targets.is_empty() {
        return Err(DatasetRevocationError::NoMatchingArtifacts);
    }
    if targets.len() > MAX_DIRECT_TARGETS {
        return Err(DatasetRevocationError::Capacity);
    }
    let mut request_bytes = b"hepta.dataset-revocation.request.v1".to_vec();
    push_id(&mut request_bytes, &request.operation_id);
    request_bytes.extend_from_slice(request.dataset_digest.as_array());
    request_bytes.extend_from_slice(request.source_revocation_digest.as_array());
    push_id(&mut request_bytes, &request.evaluator_id);
    let request_digest = Digest32::of_bytes(&request_bytes);
    let existing: BTreeSet<_> = registry
        .records()
        .iter()
        .map(|record| record.event.event_id().clone())
        .collect();
    let mut staged = registry.clone();
    let mut appended = 0;
    let mut replayed = 0;
    let mut already_revoked = 0;
    for artifact in &targets {
        let manifest = registry
            .manifest(artifact)
            .ok_or(DatasetRevocationError::Registry(
                ArtifactRegistryError::InternalInvariant,
            ))?;
        if manifest.producer_id == request.evaluator_id {
            return Err(DatasetRevocationError::Registry(
                ArtifactRegistryError::ProducerSelfEvaluates(artifact.to_string()),
            ));
        }
        // Keep event identity stable across changed notice/evaluator values so
        // conflicting retries reach the existing registry's identity-conflict check.
        let mut key = b"hepta.dataset-revocation.event.v1".to_vec();
        key.extend_from_slice(request.dataset_digest.as_array());
        push_id(&mut key, &request.operation_id);
        push_id(&mut key, artifact);
        let event_id =
            StableId::new(format!("ds-revoke:{}", Digest32::of_bytes(&key))).map_err(|_| {
                DatasetRevocationError::Registry(ArtifactRegistryError::InternalInvariant)
            })?;
        if !existing.contains(&event_id) {
            if registry.state(artifact) == Some(ArtifactState::Revoked) {
                already_revoked += 1;
                continue;
            }
            if staged.records().len() >= MAX_PREPARED_RECORDS {
                return Err(DatasetRevocationError::Capacity);
            }
        }
        let receipt = staged
            .append(ArtifactEvent::Revoke(StateChange {
                event_id,
                artifact_id: artifact.clone(),
                evaluator_id: request.evaluator_id.clone(),
                reason_digest: request_digest,
            }))
            .map_err(DatasetRevocationError::Registry)?;
        match receipt.disposition {
            RegistryAppendDisposition::Appended => appended += 1,
            RegistryAppendDisposition::IdempotentReplay => replayed += 1,
        }
    }
    let after_head = staged
        .records()
        .last()
        .map_or(Digest32::ZERO, |r| r.chain_digest);
    Ok(PreparedDatasetRevocation {
        registry: staged,
        summary: DatasetRevocationSummary {
            before_head,
            after_head,
            request_digest,
            direct_artifacts: targets,
            appended,
            replayed,
            already_revoked,
            authority: AuthorityPosture::DENY_ALL,
        },
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    // StableId has a checked 128-byte bound.
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "dataset_revocation_tests.rs"]
mod tests;
