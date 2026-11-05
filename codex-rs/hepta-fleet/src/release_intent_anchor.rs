//! Exact H7 owner snapshots in the existing external release frontier. These
//! records attest to retained history; they are not process launch capabilities.

use std::collections::BTreeSet;

use codex_hepta_contracts::AgentId;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::FleetRegistryError;
use crate::release_authority::invalid;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReleaseIntentPhaseV1 {
    Prepared,
    Queued,
    RecoveryRequired,
    Committed,
    RolledBack,
    Aborted,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReleaseIntentWitnessKindV1 {
    CompletedReleaseCas,
    /// A signed decision to retain an unknown effect as history. This does not
    /// assert that the original effect succeeded, failed, or never occurred.
    AbandonUnknown,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReleaseIntentTerminalWitnessV1 {
    pub kind: ReleaseIntentWitnessKindV1,
    pub transaction_sha256: [u8; 32],
    pub release_state_sha256: [u8; 32],
    pub release_state_generation: u64,
    pub recovery_decision_sha256: Option<[u8; 32]>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub publication_confirmation_sha256: Option<[u8; 32]>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReleaseIntentAnchorV1 {
    pub schema_version: u32,
    pub agent_id: AgentId,
    /// Per-agent generation, distinct from the complete publication frontier.
    pub generation: u64,
    pub phase: ReleaseIntentPhaseV1,
    /// Digest of the entire canonical signed-intent snapshot, including its
    /// original epoch, source/target, CAS inputs, and complete unknown history.
    pub intent_sha256: [u8; 32],
    pub grant_sha256: [u8; 32],
    /// None describes an explicitly recovered legacy grant. Current recovery
    /// authority never relabels that historical grant as PQ-authorized.
    pub original_grant_policy_sha256: Option<[u8; 32]>,
    pub terminal_witness: Option<ReleaseIntentTerminalWitnessV1>,
}

impl ReleaseIntentAnchorV1 {
    /// An absence observation has a distinct domain; generation zero never
    /// becomes a valid anchor. Only explicit recovery of an exact pending
    /// Prepared snapshot may use this observation as its signed predecessor.
    pub fn absent_sha256(agent_id: &AgentId) -> [u8; 32] {
        let text = agent_id.to_string();
        let mut digest = Sha256::new();
        digest.update(b"hepta.fleet.release-intent-anchor.absent.v1\0");
        digest.update((text.len() as u64).to_be_bytes());
        digest.update(text.as_bytes());
        digest.finalize().into()
    }

    /// Digest used by the explicitly signed predecessor recovery observation.
    /// The domain is followed by this validated DTO's compact serde JSON bytes,
    /// without a trailing newline. It binds every field, including the witness.
    pub fn sha256(&self) -> Result<[u8; 32], FleetRegistryError> {
        self.validate()?;
        let mut digest = Sha256::new();
        digest.update(b"hepta.fleet.release-intent-anchor.v1\0");
        digest
            .update(serde_json::to_vec(self).map_err(|_| invalid("cannot encode intent anchor"))?);
        Ok(digest.finalize().into())
    }

    pub fn validate(&self) -> Result<(), FleetRegistryError> {
        if self.schema_version != 1
            || self.generation == 0
            || self.intent_sha256 == [0; 32]
            || self.grant_sha256 == [0; 32]
            || self.original_grant_policy_sha256 == Some([0; 32])
        {
            return Err(invalid("malformed release intent anchor"));
        }
        if let Some(witness) = &self.terminal_witness {
            if witness.transaction_sha256 == [0; 32]
                || witness.release_state_sha256 == [0; 32]
                || witness.release_state_generation == 0
                || witness.recovery_decision_sha256 == Some([0; 32])
                || witness.publication_confirmation_sha256 == Some([0; 32])
                || (witness.kind == ReleaseIntentWitnessKindV1::AbandonUnknown
                    && witness.recovery_decision_sha256.is_none())
            {
                return Err(invalid("malformed release intent completion witness"));
            }
        }
        match (self.phase, self.terminal_witness.as_ref().map(|w| w.kind)) {
            (
                ReleaseIntentPhaseV1::Committed | ReleaseIntentPhaseV1::RolledBack,
                Some(ReleaseIntentWitnessKindV1::CompletedReleaseCas),
            )
            | (
                ReleaseIntentPhaseV1::Aborted,
                None | Some(ReleaseIntentWitnessKindV1::AbandonUnknown),
            )
            | (
                ReleaseIntentPhaseV1::Prepared
                | ReleaseIntentPhaseV1::Queued
                | ReleaseIntentPhaseV1::RecoveryRequired,
                None,
            ) => Ok(()),
            _ => Err(invalid("intent phase and completion witness disagree")),
        }
    }

    /// A local abort without an explicit signed unknown-effect disposition
    /// remains quarantined and cannot be a predecessor for another grant.
    pub fn is_closed_history(&self) -> bool {
        matches!(
            self.phase,
            ReleaseIntentPhaseV1::Committed | ReleaseIntentPhaseV1::RolledBack
        ) || (self.phase == ReleaseIntentPhaseV1::Aborted
            && self
                .terminal_witness
                .as_ref()
                .is_some_and(|w| w.kind == ReleaseIntentWitnessKindV1::AbandonUnknown))
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum AnchorMutation {
    Current {
        policy_sha256: [u8; 32],
    },
    Recovery {
        policy_sha256: [u8; 32],
        decision_sha256: [u8; 32],
    },
    UnanchoredRecovery {
        policy_sha256: [u8; 32],
        decision_sha256: [u8; 32],
        predecessor_anchor_sha256: [u8; 32],
    },
    ConfirmAbandonUnknown {
        policy_sha256: [u8; 32],
        confirmation_sha256: [u8; 32],
        expected_anchor_sha256: [u8; 32],
    },
    Historical,
}

impl AnchorMutation {
    pub(crate) fn policy(self) -> Option<[u8; 32]> {
        match self {
            Self::Current { policy_sha256 }
            | Self::Recovery { policy_sha256, .. }
            | Self::UnanchoredRecovery { policy_sha256, .. } => Some(policy_sha256),
            Self::ConfirmAbandonUnknown { policy_sha256, .. } => Some(policy_sha256),
            Self::Historical => None,
        }
    }

    fn validate(self) -> Result<(), FleetRegistryError> {
        if self.policy() == Some([0; 32])
            || matches!(self, Self::Recovery { decision_sha256, .. }
                | Self::UnanchoredRecovery { decision_sha256, .. }
                if decision_sha256 == [0; 32])
            || matches!(self, Self::UnanchoredRecovery { predecessor_anchor_sha256, .. }
                if predecessor_anchor_sha256 == [0; 32])
            || matches!(self, Self::ConfirmAbandonUnknown { confirmation_sha256, expected_anchor_sha256, .. }
                if confirmation_sha256 == [0; 32] || expected_anchor_sha256 == [0; 32])
        {
            return Err(invalid("malformed intent anchor authorization context"));
        }
        Ok(())
    }
}

/// Called for both actual updates and replay. Repeated identical observations
/// are handled without an event by the owner, never by erasing an uncertain CAS.
pub(crate) fn validate_transition(
    previous: Option<&ReleaseIntentAnchorV1>,
    next: &ReleaseIntentAnchorV1,
    mutation: AnchorMutation,
    consumed: &BTreeSet<(AgentId, [u8; 32])>,
) -> Result<(), FleetRegistryError> {
    next.validate()?;
    mutation.validate()?;
    if let AnchorMutation::ConfirmAbandonUnknown {
        confirmation_sha256,
        expected_anchor_sha256,
        ..
    } = mutation
    {
        if previous.map(ReleaseIntentAnchorV1::sha256).transpose()? != Some(expected_anchor_sha256)
            || next.phase != ReleaseIntentPhaseV1::Aborted
            || !next.terminal_witness.as_ref().is_some_and(|w| {
                w.kind == ReleaseIntentWitnessKindV1::AbandonUnknown
                    && w.publication_confirmation_sha256 == Some(confirmation_sha256)
                    && w.recovery_decision_sha256
                        .is_some_and(|old| old != confirmation_sha256)
            })
        {
            return Err(invalid(
                "unknown-history confirmation does not bind its exact predecessor and decision",
            ));
        }
    } else if next
        .terminal_witness
        .as_ref()
        .is_some_and(|w| w.publication_confirmation_sha256.is_some())
    {
        return Err(invalid(
            "publication confirmation requires its explicit signed recovery path",
        ));
    }
    if let AnchorMutation::Recovery {
        decision_sha256, ..
    }
    | AnchorMutation::UnanchoredRecovery {
        decision_sha256, ..
    } = mutation
    {
        if next
            .terminal_witness
            .as_ref()
            .is_some_and(|w| w.recovery_decision_sha256 != Some(decision_sha256))
        {
            return Err(invalid(
                "recovery witness differs from its verified decision",
            ));
        }
    }
    let expected_generation = previous.map_or(Some(1), |old| old.generation.checked_add(1));
    if expected_generation != Some(next.generation)
        || previous.is_some_and(|old| old.agent_id != next.agent_id)
    {
        return Err(invalid("intent anchor generation or agent changed"));
    }
    let new_grant = previous.is_none_or(|old| old.grant_sha256 != next.grant_sha256);
    if new_grant {
        if consumed.contains(&(next.agent_id.clone(), next.grant_sha256)) {
            return Err(invalid(
                "release grant was already consumed in protected history",
            ));
        }
        match mutation {
            AnchorMutation::Current { policy_sha256 }
                if next.phase == ReleaseIntentPhaseV1::Prepared
                    && next.original_grant_policy_sha256 == Some(policy_sha256)
                    && previous.is_none_or(ReleaseIntentAnchorV1::is_closed_history) =>
            {
                return Ok(());
            }
            AnchorMutation::Recovery { .. }
                if previous.is_none()
                    && matches!(
                        next.phase,
                        ReleaseIntentPhaseV1::RecoveryRequired
                            | ReleaseIntentPhaseV1::Committed
                            | ReleaseIntentPhaseV1::RolledBack
                            | ReleaseIntentPhaseV1::Aborted
                    ) =>
            {
                return Ok(());
            }
            AnchorMutation::UnanchoredRecovery {
                predecessor_anchor_sha256,
                ..
            } if previous.is_some_and(ReleaseIntentAnchorV1::is_closed_history)
                && previous.map(ReleaseIntentAnchorV1::sha256).transpose()?
                    == Some(predecessor_anchor_sha256)
                && next.phase == ReleaseIntentPhaseV1::Aborted
                && next.original_grant_policy_sha256.is_some()
                && next
                    .terminal_witness
                    .as_ref()
                    .is_some_and(|w| w.kind == ReleaseIntentWitnessKindV1::AbandonUnknown) =>
            {
                return Ok(());
            }
            AnchorMutation::ConfirmAbandonUnknown { .. }
                if previous.is_some_and(ReleaseIntentAnchorV1::is_closed_history)
                    && next.original_grant_policy_sha256.is_some() =>
            {
                return Ok(());
            }
            _ => {
                return Err(invalid(
                    "new intent requires a fresh grant or explicit legacy recovery",
                ));
            }
        }
    }
    let old = previous.ok_or_else(|| invalid("missing original intent anchor"))?;
    if old.original_grant_policy_sha256 != next.original_grant_policy_sha256 {
        return Err(invalid(
            "recovery cannot change the original grant policy identity",
        ));
    }
    use ReleaseIntentPhaseV1 as Phase;
    let permitted = match (old.phase, next.phase, mutation) {
        (Phase::Prepared, Phase::Queued, AnchorMutation::Current { policy_sha256 }) => {
            old.original_grant_policy_sha256 == Some(policy_sha256)
        }
        (Phase::Prepared | Phase::Queued, Phase::RecoveryRequired, AnchorMutation::Historical)
        | (Phase::RecoveryRequired, Phase::Aborted, AnchorMutation::Historical) => {
            next.terminal_witness.is_none()
        }
        (Phase::Queued, Phase::Committed | Phase::RolledBack, AnchorMutation::Historical) => next
            .terminal_witness
            .as_ref()
            .is_some_and(|w| w.recovery_decision_sha256.is_none()),
        (
            Phase::RecoveryRequired,
            Phase::Committed | Phase::RolledBack,
            AnchorMutation::Recovery { .. },
        ) => true,
        (
            Phase::RecoveryRequired | Phase::Aborted,
            Phase::Aborted,
            AnchorMutation::Recovery { .. },
        ) => {
            !old.is_closed_history()
                && next
                    .terminal_witness
                    .as_ref()
                    .is_some_and(|w| w.kind == ReleaseIntentWitnessKindV1::AbandonUnknown)
        }
        (
            Phase::RecoveryRequired | Phase::Aborted,
            Phase::Aborted,
            AnchorMutation::ConfirmAbandonUnknown { .. },
        ) => !old.is_closed_history(),
        _ => false,
    };
    if !permitted {
        return Err(invalid(
            "intent anchor transition is not authorized for this path",
        ));
    }
    Ok(())
}
