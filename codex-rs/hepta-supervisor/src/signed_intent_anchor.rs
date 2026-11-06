//! H7 snapshots use the existing Fleet publication journal and external CAS.
//! These helpers bind local bytes to that history; hashes alone do not attest
//! that an operation completed. Cold recovery never promotes a local outcome.
use crate::SupervisorError;
use crate::release_transaction::read_release_transaction;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;
use crate::signed_intent::read_intent;
use crate::signed_intent::write_intent;
use crate::signed_intent_policy::digest_bytes;
use crate::signed_intent_policy::terminal_owner_matches;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::CurrentReleaseAdmission;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseIntentAnchorV1;
use codex_hepta_fleet::ReleaseIntentHistory;
use codex_hepta_fleet::ReleaseIntentPhaseV1;
use codex_hepta_fleet::ReleaseIntentTerminalWitnessV1;
use codex_hepta_fleet::ReleaseIntentWitnessKindV1;

fn error(agent_id: &AgentId) -> SupervisorError {
    SupervisorError::SignedIntentRecoveryRequired(agent_id.clone())
}

pub(crate) fn phase(status: SignedIntentStatus) -> ReleaseIntentPhaseV1 {
    match status {
        SignedIntentStatus::Prepared => ReleaseIntentPhaseV1::Prepared,
        SignedIntentStatus::Queued => ReleaseIntentPhaseV1::Queued,
        SignedIntentStatus::RecoveryRequired => ReleaseIntentPhaseV1::RecoveryRequired,
        SignedIntentStatus::Committed => ReleaseIntentPhaseV1::Committed,
        SignedIntentStatus::RolledBack => ReleaseIntentPhaseV1::RolledBack,
        SignedIntentStatus::Aborted => ReleaseIntentPhaseV1::Aborted,
    }
}

pub(crate) fn snapshot_matches(
    anchor: &ReleaseIntentAnchorV1,
    intent: &SignedSupervisorIntent,
) -> Result<bool, SupervisorError> {
    let policy = intent
        .pq_authority
        .as_ref()
        .map(|proof| digest_bytes(&proof.binding.policy_sha256))
        .transpose()?;
    Ok(anchor.agent_id.as_str() == intent.agent_id
        && anchor.phase == phase(intent.status)
        && anchor.intent_sha256 == digest_bytes(&intent.intent_sha256)?
        && anchor.grant_sha256 == digest_bytes(&intent.grant_sha256)?
        && anchor.original_grant_policy_sha256 == policy)
}

pub(crate) enum HistoricalPolicyKeys<'a> {
    Decode,
    Prepared(&'a crate::H7H89ProductionGrantVerifier),
}

pub(crate) fn check_previous(
    anchor: Option<&ReleaseIntentAnchorV1>,
    previous: Option<&SignedSupervisorIntent>,
    record: &AgentRecord,
) -> Result<(), SupervisorError> {
    check_previous_using_keys(anchor, previous, record, HistoricalPolicyKeys::Decode)
}

pub(crate) fn check_previous_using_keys(
    anchor: Option<&ReleaseIntentAnchorV1>,
    previous: Option<&SignedSupervisorIntent>,
    record: &AgentRecord,
    keys: HistoricalPolicyKeys<'_>,
) -> Result<(), SupervisorError> {
    match (anchor, previous) {
        (None, None) => Ok(()),
        (Some(anchor), Some(intent)) if snapshot_matches(anchor, intent)? => {
            if let Some(proof) = &intent.pq_authority {
                match keys {
                    HistoricalPolicyKeys::Decode => proof.verify_historical_for(intent)?,
                    HistoricalPolicyKeys::Prepared(keys) => {
                        proof.verify_historical_using_keys(intent, keys)?;
                    }
                }
            }
            if anchor.is_closed_history()
                && anchor.terminal_witness != terminal_witness(intent, record)?
            {
                return Err(error(&anchor.agent_id));
            }
            Ok(())
        }
        _ => Err(error(&record.release_state.agent_id)),
    }
}

pub(crate) fn next_anchor(
    previous: Option<&ReleaseIntentAnchorV1>,
    intent: &SignedSupervisorIntent,
    record: &AgentRecord,
) -> Result<ReleaseIntentAnchorV1, SupervisorError> {
    let agent_id = AgentId::parse(intent.agent_id.clone())
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    if agent_id != record.release_state.agent_id {
        return Err(error(&agent_id));
    }
    let generation = previous
        .map_or(Some(1), |anchor| anchor.generation.checked_add(1))
        .ok_or_else(|| SupervisorError::Invalid("intent anchor generation overflow".to_string()))?;
    let anchor = ReleaseIntentAnchorV1 {
        schema_version: 1,
        agent_id,
        generation,
        phase: phase(intent.status),
        intent_sha256: digest_bytes(&intent.intent_sha256)?,
        grant_sha256: digest_bytes(&intent.grant_sha256)?,
        original_grant_policy_sha256: intent
            .pq_authority
            .as_ref()
            .map(|proof| digest_bytes(&proof.binding.policy_sha256))
            .transpose()?,
        terminal_witness: terminal_witness(intent, record)?,
    };
    anchor.validate()?;
    Ok(anchor)
}

pub(crate) fn terminal_witness(
    intent: &SignedSupervisorIntent,
    record: &AgentRecord,
) -> Result<Option<ReleaseIntentTerminalWitnessV1>, SupervisorError> {
    let (kind, transaction_sha256, recovery_decision_sha256) = match intent.status {
        SignedIntentStatus::Committed | SignedIntentStatus::RolledBack => {
            let transaction = read_release_transaction(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                .ok_or_else(|| error(&record.release_state.agent_id))?;
            if !terminal_owner_matches(intent, &transaction, record) {
                return Err(error(&record.release_state.agent_id));
            }
            (
                ReleaseIntentWitnessKindV1::CompletedReleaseCas,
                digest_bytes(&transaction.transaction_sha256)?,
                transaction
                    .recovery_decision_sha256
                    .as_ref()
                    .map(digest_bytes)
                    .transpose()?,
            )
        }
        SignedIntentStatus::Aborted if !intent.requires_recovery() => {
            let transaction = read_release_transaction(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            let decision = &intent
                .unknown_effects
                .last()
                .ok_or_else(|| error(&record.release_state.agent_id))?
                .decision;
            let observed_transaction = transaction
                .as_ref()
                .map_or_else(crate::absent_release_transaction_digest, |transaction| {
                    transaction.transaction_sha256.clone()
                });
            if decision.release_transaction_sha256 != observed_transaction
                || transaction.is_some()
                    && decision
                        .unknown_observation
                        .as_ref()
                        .and_then(|observation| observation.predecessor.as_ref())
                        .is_none()
            {
                return Err(error(&record.release_state.agent_id));
            }
            if record
                .release_state
                .current
                .as_ref()
                .map(codex_hepta_fleet::ReleaseId::as_str)
                != Some(intent.source_release.as_str())
            {
                return Err(error(&record.release_state.agent_id));
            }
            (
                ReleaseIntentWitnessKindV1::AbandonUnknown,
                digest_bytes(&observed_transaction)?,
                Some(digest_bytes(decision.digest())?),
            )
        }
        SignedIntentStatus::Prepared
        | SignedIntentStatus::Queued
        | SignedIntentStatus::RecoveryRequired
        | SignedIntentStatus::Aborted => return Ok(None),
    };
    let state_bytes = serde_json::to_vec(&record.release_state)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let publication_confirmation_sha256 = {
        let current = crate::signed_intent_confirmation::read_current(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let previous =
            crate::signed_intent_confirmation::read_predecessor(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let material = current
            .as_ref()
            .filter(|material| material.intent_sha256 == intent.intent_sha256)
            .or_else(|| {
                previous
                    .as_ref()
                    .filter(|material| material.intent_sha256 == intent.intent_sha256)
            });
        material
            .map(|material| {
                material
                    .validate_for(intent)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                digest_bytes(
                    &material
                        .digest()
                        .map_err(|error| SupervisorError::Invalid(error.to_string()))?,
                )
            })
            .transpose()?
    };
    Ok(Some(ReleaseIntentTerminalWitnessV1 {
        kind,
        transaction_sha256,
        release_state_sha256: digest_bytes(&Sha256Digest::for_bytes(&state_bytes))?,
        release_state_generation: record.release_state.generation,
        recovery_decision_sha256,
        publication_confirmation_sha256,
    }))
}

/// Read a fresh anchor under the already-held release owner lock. A missing
/// local intent, a different history, or a forged completion cannot be ignored.
pub(crate) fn check_process_entry(
    guard: &CurrentReleaseAdmission,
    record: &AgentRecord,
    intent: Option<&SignedSupervisorIntent>,
) -> Result<(), SupervisorError> {
    let actual = read_intent(record.layout.run_root())
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    if actual.as_ref() != intent {
        return Err(error(&record.release_state.agent_id));
    }
    let anchor = guard.intent_anchor()?;
    check_previous(anchor.as_ref(), intent, record)?;
    if intent.is_some_and(SignedSupervisorIntent::requires_recovery) {
        return Err(error(&record.release_state.agent_id));
    }
    if anchor
        .as_ref()
        .is_some_and(ReleaseIntentAnchorV1::is_closed_history)
        && record.release_state.current.as_ref() != Some(&guard.release().release_id)
    {
        return Err(error(&record.release_state.agent_id));
    }
    Ok(())
}

/// Record a fact observed by the original hot lifecycle owner. The caller must
/// already have performed its actual health/release-state CAS completion. Cold
/// recovery calls this helper only for strict quarantine, never for completion.
pub(crate) fn publish_history(
    registry: &FleetRegistry,
    record: &AgentRecord,
    previous: &SignedSupervisorIntent,
    next: &SignedSupervisorIntent,
) -> Result<(), SupervisorError> {
    if registry.is_release_qualification() {
        return write_intent(record.layout.run_root(), next)
            .map_err(|error| SupervisorError::Invalid(error.to_string()));
    }
    let old = registry
        .release_intent_anchor(&record.release_state.agent_id)?
        .ok_or_else(|| error(&record.release_state.agent_id))?;
    publish_observed_history(old, record, previous, next, |old, next| {
        registry.record_intent_history(old, next)
    })
}

/// Cold recovery carries the same history owner across its initial comparison.
/// The second original history boundary still makes a fresh authenticated read.
pub(crate) fn publish_retained_history(
    history: ReleaseIntentHistory,
    record: &AgentRecord,
    previous: &SignedSupervisorIntent,
    next: &SignedSupervisorIntent,
) -> Result<(), SupervisorError> {
    let old = history
        .refresh_anchor()?
        .ok_or_else(|| error(&record.release_state.agent_id))?;
    publish_observed_history(old, record, previous, next, |old, next| {
        history.record_quarantine(old, next)
    })
}

// Both callers supply their actual Fleet append owner. Keep local predecessor,
// proof, witness, durable write and post-confirmation ordering shared verbatim.
fn publish_observed_history(
    old: ReleaseIntentAnchorV1,
    record: &AgentRecord,
    previous: &SignedSupervisorIntent,
    next: &SignedSupervisorIntent,
    record_history: impl FnOnce(
        &ReleaseIntentAnchorV1,
        &ReleaseIntentAnchorV1,
    ) -> Result<(), codex_hepta_fleet::FleetRegistryError>,
) -> Result<(), SupervisorError> {
    check_previous(Some(&old), Some(previous), record)?;
    let actual = read_intent(record.layout.run_root())
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    if actual.as_ref() != Some(previous) {
        return Err(error(&record.release_state.agent_id));
    }
    let next_anchor = next_anchor(Some(&old), next, record)?;
    crate::signed_intent::predecessor::stage(record.layout.run_root(), previous)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    write_intent(record.layout.run_root(), next)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    record_history(&old, &next_anchor)?;
    crate::signed_intent::predecessor::clear_after_confirmation(record.layout.run_root(), next)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    Ok(())
}
