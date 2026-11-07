//! Current signed recovery of an Unknown publication, including a retained
//! predecessor and an actual failed external CAS. No branch dispatches a child.
use crate::H7H89ProductionGrantVerifier;
use crate::ProcessDriver;
use crate::ProductionMutationReceipt;
use crate::ProductionMutationStatus;
use crate::ProductionRecoveryDecision;
use crate::ProductionRecoveryOutcome;
use crate::Supervisor;
use crate::SupervisorError;
use crate::UnknownRecoveryPredecessorV1;
use crate::current_recovery_admission::CurrentRecoveryAdmission;
use crate::current_recovery_admission::RecoveryPublicationState;
use crate::release_transaction::read_release_transaction;
use crate::runtime::AgentSlot;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;
use crate::signed_intent::read_intent;
use crate::signed_intent::write_intent;
use crate::signed_intent_anchor::check_previous_with_prepared;
use crate::signed_intent_anchor::next_anchor;
use crate::signed_intent_anchor::snapshot_matches;
use crate::signed_intent_confirmation::SignedIntentPublicationConfirmation;
use crate::signed_intent_confirmation::{self};
use crate::signed_intent_policy::digest_bytes;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::ReleaseBinding;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ReleaseIntentAnchorV1;
use codex_hepta_fleet::ReleaseIntentPhaseV1;

fn denied(agent: &AgentId) -> SupervisorError {
    SupervisorError::SignedIntentRecoveryRequired(agent.clone())
}

pub(crate) fn state_sha256(record: &AgentRecord) -> Result<Sha256Digest, SupervisorError> {
    Ok(Sha256Digest::for_bytes(
        &serde_json::to_vec(&record.release_state)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?,
    ))
}

pub(crate) fn ensure_stopped<P>(
    record: &AgentRecord,
    slot: &AgentSlot<P>,
) -> Result<(), SupervisorError> {
    if slot.runtime.is_some()
        || slot.matrix.runtime.is_some()
        || !matches!(
            record.lifecycle.lifecycle,
            AgentLifecycle::Failed | AgentLifecycle::Stopped
        )
        || crate::lease::read_lease(record.layout.run_root())?.is_some()
        || crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_some()
    {
        return Err(denied(&record.release_state.agent_id));
    }
    Ok(())
}

pub(crate) fn expected_sha256(
    expected: Option<&ReleaseIntentAnchorV1>,
    agent: &AgentId,
    observed: Option<&UnknownRecoveryPredecessorV1>,
    explicit: bool,
) -> Result<[u8; 32], SupervisorError> {
    let actual = match expected {
        Some(anchor) => UnknownRecoveryPredecessorV1::from_anchor(anchor),
        None => Ok(UnknownRecoveryPredecessorV1::from_absent(agent)),
    }
    .map_err(|error| SupervisorError::ProductionAuthority(error.to_string()))?;
    if observed.is_some_and(|observed| observed != &actual) || explicit && observed.is_none() {
        return Err(denied(agent));
    }
    digest_bytes(&actual.anchor_sha256)
}

/// Recover the unique pre-disposition canonical snapshot named by the retained
/// signed decision. This does not reauthorize it or rewrite the current file.
fn unknown_origin(
    intent: &SignedSupervisorIntent,
) -> Result<SignedSupervisorIntent, SupervisorError> {
    let last = intent
        .unknown_effects
        .last()
        .ok_or_else(|| SupervisorError::Invalid("missing retained Unknown".to_string()))?;
    if intent.status != SignedIntentStatus::Aborted
        || intent.requires_recovery()
        || last.decision.schema_version != 3
        || last.decision.pq_authority.is_none()
    {
        return Err(SupervisorError::Invalid(
            "confirmation requires a retained PQ Unknown disposition".to_string(),
        ));
    }
    let mut matches = Vec::new();
    for status in [
        SignedIntentStatus::Prepared,
        SignedIntentStatus::Queued,
        SignedIntentStatus::RecoveryRequired,
        SignedIntentStatus::Aborted,
    ] {
        for schema in [1, 2, 3] {
            let mut candidate = intent.clone();
            candidate.unknown_effects.pop();
            candidate.status = status;
            candidate.schema_version = schema;
            candidate.intent_sha256 = candidate
                .compute_digest()
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            if candidate.intent_sha256 == last.decision.intent_sha256
                && candidate.validate().is_ok()
            {
                matches.push(candidate);
            }
        }
    }
    if matches.len() != 1 {
        return Err(SupervisorError::Invalid(
            "retained Unknown lacks its exact original snapshot".to_string(),
        ));
    }
    Ok(matches.remove(0))
}

fn same_operation(
    left: &SignedSupervisorIntent,
    right: &SignedSupervisorIntent,
) -> Result<bool, SupervisorError> {
    let left = left
        .with_status(right.status)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    Ok(&left == right)
}

fn check_origin(
    record: &AgentRecord,
    expected: Option<&ReleaseIntentAnchorV1>,
    pending: Option<&ReleaseIntentAnchorV1>,
    current: &SignedSupervisorIntent,
    origin: &SignedSupervisorIntent,
    verifier: &H7H89ProductionGrantVerifier,
) -> Result<(), SupervisorError> {
    let agent = &record.release_state.agent_id;
    if let Some(proof) = &origin.pq_authority {
        proof.verify_historical_for_with_prepared(origin, verifier)?;
    }
    if let Some(pending) = pending
        && (pending.agent_id != *agent
            || (!snapshot_matches(pending, origin)? && !snapshot_matches(pending, current)?))
    {
        return Err(denied(agent));
    }
    match expected {
        Some(anchor) if snapshot_matches(anchor, origin)? => {
            check_previous_with_prepared(Some(anchor), Some(origin), record, Some(verifier))
        }
        Some(anchor) => {
            let previous = crate::signed_intent::predecessor::read(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                .ok_or_else(|| denied(agent))?;
            check_previous_with_prepared(Some(anchor), Some(&previous), record, Some(verifier))?;
            if origin.grant_sha256 == previous.grant_sha256 {
                if !same_operation(origin, &previous)?
                    || previous.requires_recovery() && !origin.requires_recovery()
                {
                    return Err(denied(agent));
                }
            } else if !anchor.is_closed_history()
                || origin.pq_authority.is_none()
                || origin.unknown_effects != previous.unknown_effects
            {
                return Err(denied(agent));
            }
            Ok(())
        }
        None => {
            if origin.pq_authority.is_some() {
                // An absent external anchor is an explicit current recovery
                // observation, not absence inferred from the local file tree.
                if !matches!(origin.status, SignedIntentStatus::Prepared | SignedIntentStatus::Queued)
                    || !origin.unknown_effects.is_empty()
                    || pending.is_some_and(|pending| {
                        pending.phase != ReleaseIntentPhaseV1::Prepared
                            && !(pending.phase == ReleaseIntentPhaseV1::Aborted
                                && current.status == SignedIntentStatus::Aborted
                                && current != origin
                                && pending.terminal_witness.as_ref().is_some_and(|witness|
                                    witness.kind == codex_hepta_fleet::ReleaseIntentWitnessKindV1::AbandonUnknown
                                        && witness.publication_confirmation_sha256.is_none())
                                && snapshot_matches(pending, current).unwrap_or(false))
                    })
                    || read_release_transaction(record.layout.run_root()).map_err(|error| SupervisorError::Invalid(error.to_string()))?.is_some() {
                    return Err(denied(agent));
                }
            } else if !origin.requires_recovery()
                || pending.is_some_and(|pending| pending.original_grant_policy_sha256.is_some())
            {
                // Existing legacy unresolved history is readable and requires
                // a new current PQ recovery signature. It acquires no PQ grant.
                return Err(denied(agent));
            }
            Ok(())
        }
    }
}

fn actual_unknown_transaction(
    record: &AgentRecord,
    intent: &SignedSupervisorIntent,
    expected: Option<&ReleaseIntentAnchorV1>,
    previous_closed: Option<&ReleaseIntentAnchorV1>,
    explicit: bool,
) -> Result<Sha256Digest, SupervisorError> {
    let transaction = read_release_transaction(record.layout.run_root())
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let Some(transaction) = transaction else {
        return Ok(crate::absent_release_transaction_digest());
    };
    let previous = expected
        .filter(|anchor| {
            anchor.is_closed_history()
                && anchor.grant_sha256 != digest_bytes(&intent.grant_sha256).unwrap_or([0; 32])
        })
        .or(previous_closed)
        .ok_or_else(|| denied(&record.release_state.agent_id))?;
    let witness = previous
        .terminal_witness
        .as_ref()
        .ok_or_else(|| denied(&record.release_state.agent_id))?;
    if !explicit
        || previous.agent_id != record.release_state.agent_id
        || !previous.is_closed_history()
        || previous.grant_sha256 == digest_bytes(&intent.grant_sha256)?
        || witness.transaction_sha256 != digest_bytes(&transaction.transaction_sha256)?
        || witness.release_state_generation != record.release_state.generation
        || witness.release_state_sha256 != digest_bytes(&state_sha256(record)?)?
    {
        return Err(denied(&record.release_state.agent_id));
    }
    Ok(transaction.transaction_sha256)
}

#[expect(
    clippy::too_many_arguments,
    reason = "every current signed recovery observation is explicit"
)]
pub(crate) fn verify_decision(
    verifier: &H7H89ProductionGrantVerifier,
    decision: &ProductionRecoveryDecision,
    intent: &SignedSupervisorIntent,
    record: &AgentRecord,
    binding: &ReleaseBinding,
    transaction: &Sha256Digest,
    authority_epoch: u64,
    now: u64,
) -> Result<(), SupervisorError> {
    let parse = |value: &str| Sha256Digest::parse(value).map_err(SupervisorError::Invalid);
    verifier
        .verify_recovery(
            decision,
            &record.release_state.agent_id,
            &intent.grant_sha256,
            &intent.intent_sha256,
            transaction,
            binding.release_id.as_str(),
            &parse(&binding.manifest_sha256)?,
            &parse(&binding.agentd_program_sha256)?,
            binding
                .matrixd_program_sha256
                .as_deref()
                .map(parse)
                .transpose()?
                .as_ref(),
            record.lifecycle.generation,
            authority_epoch,
            now,
        )
        .map_err(|error| SupervisorError::ProductionAuthority(error.to_string()))
}

impl<D: ProcessDriver> Supervisor<D> {
    #[expect(
        clippy::too_many_arguments,
        reason = "the original locked owner supplies every observed fence"
    )]
    pub(crate) fn resolve_current_unknown_publication(
        &mut self,
        agent: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        intent: &SignedSupervisorIntent,
        decision: &ProductionRecoveryDecision,
        verifier: &H7H89ProductionGrantVerifier,
        authority_epoch: u64,
    ) -> Result<ProductionMutationReceipt, SupervisorError> {
        ensure_stopped(record, slot)?;
        if intent.agent_id != agent.as_str() || decision.pq_authority.is_none() {
            return Err(denied(agent));
        }
        let confirmation = decision.outcome == ProductionRecoveryOutcome::ConfirmUnknownPublication;
        if !confirmation
            && (decision.outcome != ProductionRecoveryOutcome::AbandonUnknown
                || !intent.requires_recovery()
                    && !matches!(
                        intent.status,
                        SignedIntentStatus::Prepared | SignedIntentStatus::Queued
                    ))
        {
            return Err(denied(agent));
        }
        let origin = if confirmation {
            unknown_origin(intent)?
        } else {
            intent.clone()
        };
        let source_id = ReleaseId::parse(intent.source_release.clone())?;
        if record.release_state.current.as_ref() != Some(&source_id) {
            return Err(denied(agent));
        }
        let admission = CurrentRecoveryAdmission::acquire(&self.registry, verifier)?;
        if admission.replacement().is_some() {
            return Err(denied(agent));
        }
        let expected = admission.expected(agent)?;
        let previous_closed = admission.previous_closed(agent)?;
        let observation = decision
            .unknown_observation
            .as_ref()
            .ok_or_else(|| denied(agent))?;
        let explicit = confirmation
            || admission.pending().is_some()
            || expected
                .as_ref()
                .is_none_or(|anchor| !snapshot_matches(anchor, &origin).unwrap_or(false));
        let expected_digest = expected_sha256(
            expected.as_ref(),
            agent,
            observation.predecessor.as_ref(),
            explicit,
        )?;
        check_origin(
            record,
            expected.as_ref(),
            admission.pending(),
            intent,
            &origin,
            verifier,
        )?;
        let transaction = actual_unknown_transaction(
            record,
            intent,
            expected.as_ref(),
            previous_closed.as_ref(),
            observation.predecessor.is_some(),
        )?;
        let binding = admission.binding(&self.registry, agent, &source_id)?;
        if observation.release_state_generation != record.release_state.generation
            || observation.admission_frontier_sha256.as_str() != binding.admission_frontier_sha256
        {
            return Err(denied(agent));
        }
        verify_decision(
            verifier,
            decision,
            intent,
            record,
            &binding,
            &transaction,
            authority_epoch,
            admission.now_seconds()?,
        )?;
        let next = if confirmation {
            intent.clone()
        } else if observation.predecessor.is_some() && intent.pq_authority.is_some() {
            intent
                .abandon_unknown_at_publication_cut(decision)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        } else {
            intent
                .abandon_unknown(decision)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        };
        let material = if confirmation {
            Some(
                SignedIntentPublicationConfirmation::new(
                    intent,
                    verifier.policy_bytes().ok_or_else(|| denied(agent))?,
                    decision.clone(),
                )
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?,
            )
        } else {
            None
        };
        let next_revision = slot
            .control_revision
            .checked_add(1)
            .ok_or_else(|| SupervisorError::Invalid("control revision overflow".to_string()))?;
        if self.record(agent)?.release_state != record.release_state
            || self.record(agent)?.lifecycle != record.lifecycle
            || read_intent(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                .as_ref()
                != Some(intent)
        {
            return Err(denied(agent));
        }
        ensure_stopped(record, slot)?;
        admission.check_window(decision)?;
        slot.intent_publication_fenced = true;
        if expected
            .as_ref()
            .is_some_and(|anchor| snapshot_matches(anchor, intent).unwrap_or(false))
        {
            crate::signed_intent::predecessor::stage(record.layout.run_root(), intent)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        }
        if let Some(material) = &material {
            let old = signed_intent_confirmation::read_current(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            signed_intent_confirmation::write_current(
                record.layout.run_root(),
                old.as_ref(),
                Some(material),
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        } else {
            write_intent(record.layout.run_root(), &next)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        }
        let anchor = next_anchor(expected.as_ref(), &next, record)?;
        let original_decision = next
            .unknown_effects
            .last()
            .ok_or_else(|| denied(agent))?
            .decision
            .digest();
        let material_digest = material
            .as_ref()
            .map(|material| {
                material
                    .digest()
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))
            })
            .transpose()?;
        if admission.binding(&self.registry, agent, &source_id)? != binding
            || self.record(agent)?.release_state != record.release_state
            || self.record(agent)?.lifecycle != record.lifecycle
        {
            return Err(denied(agent));
        }
        let state = admission.commit_unknown(
            expected.as_ref(),
            &anchor,
            decision,
            digest_bytes(original_decision)?,
            material_digest.as_ref().map(digest_bytes).transpose()?,
            expected_digest,
        )?;
        crate::signed_intent::predecessor::clear_after_confirmation(
            record.layout.run_root(),
            &next,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        slot.signed_intent = Some(next.clone());
        slot.control_revision = next_revision;
        slot.intent_publication_fenced = matches!(state, RecoveryPublicationState::ReopenRequired);
        Ok(ProductionMutationReceipt {
            grant_sha256: next.grant_sha256,
            agent_id: next.agent_id,
            transition: next.transition,
            source_release: next.source_release,
            target_release: next.target_release,
            control_revision: next_revision,
            status: ProductionMutationStatus::Aborted,
            production_authority: true,
            external_effects: true,
            operator_acceptance: true,
            promotion: false,
        })
    }
}
