//! Completed-only local recovery, including interruption of marker cleanup.
//! A fresh exact winner makes every CAS with the old expected value conflict.

use codex_hepta_contracts::ReleaseFrontierV1;

use super::super::PendingUpdate;
use super::super::ReleaseAuthority;
use super::load;
use crate::FleetRegistryError;
use crate::release_authority::invalid;
use crate::release_authority_set::record_bytes;
use crate::release_authority_state::Journal;
use crate::release_authority_state::JournalEntry;
use crate::release_authority_store::IntentRecoveryFiles;
use crate::release_authority_store::IntentRecoveryWinner;

fn replacement_update(
    journal: &Journal,
    bytes: &[u8],
) -> Result<PendingUpdate, FleetRegistryError> {
    let Some(JournalEntry::IntentReconciliation { record }) = journal.entries.last() else {
        return Err(invalid(
            "retained replacement is not an intent reconciliation",
        ));
    };
    let expected = record.original.expected()?;
    Ok(PendingUpdate {
        schema_version: 1,
        expected: Some(expected),
        proposed: ReleaseFrontierV1 {
            generation: expected
                .generation
                .checked_add(1)
                .ok_or_else(|| invalid("release generation overflow"))?,
            initial_root_sha256: expected.initial_root_sha256,
            checkpoint_sha256: expected.checkpoint_sha256,
            state_sha256: load::hash(bytes),
        },
    })
}

pub(super) fn known_winner(
    owner: &ReleaseAuthority,
    files: &IntentRecoveryFiles,
    external: ReleaseFrontierV1,
) -> Result<Option<IntentRecoveryWinner>, FleetRegistryError> {
    external
        .validate()
        .map_err(|_| invalid("invalid current recovery frontier"))?;
    if external.initial_root_sha256 != owner.config.initial_root_sha256 {
        return Err(FleetRegistryError::ReleaseAuthorityRollback);
    }
    let mut original = files
        .original_attempt
        .as_deref()
        .map(load::attempt)
        .transpose()?;
    let mut replacement = files
        .replacement_attempt
        .as_deref()
        .map(load::attempt)
        .transpose()?;
    let replacement_journal = files
        .replacement_proposal
        .as_deref()
        .map(load::journal)
        .transpose()?;
    if let (Some(journal), Some(bytes)) = (&replacement_journal, &files.replacement_proposal) {
        let derived = replacement_update(journal, bytes)?;
        if replacement.as_ref().is_some_and(|value| value != &derived) {
            return Err(FleetRegistryError::ReleaseAuthorityRollback);
        }
        replacement = Some(derived);
        let Some(JournalEntry::IntentReconciliation { record }) = journal.entries.last() else {
            return Err(invalid("replacement lacks its typed reconciliation record"));
        };
        if original
            .as_ref()
            .is_some_and(|value| value != &record.original.original_attempt)
        {
            return Err(FleetRegistryError::ReleaseAuthorityRollback);
        }
        original = Some(record.original.original_attempt.clone());
    }
    // Before any winner exists, reading the old frontier says nothing about a
    // delayed CAS. Leave every byte and both attempts untouched.
    if original.as_ref().and_then(|value| value.expected) == Some(external)
        || replacement.as_ref().and_then(|value| value.expected) == Some(external)
    {
        return Ok(None);
    }
    let (winner, bytes) = if load::hash(&files.journal) == external.state_sha256 {
        (IntentRecoveryWinner::Published, files.journal.as_slice())
    } else if let Some(bytes) = files
        .replacement_proposal
        .as_deref()
        .filter(|bytes| load::hash(bytes) == external.state_sha256)
    {
        (IntentRecoveryWinner::ReplacementProposal, bytes)
    } else if let Some(bytes) = files
        .original_proposal
        .as_deref()
        .filter(|bytes| load::hash(bytes) == external.state_sha256)
    {
        (IntentRecoveryWinner::OriginalProposal, bytes)
    } else {
        return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
    };
    let winning = load::journal(bytes)?;
    let state = winning.clone().rebuild(&owner.config, external)?;
    if owner.now()? < state.time_floor {
        return Err(invalid("completed intent recovery clock regressed"));
    }
    match winning.entries.last() {
        Some(JournalEntry::IntentReconciliation { record }) => {
            let derived = replacement_update(&winning, bytes)?;
            if replacement.as_ref().is_some_and(|value| value != &derived)
                || original
                    .as_ref()
                    .is_some_and(|value| value != &record.original.original_attempt)
            {
                return Err(FleetRegistryError::ReleaseAuthorityRollback);
            }
            replacement = Some(derived);
            original = Some(record.original.original_attempt.clone());
            let mut prefix = winning.clone();
            prefix.entries.pop();
            let exact_original = record.original.reconstruct(&prefix)?;
            if files.original_proposal.as_ref().is_some_and(|bytes| {
                record_bytes(&exact_original).map_or(true, |expected| expected != *bytes)
            }) {
                return Err(FleetRegistryError::ReleaseAuthorityRollback);
            }
        }
        Some(JournalEntry::IntentAnchor { .. }) => {
            let expected = winning
                .previous_frontier
                .ok_or_else(|| invalid("winning intent has no predecessor"))?;
            let derived = PendingUpdate {
                schema_version: 1,
                expected: Some(expected),
                proposed: external,
            };
            let _ = load::attempt(&record_bytes(&derived)?)?;
            if original.as_ref().is_some_and(|value| value != &derived) {
                return Err(FleetRegistryError::ReleaseAuthorityRollback);
            }
            if original.is_none()
                && (winner != IntentRecoveryWinner::Published
                    || replacement.is_none()
                    || files.original_proposal.is_some())
            {
                return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
            }
            original = Some(derived);
        }
        _ => {
            return Err(invalid(
                "publication changes cannot use intent-only recovery",
            ));
        }
    }
    let original = original.ok_or(FleetRegistryError::ReleaseAuthorityRecoveryRequired)?;
    if external != original.proposed
        && replacement
            .as_ref()
            .is_none_or(|value| value.proposed != external)
    {
        return Err(FleetRegistryError::ReleaseAuthorityRollback);
    }
    if let Some(replacement) = &replacement
        && (replacement.expected != original.expected
            || replacement.proposed.generation != original.proposed.generation
            || replacement.proposed.initial_root_sha256 != original.proposed.initial_root_sha256
            || replacement.proposed.checkpoint_sha256 != original.proposed.checkpoint_sha256
            || replacement.proposed == original.proposed)
    {
        return Err(FleetRegistryError::ReleaseAuthorityRollback);
    }
    if let Some(bytes) = &files.original_proposal {
        if load::hash(bytes) != original.proposed.state_sha256 {
            return Err(FleetRegistryError::ReleaseAuthorityRollback);
        }
        let journal = load::journal(bytes)?;
        if !matches!(
            journal.entries.last(),
            Some(JournalEntry::IntentAnchor { .. })
        ) {
            return Err(invalid("original proposal is not intent-only"));
        }
        let _ = journal.rebuild(&owner.config, original.proposed)?;
    }
    if let Some(journal) = replacement_journal {
        let update = replacement
            .as_ref()
            .ok_or(FleetRegistryError::ReleaseAuthorityRecoveryRequired)?;
        let _ = journal.rebuild(&owner.config, update.proposed)?;
    } else if replacement.is_some()
        && external == original.proposed
        && (winner != IntentRecoveryWinner::Published || files.original_proposal.is_some())
    {
        return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
    }
    Ok(Some(winner))
}
