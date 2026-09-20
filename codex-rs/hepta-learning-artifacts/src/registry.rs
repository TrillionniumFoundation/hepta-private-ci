use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

use crate::ArtifactEvent;
use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::ArtifactRecord;
use crate::ArtifactRegistryError;
use crate::ArtifactRegistrySnapshot;
use crate::ArtifactState;
use crate::RegistryAppendDisposition;
use crate::RegistryAppendReceipt;
use crate::StateChange;

const MAX_ARTIFACT_BYTES: u64 = 64 * 1024 * 1024;
const MAX_RECORDS: usize = 1_000_000;
const EVENT_DIGEST_DOMAIN: &[u8] = b"hepta.learning-artifact.event.v1";
const CHAIN_DIGEST_DOMAIN: &[u8] = b"hepta.learning-artifact.chain.v1";

#[derive(Clone, Debug)]
struct ArtifactEntry {
    manifest: ArtifactManifest,
    state: ArtifactState,
}

/// Immutable lineage registry. It can classify candidates as eligible but has
/// no selection, activation, promotion or release operation.
#[derive(Clone, Debug, Default)]
pub struct ArtifactRegistry {
    records: Vec<ArtifactRecord>,
    event_digests: BTreeMap<StableId, Digest32>,
    artifacts: BTreeMap<StableId, ArtifactEntry>,
}

impl ArtifactRegistry {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn append(
        &mut self,
        event: ArtifactEvent,
    ) -> Result<RegistryAppendReceipt, ArtifactRegistryError> {
        let event_id = event.event_id().clone();
        let event_digest = digest_event(&event);
        if let Some(existing_digest) = self.event_digests.get(&event_id) {
            if *existing_digest != event_digest {
                return Err(ArtifactRegistryError::IdentityConflict(
                    event_id.to_string(),
                ));
            }
            let existing = self
                .records
                .iter()
                .find(|record| record.event.event_id() == &event_id)
                .ok_or(ArtifactRegistryError::InternalInvariant)?;
            return Ok(receipt(
                existing,
                RegistryAppendDisposition::IdempotentReplay,
            ));
        }

        if self.records.len() >= MAX_RECORDS {
            return Err(ArtifactRegistryError::RecordLimitExceeded);
        }
        self.validate_event(&event)?;
        let sequence_value = u64::try_from(self.records.len())
            .map_err(|_| ArtifactRegistryError::SequenceOverflow)?
            .checked_add(1)
            .ok_or(ArtifactRegistryError::SequenceOverflow)?;
        let sequence = LogicalSequence::new(sequence_value)
            .map_err(|_| ArtifactRegistryError::SequenceOverflow)?;
        let predecessor_chain_digest = self
            .records
            .last()
            .map_or(Digest32::ZERO, |record| record.chain_digest);
        let chain_digest = digest_chain(predecessor_chain_digest, sequence, event_digest);
        let record = ArtifactRecord {
            sequence,
            predecessor_chain_digest,
            event_digest,
            chain_digest,
            event,
        };
        let append_receipt = receipt(&record, RegistryAppendDisposition::Appended);
        self.index_record(&record)?;
        self.records.push(record);
        Ok(append_receipt)
    }

    #[must_use]
    pub fn state(&self, artifact_id: &StableId) -> Option<ArtifactState> {
        self.artifacts.get(artifact_id).map(|entry| entry.state)
    }

    #[must_use]
    pub fn manifest(&self, artifact_id: &StableId) -> Option<&ArtifactManifest> {
        self.artifacts.get(artifact_id).map(|entry| &entry.manifest)
    }

    /// Returns whether this candidate and every predecessor remain in the
    /// candidate state. Quarantine or revocation of an ancestor therefore
    /// cannot be bypassed by a derived artifact.
    #[must_use]
    pub fn is_eligible(&self, artifact_id: &StableId) -> bool {
        self.lineage_is_eligible(artifact_id)
    }

    /// Returns all candidate manifests matching a kind and objective. Ordering
    /// is deterministic by artifact identity. No winner is selected.
    #[must_use]
    pub fn eligible_candidates(
        &self,
        kind: ArtifactKind,
        objective_digest: Digest32,
    ) -> Vec<&ArtifactManifest> {
        self.artifacts
            .iter()
            .filter(|(artifact_id, entry)| {
                entry.manifest.kind == kind
                    && entry.manifest.objective_digest == objective_digest
                    && self.lineage_is_eligible(artifact_id)
            })
            .map(|(_, entry)| &entry.manifest)
            .collect()
    }

    #[must_use]
    pub fn records(&self) -> &[ArtifactRecord] {
        &self.records
    }

    #[must_use]
    pub fn snapshot(&self) -> ArtifactRegistrySnapshot {
        ArtifactRegistrySnapshot {
            records: self.records.clone(),
            head_digest: self
                .records
                .last()
                .map_or(Digest32::ZERO, |record| record.chain_digest),
        }
    }

    pub fn from_snapshot(
        snapshot: ArtifactRegistrySnapshot,
    ) -> Result<Self, ArtifactRegistryError> {
        let expected_head = snapshot.head_digest;
        let mut registry = Self::new();
        for expected in snapshot.records {
            let receipt = registry.append(expected.event.clone())?;
            let actual = registry
                .records
                .last()
                .ok_or(ArtifactRegistryError::InternalInvariant)?;
            if actual != &expected || receipt.disposition != RegistryAppendDisposition::Appended {
                return Err(ArtifactRegistryError::SnapshotRecordMismatch(
                    expected.sequence.get(),
                ));
            }
        }
        let actual_head = registry
            .records
            .last()
            .map_or(Digest32::ZERO, |record| record.chain_digest);
        if actual_head != expected_head {
            return Err(ArtifactRegistryError::SnapshotHeadMismatch);
        }
        Ok(registry)
    }

    fn validate_event(&self, event: &ArtifactEvent) -> Result<(), ArtifactRegistryError> {
        match event {
            ArtifactEvent::Register { manifest, .. } => self.validate_manifest(manifest),
            ArtifactEvent::Quarantine(change) => {
                self.validate_state_change(change, ArtifactState::Quarantined)
            }
            ArtifactEvent::Revoke(change) => {
                self.validate_state_change(change, ArtifactState::Revoked)
            }
        }
    }

    fn validate_manifest(&self, manifest: &ArtifactManifest) -> Result<(), ArtifactRegistryError> {
        validate_manifest_digests(manifest)?;
        if manifest.encoded_size_bytes == 0 {
            return Err(ArtifactRegistryError::ZeroEncodedSize);
        }
        if manifest.encoded_size_bytes > MAX_ARTIFACT_BYTES {
            return Err(ArtifactRegistryError::ArtifactTooLarge {
                actual: manifest.encoded_size_bytes,
                maximum: MAX_ARTIFACT_BYTES,
            });
        }
        if self.artifacts.contains_key(&manifest.artifact_id) {
            return Err(ArtifactRegistryError::ArtifactAlreadyExists(
                manifest.artifact_id.to_string(),
            ));
        }
        if let Some(predecessor_id) = &manifest.predecessor_id {
            let predecessor = self.artifacts.get(predecessor_id).ok_or_else(|| {
                ArtifactRegistryError::PredecessorNotFound(predecessor_id.to_string())
            })?;
            if !self.lineage_is_eligible(predecessor_id) {
                return Err(ArtifactRegistryError::PredecessorUnavailable(
                    predecessor_id.to_string(),
                ));
            }
            if manifest.generation <= predecessor.manifest.generation {
                return Err(ArtifactRegistryError::GenerationNotAdvanced);
            }
            if manifest.objective_digest != predecessor.manifest.objective_digest {
                return Err(ArtifactRegistryError::ObjectiveLineageMismatch);
            }
            if manifest.kind != predecessor.manifest.kind {
                return Err(ArtifactRegistryError::ArtifactKindLineageMismatch);
            }
        }
        Ok(())
    }

    fn validate_state_change(
        &self,
        change: &StateChange,
        next: ArtifactState,
    ) -> Result<(), ArtifactRegistryError> {
        if change.reason_digest.is_zero() {
            return Err(ArtifactRegistryError::EmptyDigest("state-change reason"));
        }
        let entry = self.artifacts.get(&change.artifact_id).ok_or_else(|| {
            ArtifactRegistryError::ArtifactNotFound(change.artifact_id.to_string())
        })?;
        if entry.manifest.producer_id == change.evaluator_id {
            return Err(ArtifactRegistryError::ProducerSelfEvaluates(
                change.artifact_id.to_string(),
            ));
        }
        if entry.state == ArtifactState::Revoked {
            return Err(ArtifactRegistryError::RevokedArtifactCannotTransition(
                change.artifact_id.to_string(),
            ));
        }
        if entry.state == next {
            return Err(ArtifactRegistryError::StateAlreadyApplied(
                change.artifact_id.to_string(),
            ));
        }
        Ok(())
    }

    fn lineage_is_eligible(&self, artifact_id: &StableId) -> bool {
        let mut current = Some(artifact_id);
        let mut visited = BTreeSet::new();
        while let Some(id) = current {
            if !visited.insert(id.clone()) {
                return false;
            }
            let Some(entry) = self.artifacts.get(id) else {
                return false;
            };
            if entry.state != ArtifactState::Candidate {
                return false;
            }
            current = entry.manifest.predecessor_id.as_ref();
        }
        true
    }

    fn index_record(&mut self, record: &ArtifactRecord) -> Result<(), ArtifactRegistryError> {
        self.event_digests
            .insert(record.event.event_id().clone(), record.event_digest);
        match &record.event {
            ArtifactEvent::Register { manifest, .. } => {
                self.artifacts.insert(
                    manifest.artifact_id.clone(),
                    ArtifactEntry {
                        manifest: manifest.clone(),
                        state: ArtifactState::Candidate,
                    },
                );
            }
            ArtifactEvent::Quarantine(change) => {
                let entry = self
                    .artifacts
                    .get_mut(&change.artifact_id)
                    .ok_or(ArtifactRegistryError::InternalInvariant)?;
                entry.state = ArtifactState::Quarantined;
            }
            ArtifactEvent::Revoke(change) => {
                let entry = self
                    .artifacts
                    .get_mut(&change.artifact_id)
                    .ok_or(ArtifactRegistryError::InternalInvariant)?;
                entry.state = ArtifactState::Revoked;
            }
        }
        Ok(())
    }
}

fn validate_manifest_digests(manifest: &ArtifactManifest) -> Result<(), ArtifactRegistryError> {
    for (kind, digest) in [
        ("content", manifest.content_digest),
        ("objective", manifest.objective_digest),
        ("support", manifest.support_digest),
        ("compatibility", manifest.compatibility_digest),
    ] {
        if digest.is_zero() {
            return Err(ArtifactRegistryError::EmptyDigest(kind));
        }
    }
    Ok(())
}

fn receipt(
    record: &ArtifactRecord,
    disposition: RegistryAppendDisposition,
) -> RegistryAppendReceipt {
    RegistryAppendReceipt {
        disposition,
        sequence: record.sequence,
        event_digest: record.event_digest,
        chain_digest: record.chain_digest,
    }
}

fn event_tag(event: &ArtifactEvent) -> u8 {
    match event {
        ArtifactEvent::Register { .. } => 0,
        ArtifactEvent::Quarantine(_) => 1,
        ArtifactEvent::Revoke(_) => 2,
    }
}

fn digest_event(event: &ArtifactEvent) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(EVENT_DIGEST_DOMAIN);
    bytes.push(event_tag(event));
    match event {
        ArtifactEvent::Register { event_id, manifest } => {
            push_id(&mut bytes, event_id);
            push_manifest(&mut bytes, manifest);
        }
        ArtifactEvent::Quarantine(change) | ArtifactEvent::Revoke(change) => {
            push_state_change(&mut bytes, change);
        }
    }
    Digest32::of_bytes(&bytes)
}

fn digest_chain(
    predecessor: Digest32,
    sequence: LogicalSequence,
    event_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::with_capacity(CHAIN_DIGEST_DOMAIN.len() + 72);
    bytes.extend_from_slice(CHAIN_DIGEST_DOMAIN);
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(&sequence.get().to_be_bytes());
    bytes.extend_from_slice(event_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_manifest(bytes: &mut Vec<u8>, value: &ArtifactManifest) {
    push_id(bytes, &value.artifact_id);
    bytes.push(value.kind.tag());
    bytes.extend_from_slice(&value.generation.get().to_be_bytes());
    match &value.predecessor_id {
        Some(id) => {
            bytes.push(1);
            push_id(bytes, id);
        }
        None => bytes.push(0),
    }
    push_digest(bytes, value.content_digest);
    push_digest(bytes, value.objective_digest);
    push_digest(bytes, value.support_digest);
    push_id(bytes, &value.producer_id);
    push_digest(bytes, value.compatibility_digest);
    bytes.extend_from_slice(&value.encoded_size_bytes.to_be_bytes());
}

fn push_state_change(bytes: &mut Vec<u8>, value: &StateChange) {
    push_id(bytes, &value.event_id);
    push_id(bytes, &value.artifact_id);
    push_id(bytes, &value.evaluator_id);
    push_digest(bytes, value.reason_digest);
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    let converted = u32::try_from(value).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&converted.to_be_bytes());
}

#[cfg(test)]
#[path = "registry_tests.rs"]
mod tests;
