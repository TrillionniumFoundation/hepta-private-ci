//! Exact native admission followed by bounded irreversible state changes.
//! The same publication receipt and signed CURRENT bind the complete suffix.
use crate::ArtifactEvent;
use crate::ArtifactPublicationError;
use crate::ArtifactPublicationIntentV1;
use crate::ArtifactRegistry;

const MAX_PUBLICATION_STATE_CHANGES: usize = 64;

pub(crate) fn validate_registry_suffix(
    intent: &ArtifactPublicationIntentV1,
    registry: &ArtifactRegistry,
) -> Result<usize, ArtifactPublicationError> {
    let records = registry.records();
    let start = records
        .iter()
        .position(|record| {
            record.predecessor_chain_digest == intent.expected_registry_predecessor_head
        })
        .ok_or(ArtifactPublicationError::RegistryPredecessorMismatch)?;
    if records.len() - start > MAX_PUBLICATION_STATE_CHANGES + 1 {
        return Err(ArtifactPublicationError::RegistryProjectionMismatch);
    }
    let v2 = &intent.admission.validated_manifest.manifest;
    let ArtifactEvent::Register { manifest: v1, .. } = &records[start].event else {
        return Err(ArtifactPublicationError::RegistryProjectionMismatch);
    };
    let predecessor = if v2.predecessor_ids.len() == 1 {
        v2.predecessor_ids.first()
    } else {
        None
    };
    if v1.artifact_id != v2.artifact_id
        || v1.kind != v2.kind
        || v1.generation != v2.generation
        || v1.predecessor_id.as_ref() != predecessor
        || v1.content_digest != v2.bytes_digest
        || v1.objective_digest != v2.objective_class_digest
        || v1.support_digest != intent.admission.validated_manifest.manifest_digest
        || v1.producer_id != v2.producer_id
        || v1.compatibility_digest != v2.compatibility_digest
        || v1.encoded_size_bytes != v2.encoded_size_bytes
    {
        return Err(ArtifactPublicationError::RegistryProjectionMismatch);
    }
    for record in &records[start + 1..] {
        let change = match &record.event {
            ArtifactEvent::Quarantine(change) | ArtifactEvent::Revoke(change) => change,
            ArtifactEvent::Register { .. } => {
                return Err(ArtifactPublicationError::RegistryProjectionMismatch);
            }
        };
        // A suffix cannot disable the newly admitted candidate or introduce a
        // different candidate. Only already registered artifacts may be fenced.
        if change.artifact_id == v2.artifact_id
            || !records[..start].iter().any(|prior| {
                matches!(&prior.event, ArtifactEvent::Register { manifest, .. }
                if manifest.artifact_id == change.artifact_id)
            })
        {
            return Err(ArtifactPublicationError::RegistryProjectionMismatch);
        }
    }
    Ok(start)
}

pub(crate) fn stage_state_changes(
    intent: &ArtifactPublicationIntentV1,
    registry: &mut ArtifactRegistry,
    changes: &[ArtifactEvent],
) -> Result<(), crate::ArtifactOwnerHostError> {
    if changes.len() > MAX_PUBLICATION_STATE_CHANGES {
        return Err(crate::ArtifactOwnerHostError::Capacity);
    }
    if changes.is_empty() {
        validate_registry_suffix(intent, registry)?;
        return Ok(());
    }
    let mut staged = registry.clone();
    for change in changes {
        staged.append(change.clone())?;
    }
    validate_registry_suffix(intent, &staged)?;
    *registry = staged;
    Ok(())
}
