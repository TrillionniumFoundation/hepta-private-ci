//! Explicit reconciliation of an uncertain intent CAS. Both attempts use the
//! same external expected value, so a late original and a replacement cannot
//! both win. Current signatures authorize recovery; local files never do.

use std::fs::File;
use std::path::Path;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::ReleaseFrontierV1;
use trnm_release_bundle::pq_release::PqReleaseRoleV1;

use super::FleetReleaseTrustConfig;
use super::PendingUpdate;
use super::ReleaseAuthority;
use super::VerifiedDecisionWindow;
use super::invalid;
use crate::FleetRegistryError;
use crate::ReleaseId;
use crate::ReleaseIntentAnchorV1;
use crate::ReleaseMetadata;
use crate::release_authority_set::record_bytes;
use crate::release_authority_state::JournalEntry;
use crate::release_authority_state::LoadedState;
use crate::release_authority_state::MAX_JOURNAL_ENTRIES;
use crate::release_authority_store::AuthorityFiles;
use crate::release_authority_store::IntentRecoveryFiles;
use crate::release_authority_store::IntentRecoveryWinner;
use crate::release_authority_store::MAX_AUTHORITY_BYTES;
use crate::release_intent_reconciliation_record::IntentReconciliationKind;
use crate::release_intent_reconciliation_record::IntentReconciliationRecord;
use crate::release_intent_reconciliation_record::RetainedIntentProposal;

#[path = "release_authority_reconciliation_complete.rs"]
mod complete;
#[path = "release_authority_reconciliation_load.rs"]
mod load;
#[path = "release_authority_reconciliation_retry.rs"]
mod retry;

pub(crate) struct PendingIntentReconciliation {
    lock: File,
    state: LoadedState,
    original: RetainedIntentProposal,
    files: IntentRecoveryFiles,
    policy_sha256: [u8; 32],
    replacement: Option<(PendingUpdate, IntentReconciliationRecord)>,
    decision_window: Option<VerifiedDecisionWindow>,
}

impl PendingIntentReconciliation {
    pub fn bind_decision_window(
        &mut self,
        not_before_ms: u64,
        expires_at_ms: u64,
    ) -> Result<(), FleetRegistryError> {
        self.decision_window = Some(VerifiedDecisionWindow::new(not_before_ms, expires_at_ms)?);
        Ok(())
    }
    pub fn expected_intent_anchor(&self) -> Option<&ReleaseIntentAnchorV1> {
        self.state
            .intent_anchors
            .get(&self.original.anchor.agent_id)
    }
    pub fn pending_intent_anchor(&self) -> &ReleaseIntentAnchorV1 {
        &self.original.anchor
    }
    pub fn pending_publication_sha256(&self) -> Result<[u8; 32], FleetRegistryError> {
        self.original.pending_publication_sha256()
    }
    pub fn previous_closed_intent_anchor(&self) -> Option<&ReleaseIntentAnchorV1> {
        if let Some(previous) = self.expected_intent_anchor() {
            if previous.is_closed_history()
                && previous.grant_sha256 != self.original.anchor.grant_sha256
            {
                return Some(previous);
            }
        }
        self.state
            .previous_closed_intents
            .get(&self.original.anchor.agent_id)
    }
}

impl ReleaseAuthority {
    pub fn open_intent_recovery(
        state_root: &Path,
        config: FleetReleaseTrustConfig,
    ) -> Result<Self, FleetRegistryError> {
        let mut owner = Self::configured(
            AuthorityFiles::open(state_root.join("pq-release-authority-v1"))?,
            config,
        )?;
        owner.intent_reconciliation_only = true;
        owner.fenced.store(true, Ordering::Release);
        {
            let lock = owner.files.recovery_lock()?;
            let files = owner.files.intent_recovery_files()?;
            if files.original_attempt.is_none()
                && files.original_proposal.is_none()
                && files.replacement_attempt.is_none()
                && files.replacement_proposal.is_none()
            {
                return Err(invalid(
                    "intent reconciliation requires an actual retained attempt",
                ));
            }
            let external = owner.recovery_frontier()?;
            // A known winner may be waiting for completed-only local cleanup.
            // Merely opening this mode never performs that cleanup or dispatch.
            if complete::known_winner(&owner, &files, external)?.is_none() {
                let (_state, original) = load::original(&owner, &files)?;
                let replacement = load::replacement(&owner, &files, &original)?;
                if Some(external) != original.original_attempt.expected
                    && external != original.original_attempt.proposed
                    && replacement
                        .as_ref()
                        .is_none_or(|value| value.proposed != external)
                {
                    return Err(FleetRegistryError::ReleaseAuthorityRollback);
                }
            }
            drop(lock);
        }
        Ok(owner)
    }

    pub fn is_intent_reconciliation(&self) -> bool {
        self.intent_reconciliation_only
    }

    pub fn admit_intent_reconciliation(
        &self,
        policy_sha256: [u8; 32],
    ) -> Result<PendingIntentReconciliation, FleetRegistryError> {
        if !self.intent_reconciliation_only {
            return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
        }
        let lock = self.files.recovery_lock()?;
        let files = self.files.intent_recovery_files()?;
        let (state, original) = load::original(self, &files)?;
        let replacement = match load::replacement(self, &files, &original)? {
            Some(update) => {
                let journal = load::journal(
                    files
                        .replacement_proposal
                        .as_deref()
                        .ok_or(FleetRegistryError::ReleaseAuthorityRecoveryRequired)?,
                )?;
                let Some(JournalEntry::IntentReconciliation { record }) = journal.entries.last()
                else {
                    return Err(invalid("replacement has no exact reconciliation record"));
                };
                Some((update, (**record).clone()))
            }
            None => None,
        };
        let admission = PendingIntentReconciliation {
            lock,
            state,
            original,
            files,
            policy_sha256,
            replacement,
            decision_window: None,
        };
        self.recheck_intent_reconciliation(&admission)?;
        Ok(admission)
    }

    pub fn recheck_intent_reconciliation(
        &self,
        admission: &PendingIntentReconciliation,
    ) -> Result<u64, FleetRegistryError> {
        if !self.intent_reconciliation_only
            || self.files.intent_recovery_files()? != admission.files
            || self.recovery_frontier()? != admission.state.frontier
        {
            return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
        }
        let unix_ms = self.now_unix_ms()?;
        if let Some(window) = admission.decision_window {
            window.check(unix_ms)?;
        }
        let now = unix_ms / 1000;
        if now < admission.state.time_floor || now < admission.original.observed_at {
            return Err(invalid(
                "intent recovery clock regressed behind retained history",
            ));
        }
        let authority = &admission.state.authority;
        authority
            .check_current(
                PqReleaseRoleV1::ProtocolConfiguration,
                admission.policy_sha256,
                admission.state.frontier.checkpoint_sha256,
                now,
            )
            .map_err(|error| {
                invalid(format!(
                    "M15 current intent recovery policy rejected: {error}"
                ))
            })?;
        let set = admission
            .state
            .journal
            .current_set
            .as_ref()
            .ok_or(FleetRegistryError::ReleaseAuthorityRequired)?;
        authority
            .check_current(
                PqReleaseRoleV1::NodeSoftware,
                set.bundle.bundle_digest,
                admission.state.frontier.checkpoint_sha256,
                now,
            )
            .map_err(|error| invalid(format!("M15 current recovery software rejected: {error}")))?;
        Ok(unix_ms)
    }

    pub fn reconciliation_member_projection(
        &self,
        admission: &PendingIntentReconciliation,
        agent: &AgentId,
        release: &ReleaseId,
    ) -> Result<(ReleaseMetadata, [u8; 32]), FleetRegistryError> {
        if agent != &admission.original.anchor.agent_id {
            return Err(invalid("pending intent recovery belongs to another agent"));
        }
        let now = self.recheck_intent_reconciliation(admission)? / 1000;
        self.member_projection(&admission.state, agent, release, now)
    }

    pub fn reconcile_intent(
        &self,
        mut admission: PendingIntentReconciliation,
        next: &ReleaseIntentAnchorV1,
        kind: IntentReconciliationKind,
        recovery_decision_sha256: Option<[u8; 32]>,
        publication_confirmation_sha256: Option<[u8; 32]>,
        expected_anchor_sha256: [u8; 32],
    ) -> Result<(), FleetRegistryError> {
        if admission.replacement.is_some() {
            return Err(invalid(
                "retained replacement requires an explicit exact-publication retry",
            ));
        }
        admission.decision_window.ok_or_else(|| {
            invalid("intent reconciliation requires its verified decision validity window")
        })?;
        let now = self.recheck_intent_reconciliation(&admission)? / 1000;
        let record = IntentReconciliationRecord {
            schema_version: 1,
            kind,
            original: admission.original.clone(),
            anchor: next.clone(),
            policy_sha256: admission.policy_sha256,
            recovery_decision_sha256,
            publication_confirmation_sha256,
            expected_anchor_sha256,
            observed_at: now,
        };
        record.validate_transition(
            admission.expected_intent_anchor(),
            &admission.state.consumed_grants,
        )?;
        if admission.state.journal.entries.len() >= MAX_JOURNAL_ENTRIES {
            return Err(invalid("release security history is full"));
        }
        let mut journal = admission.state.journal.clone();
        journal.generation = admission.original.original_attempt.proposed.generation;
        journal.previous_frontier = Some(admission.state.frontier);
        journal.entries.push(JournalEntry::IntentReconciliation {
            record: Box::new(record),
        });
        let bytes = record_bytes(&journal)?;
        if bytes.len() > MAX_AUTHORITY_BYTES {
            return Err(invalid(
                "intent reconciliation exceeds the original journal bound",
            ));
        }
        let next_frontier = ReleaseFrontierV1 {
            generation: journal.generation,
            initial_root_sha256: self.config.initial_root_sha256,
            checkpoint_sha256: admission.state.frontier.checkpoint_sha256,
            state_sha256: load::hash(&bytes),
        };
        let _ = journal.rebuild(&self.config, next_frontier)?;
        let attempt = record_bytes(&PendingUpdate {
            schema_version: 1,
            expected: Some(admission.state.frontier),
            proposed: next_frontier,
        })?;
        self.files.prepare_intent_reconciliation(&bytes, &attempt)?;
        admission.files.replacement_attempt = Some(attempt);
        admission.files.replacement_proposal = Some(bytes);
        // Large serialization/hashing/fsync may have crossed a signed expiry.
        // Recheck both roles and the original absolute trust RPC bounds here.
        self.recheck_intent_reconciliation(&admission)?;
        if self
            .frontier
            .compare_and_set(
                &self.config.owner_id,
                &Some(admission.state.frontier),
                &Some(next_frontier),
            )
            .is_err()
            || self.recovery_frontier()? != next_frontier
        {
            return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
        }
        self.files
            .finish_intent_winner(IntentRecoveryWinner::ReplacementProposal)?;
        // The explicit-mode object stays fenced even after success. A caller
        // must close it and perform an ordinary authenticated reopen.
        drop(admission.lock);
        Ok(())
    }

    fn recovery_frontier(&self) -> Result<ReleaseFrontierV1, FleetRegistryError> {
        self.frontier
            .load(&self.config.owner_id)
            .map_err(|_| FleetRegistryError::ReleaseAuthorityRecoveryRequired)?
            .ok_or(FleetRegistryError::ReleaseAuthorityRollback)
    }

    pub(super) fn complete_intent_reconciliation_locked(
        &self,
        _lock: &File,
    ) -> Result<(), FleetRegistryError> {
        let files = self.files.intent_recovery_files()?;
        let frontier = self.recovery_frontier()?;
        let winner = complete::known_winner(self, &files, frontier)?
            .ok_or(FleetRegistryError::ReleaseAuthorityRecoveryRequired)?;
        if self.files.intent_recovery_files()? != files || self.recovery_frontier()? != frontier {
            return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
        }
        self.files.finish_intent_winner(winner)
    }
}
