use sha2::Digest;
use sha2::Sha256;

use super::super::PendingUpdate;
use super::super::ReleaseAuthority;
use crate::FleetRegistryError;
use crate::release_authority::invalid;
use crate::release_authority_set::record_bytes;
use crate::release_authority_state::Journal;
use crate::release_authority_state::JournalEntry;
use crate::release_authority_state::LoadedState;
use crate::release_authority_store::IntentRecoveryFiles;
use crate::release_intent_reconciliation_record::RetainedIntentProposal;

pub(super) fn hash(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}

pub(super) fn journal(bytes: &[u8]) -> Result<Journal, FleetRegistryError> {
    let value: Journal =
        serde_json::from_slice(bytes).map_err(|_| invalid("invalid retained intent journal"))?;
    if record_bytes(&value)? != bytes {
        return Err(invalid(
            "intent recovery requires the exact canonical owner journal",
        ));
    }
    Ok(value)
}

pub(super) fn attempt(bytes: &[u8]) -> Result<PendingUpdate, FleetRegistryError> {
    let value: PendingUpdate =
        serde_json::from_slice(bytes).map_err(|_| invalid("invalid retained intent attempt"))?;
    let expected = value
        .expected
        .ok_or_else(|| invalid("bootstrap cannot be reconciled as an intent"))?;
    if value.schema_version != 1
        || record_bytes(&value)? != bytes
        || expected.validate().is_err()
        || value.proposed.validate().is_err()
        || expected.generation.checked_add(1) != Some(value.proposed.generation)
        || expected.initial_root_sha256 != value.proposed.initial_root_sha256
        || expected.checkpoint_sha256 != value.proposed.checkpoint_sha256
    {
        return Err(invalid(
            "intent attempt changed publication lineage or checkpoint",
        ));
    }
    Ok(value)
}

pub(super) fn original(
    owner: &ReleaseAuthority,
    files: &IntentRecoveryFiles,
) -> Result<(LoadedState, RetainedIntentProposal), FleetRegistryError> {
    let attempt = attempt(
        files
            .original_attempt
            .as_deref()
            .ok_or(FleetRegistryError::ReleaseAuthorityRecoveryRequired)?,
    )?;
    let expected = attempt
        .expected
        .ok_or(FleetRegistryError::ReleaseAuthorityRecoveryRequired)?;
    if hash(&files.journal) != expected.state_sha256
        || expected.initial_root_sha256 != owner.config.initial_root_sha256
    {
        return Err(FleetRegistryError::ReleaseAuthorityRollback);
    }
    let old = journal(&files.journal)?;
    let bytes = files
        .original_proposal
        .as_deref()
        .ok_or(FleetRegistryError::ReleaseAuthorityRecoveryRequired)?;
    if hash(bytes) != attempt.proposed.state_sha256 {
        return Err(FleetRegistryError::ReleaseAuthorityRollback);
    }
    let proposed = journal(bytes)?;
    let retained = RetainedIntentProposal::capture(attempt.clone(), &old, &proposed)?;
    // Both the committed past and the actual retained proposal are rebuilt
    // with their distinct exact pins. Recovery never promotes the proposal.
    let state = old.rebuild(&owner.config, expected)?;
    let _ = proposed.rebuild(&owner.config, attempt.proposed)?;
    if retained.observed_at < state.time_floor {
        return Err(invalid("original intent proposal clock regressed"));
    }
    Ok((state, retained))
}

pub(super) fn replacement(
    owner: &ReleaseAuthority,
    files: &IntentRecoveryFiles,
    original: &RetainedIntentProposal,
) -> Result<Option<PendingUpdate>, FleetRegistryError> {
    let Some(bytes) = files.replacement_proposal.as_deref() else {
        if files.replacement_attempt.is_some() {
            return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
        }
        return Ok(None);
    };
    let value = journal(bytes)?;
    let Some(JournalEntry::IntentReconciliation { record }) = value.entries.last() else {
        return Err(invalid(
            "replacement is not an explicit intent reconciliation",
        ));
    };
    if &record.original != original {
        return Err(FleetRegistryError::ReleaseAuthorityRollback);
    }
    let update = PendingUpdate {
        schema_version: 1,
        expected: original.original_attempt.expected,
        proposed: codex_hepta_contracts::ReleaseFrontierV1 {
            generation: original.original_attempt.proposed.generation,
            initial_root_sha256: original.original_attempt.proposed.initial_root_sha256,
            checkpoint_sha256: original.original_attempt.proposed.checkpoint_sha256,
            state_sha256: hash(bytes),
        },
    };
    if let Some(bytes) = files.replacement_attempt.as_deref()
        && attempt(bytes)? != update
    {
        return Err(FleetRegistryError::ReleaseAuthorityRollback);
    }
    let _ = value.rebuild(&owner.config, update.proposed)?;
    Ok(Some(update))
}
