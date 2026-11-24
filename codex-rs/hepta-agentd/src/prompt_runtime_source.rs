//! Current durable registry fencing for staged prompts and each provider claim.

use std::sync::MutexGuard;

use super::*;
use codex_hepta_prompt_registry::PromptRegistrySnapshotV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Revision;

/// Snapshot evidence bound to the exact persisted attachment. This checksum is
/// integrity metadata; authorization still comes from the current durable owner.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RegistrySourceFence {
    revision: u64,
    registry_digest: [u8; 32],
    lifecycle_frontier: u64,
    revocation_frontier: u64,
    generation_vector_digest: [u8; 32],
    model_tuple_digest: [u8; 32],
    snapshot_digest: [u8; 32],
    attachment_binding_digest: [u8; 32],
}

impl RegistrySourceFence {
    fn new(
        snapshot: &PromptRegistrySnapshotV2,
        compiled: &PromptRegistryCompiledContextV2,
        attachment: &PromptRuntimeAttachmentV1,
    ) -> Result<Self, AgentdPromptRuntimeError> {
        snapshot
            .validate()
            .map_err(|_| AgentdPromptRuntimeError::SourceValidationFailed)?;
        if snapshot.snapshot_digest != compiled.compatible.snapshot_digest
            || snapshot.model_tuple_digest != compiled.compatible.model_tuple_digest
        {
            return Err(AgentdPromptRuntimeError::SourceValidationFailed);
        }
        Ok(Self {
            revision: snapshot.revision.get(),
            registry_digest: *snapshot.registry_digest.as_array(),
            lifecycle_frontier: snapshot.lifecycle_frontier,
            revocation_frontier: snapshot.revocation_frontier,
            generation_vector_digest: *snapshot.generation_vector_digest.as_array(),
            model_tuple_digest: *snapshot.model_tuple_digest.as_array(),
            snapshot_digest: *snapshot.snapshot_digest.as_array(),
            attachment_binding_digest: *source_attachment_digest(
                snapshot.snapshot_digest,
                attachment,
            )
            .as_array(),
        })
    }

    pub(super) fn validate(
        &self,
        attachment: &PromptRuntimeAttachmentV1,
    ) -> Result<(), AgentdPromptRuntimeError> {
        let snapshot = PromptRegistrySnapshotV2 {
            revision: Revision::new(self.revision)
                .map_err(|_| AgentdPromptRuntimeError::CorruptState)?,
            registry_digest: Digest32::from_array(self.registry_digest),
            lifecycle_frontier: self.lifecycle_frontier,
            revocation_frontier: self.revocation_frontier,
            generation_vector_digest: Digest32::from_array(self.generation_vector_digest),
            model_tuple_digest: Digest32::from_array(self.model_tuple_digest),
            snapshot_digest: Digest32::from_array(self.snapshot_digest),
            authority: AuthorityPosture::DENY_ALL,
        };
        snapshot
            .validate()
            .map_err(|_| AgentdPromptRuntimeError::CorruptState)?;
        if self.attachment_binding_digest
            != *source_attachment_digest(snapshot.snapshot_digest, attachment).as_array()
        {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
        Ok(())
    }
}

fn source_attachment_digest(
    snapshot_digest: Digest32,
    attachment: &PromptRuntimeAttachmentV1,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.prompt-runtime.registry-source.v1".to_vec();
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.extend_from_slice(attachment.source_binding_digest.as_array());
    Digest32::of_bytes(&bytes)
}

pub(super) fn validate_stage_source(
    registry: Option<&DurablePromptRegistry>,
    state: &PromptRuntimeState,
    key: &PromptRuntimeKey,
) -> Result<(), AgentdPromptRuntimeError> {
    let Some(registry) = registry else {
        return Ok(());
    };
    let source = state
        .stage_sources
        .get(key)
        .ok_or(AgentdPromptRuntimeError::SourceValidationFailed)?;
    let attachment = state
        .staged
        .get(key)
        .ok_or(AgentdPromptRuntimeError::SourceValidationFailed)?;
    source.validate(attachment)?;
    let current = registry
        .registry()
        .map_err(|_| AgentdPromptRuntimeError::SourceValidationFailed)?;
    if current.snapshot_digest() != Digest32::from_array(source.registry_digest) {
        return Err(AgentdPromptRuntimeError::SourceValidationFailed);
    }
    Ok(())
}

impl AgentdPromptRuntimeOwner {
    pub(super) fn lock_source_registry(
        &self,
    ) -> Result<Option<MutexGuard<'_, DurablePromptRegistry>>, AgentdPromptRuntimeError> {
        self.registry
            .as_ref()
            .map(|registry| {
                registry
                    .lock()
                    .map_err(|_| AgentdPromptRuntimeError::StatePoisoned)
            })
            .transpose()
    }

    /// Stage one exact optimizer-exercised/registry-dereferenced context for a
    /// real Codex turn. Only DeveloperInstruction is activated in this profile.
    pub(super) fn stage_compiled_with_source(
        &self,
        thread_id: &str,
        turn_id: &str,
        model: &str,
        requested_deadline_ms: u64,
        compiled: &PromptRegistryCompiledContextV2,
        snapshot: Option<&PromptRegistrySnapshotV2>,
    ) -> Result<PromptRuntimeStageDisposition, AgentdPromptRuntimeError> {
        validate_thread_id(thread_id)?;
        validate_turn_id(turn_id)?;
        validate_model(model)?;
        if requested_deadline_ms == 0 {
            return Err(AgentdPromptRuntimeError::InvalidDeadline);
        }
        compiled
            .validate()
            .map_err(|_| AgentdPromptRuntimeError::SourceValidationFailed)?;
        if compiled.selected_deliveries.is_empty() {
            return Err(AgentdPromptRuntimeError::EmptySelection);
        }

        let mut effective_deadline_ms = requested_deadline_ms;
        let mut fragments = Vec::with_capacity(compiled.selected_deliveries.len());
        for delivery in &compiled.selected_deliveries {
            if delivery.binding.role != PromptRoleV2::DeveloperInstruction {
                return Err(AgentdPromptRuntimeError::UnsupportedPromptRole);
            }
            if let Some(expires_unix_ms) = delivery.binding.expires_unix_ms {
                if expires_unix_ms == 0 {
                    return Err(AgentdPromptRuntimeError::InvalidDeadline);
                }
                effective_deadline_ms = effective_deadline_ms.min(expires_unix_ms);
            }
            let text = std::str::from_utf8(&delivery.payload)
                .map_err(|_| AgentdPromptRuntimeError::PayloadNotUtf8)?;
            fragments.push(
                PromptRuntimeDeveloperFragmentV1::new(text.to_owned())
                    .map_err(|error| AgentdPromptRuntimeError::Adapter(error.to_string()))?,
            );
        }

        let attachment = PromptRuntimeAttachmentV1::new(
            compiled.compiled.receipt().compilation_id().clone(),
            compiled.attachment.attachment_digest(),
            compiled.attachment.payload_digest(),
            model.to_owned(),
            effective_deadline_ms,
            fragments,
        )
        .map_err(|error| AgentdPromptRuntimeError::Adapter(error.to_string()))?;

        let source = snapshot
            .map(|snapshot| RegistrySourceFence::new(snapshot, compiled, &attachment))
            .transpose()?;
        let key = PromptRuntimeKey {
            thread_id: thread_id.to_owned(),
            turn_id: turn_id.to_owned(),
        };
        self.commit_state(|state| {
            if let Some(existing) = state.staged.get(&key) {
                return if existing == &attachment
                    && state.stage_sources.get(&key) == source.as_ref()
                {
                    Ok(PromptRuntimeStageDisposition::Unchanged)
                } else {
                    Err(AgentdPromptRuntimeError::StageConflict)
                };
            }
            if state
                .dispatch_records
                .values()
                .any(|record| dispatch_key(record) == key)
            {
                return Err(AgentdPromptRuntimeError::StageConflict);
            }
            if state.staged.len() >= MAX_STAGED_TURNS {
                return Err(AgentdPromptRuntimeError::CapacityExceeded);
            }
            if let Some(source) = source {
                state.stage_sources.insert(key.clone(), source);
            }
            state.staged.insert(key, attachment);
            Ok(PromptRuntimeStageDisposition::Inserted)
        })
    }
}
