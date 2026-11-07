//! A journal prefix plus this bounded delta reconstructs the original uncertain
//! intent proposal. No record recursively embeds the complete journal.

use std::collections::BTreeSet;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::ReleaseFrontierV1;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::FleetRegistryError;
use crate::ReleaseIntentAnchorV1;
use crate::ReleaseIntentPhaseV1;
use crate::ReleaseIntentWitnessKindV1;
use crate::release_authority::PendingUpdate;
use crate::release_authority::invalid;
use crate::release_authority_set::ReleaseSetRecord;
use crate::release_authority_set::record_bytes;
use crate::release_authority_state::Journal;
use crate::release_authority_state::JournalEntry;
use crate::release_authority_store::MAX_SET_BYTES;
use crate::release_intent_anchor::AnchorMutation;
use crate::release_intent_anchor::validate_transition;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RetainedIntentProposal {
    pub original_attempt: PendingUpdate,
    pub committed_previous_frontier: Option<ReleaseFrontierV1>,
    pub original_current_set: Option<ReleaseSetRecord>,
    pub anchor: ReleaseIntentAnchorV1,
    pub authorization: AnchorMutation,
    pub observed_at: u64,
}

impl RetainedIntentProposal {
    pub fn pending_publication_sha256(&self) -> Result<[u8; 32], FleetRegistryError> {
        let mut digest = Sha256::new();
        digest.update(b"hepta.fleet.release-intent-pending-update.v1\0");
        digest.update(
            serde_json::to_vec(&self.original_attempt)
                .map_err(|_| invalid("cannot encode pending intent publication"))?,
        );
        Ok(digest.finalize().into())
    }

    pub fn capture(
        attempt: PendingUpdate,
        old: &Journal,
        proposed: &Journal,
    ) -> Result<Self, FleetRegistryError> {
        let Some(JournalEntry::IntentAnchor {
            anchor,
            authorization,
            observed_at,
        }) = proposed.entries.last()
        else {
            return Err(invalid(
                "only an exact typed intent proposal can be reconciled",
            ));
        };
        let retained = Self {
            original_attempt: attempt,
            committed_previous_frontier: old.previous_frontier,
            original_current_set: old.current_set.clone(),
            anchor: anchor.clone(),
            authorization: *authorization,
            observed_at: *observed_at,
        };
        if retained.reconstruct(old)? != *proposed {
            return Err(FleetRegistryError::ReleaseAuthorityRollback);
        }
        Ok(retained)
    }

    pub fn expected(&self) -> Result<ReleaseFrontierV1, FleetRegistryError> {
        let expected = self
            .original_attempt
            .expected
            .ok_or_else(|| invalid("release bootstrap is not an intent reconciliation"))?;
        expected
            .validate()
            .map_err(|_| invalid("invalid original expected frontier"))?;
        let next = self.original_attempt.proposed;
        next.validate()
            .map_err(|_| invalid("invalid original proposed frontier"))?;
        if self.original_attempt.schema_version != 1
            || expected.generation.checked_add(1) != Some(next.generation)
            || next.initial_root_sha256 != expected.initial_root_sha256
            || next.checkpoint_sha256 != expected.checkpoint_sha256
        {
            return Err(invalid("uncertain proposal changed publication authority"));
        }
        Ok(expected)
    }

    pub fn old_journal(&self, prefix: &Journal) -> Result<Journal, FleetRegistryError> {
        let expected = self.expected()?;
        if self
            .original_current_set
            .as_ref()
            .is_some_and(|set| record_bytes(set).map_or(true, |bytes| bytes.len() > MAX_SET_BYTES))
        {
            return Err(invalid("retained release set exceeds its original bound"));
        }
        let mut old = prefix.clone();
        old.generation = expected.generation;
        old.previous_frontier = self.committed_previous_frontier;
        old.current_set = self.original_current_set.clone();
        if old.entries.len() as u64 + 1 != old.generation
            || <[u8; 32]>::from(Sha256::digest(record_bytes(&old)?)) != expected.state_sha256
        {
            return Err(FleetRegistryError::ReleaseAuthorityRollback);
        }
        Ok(old)
    }

    pub fn reconstruct(&self, prefix: &Journal) -> Result<Journal, FleetRegistryError> {
        let mut proposed = self.old_journal(prefix)?;
        proposed.generation = self.original_attempt.proposed.generation;
        proposed.previous_frontier = self.original_attempt.expected;
        proposed.entries.push(JournalEntry::IntentAnchor {
            anchor: self.anchor.clone(),
            authorization: self.authorization,
            observed_at: self.observed_at,
        });
        if <[u8; 32]>::from(Sha256::digest(record_bytes(&proposed)?))
            != self.original_attempt.proposed.state_sha256
        {
            return Err(FleetRegistryError::ReleaseAuthorityRollback);
        }
        Ok(proposed)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum IntentReconciliationKind {
    AbandonUnknown,
    ConfirmCompletion,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct IntentReconciliationRecord {
    pub schema_version: u32,
    pub kind: IntentReconciliationKind,
    pub original: RetainedIntentProposal,
    pub anchor: ReleaseIntentAnchorV1,
    pub policy_sha256: [u8; 32],
    pub recovery_decision_sha256: Option<[u8; 32]>,
    pub publication_confirmation_sha256: Option<[u8; 32]>,
    pub expected_anchor_sha256: [u8; 32],
    pub observed_at: u64,
}

impl IntentReconciliationRecord {
    pub fn validate_transition(
        &self,
        previous: Option<&ReleaseIntentAnchorV1>,
        consumed: &BTreeSet<(AgentId, [u8; 32])>,
    ) -> Result<(), FleetRegistryError> {
        let expected_observation = match previous {
            Some(anchor) => anchor.sha256()?,
            None => ReleaseIntentAnchorV1::absent_sha256(&self.anchor.agent_id),
        };
        self.anchor.validate()?;
        self.original.expected()?;
        validate_transition(
            previous,
            &self.original.anchor,
            self.original.authorization,
            consumed,
        )?;
        let explicit_first_unknown =
            matches!(self.original.authorization, AnchorMutation::Recovery { .. })
                && self.original.anchor.phase == ReleaseIntentPhaseV1::Aborted
                && self
                    .original
                    .anchor
                    .terminal_witness
                    .as_ref()
                    .is_some_and(|witness| {
                        witness.kind == ReleaseIntentWitnessKindV1::AbandonUnknown
                            && witness.publication_confirmation_sha256.is_none()
                    })
                && self.publication_confirmation_sha256.is_some();
        if self.schema_version != 1
            || self.policy_sha256 == [0; 32]
            || self.recovery_decision_sha256 == Some([0; 32])
            || self.publication_confirmation_sha256 == Some([0; 32])
            || (self.publication_confirmation_sha256.is_some()
                && self.publication_confirmation_sha256 == self.recovery_decision_sha256)
            || self.expected_anchor_sha256 != expected_observation
            || self.observed_at < self.original.observed_at
            || (previous.is_none()
                && self.original.anchor.phase != ReleaseIntentPhaseV1::Prepared
                && !explicit_first_unknown)
            || self.anchor.agent_id != self.original.anchor.agent_id
            || self.anchor.generation != self.original.anchor.generation
            || self.anchor.grant_sha256 != self.original.anchor.grant_sha256
            || self.anchor.original_grant_policy_sha256
                != self.original.anchor.original_grant_policy_sha256
        {
            return Err(invalid(
                "intent reconciliation must bind its original operation and explicit unknown disposition",
            ));
        }
        match self.kind {
            IntentReconciliationKind::AbandonUnknown => {
                if matches!(
                    self.original.anchor.phase,
                    ReleaseIntentPhaseV1::Committed | ReleaseIntentPhaseV1::RolledBack
                ) || self.anchor.phase != ReleaseIntentPhaseV1::Aborted
                    || self.recovery_decision_sha256.is_none()
                    || !self
                        .anchor
                        .terminal_witness
                        .as_ref()
                        .is_some_and(|witness| {
                            witness.kind == ReleaseIntentWitnessKindV1::AbandonUnknown
                                && witness.recovery_decision_sha256 == self.recovery_decision_sha256
                                && witness.publication_confirmation_sha256
                                    == self.publication_confirmation_sha256
                        })
                {
                    return Err(invalid("unknown reconciliation cannot assert completion"));
                }
                if self.original.anchor.is_closed_history() {
                    let mut exact = self.original.anchor.clone();
                    let witness = exact
                        .terminal_witness
                        .as_mut()
                        .ok_or_else(|| invalid("retained unknown decision has no witness"))?;
                    if self.publication_confirmation_sha256.is_none()
                        || witness.publication_confirmation_sha256.is_some()
                    {
                        return Err(invalid(
                            "retained unknown decision requires a fresh publication confirmation",
                        ));
                    }
                    witness.publication_confirmation_sha256 = self.publication_confirmation_sha256;
                    if exact != self.anchor {
                        return Err(invalid(
                            "unknown confirmation changed the already durable decision or history",
                        ));
                    }
                }
            }
            IntentReconciliationKind::ConfirmCompletion => {
                let mut exact = self.original.anchor.clone();
                let witness = exact
                    .terminal_witness
                    .as_mut()
                    .ok_or_else(|| invalid("pending intent has no completion witness"))?;
                if !matches!(
                    exact.phase,
                    ReleaseIntentPhaseV1::Committed | ReleaseIntentPhaseV1::RolledBack
                ) || witness.kind != ReleaseIntentWitnessKindV1::CompletedReleaseCas
                    || witness.publication_confirmation_sha256.is_some()
                    || witness.recovery_decision_sha256 != self.recovery_decision_sha256
                    || self.publication_confirmation_sha256.is_none()
                {
                    return Err(invalid(
                        "completion confirmation requires an actual pending terminal witness",
                    ));
                }
                witness.publication_confirmation_sha256 = self.publication_confirmation_sha256;
                if exact != self.anchor {
                    return Err(invalid(
                        "completion confirmation changed the retained intent or effect witness",
                    ));
                }
            }
        }
        Ok(())
    }
}
