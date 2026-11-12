//! Admit an already signed terminal experience from the original completed A.
//! No signer, target inference or new task is created here. The pair is two
//! original ledger appends, not an atomic transaction: retain the same signed
//! request and predecessor after any error, recover the original owners, and
//! replay it. Never replace a partial pair with freshly signed identities.
//! This is the execution-before-credit profile whose Decision snapshot is the
//! original input's NDU snapshot. It does not relabel an existing ledger into
//! the distinct full-RunStart-snapshot Dataset projection on the Q24 owner stack.
//! CURRENT requires acknowledged original owners: a lagging ledger witness must
//! first reconcile through the original exact append, never through this reader.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningLedger;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::OutcomeTerminalityV1;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_learning_ledger::outcome_signing_payload_v2;
use codex_hepta_learning_ledger::validate_authenticated_outcome;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;

use crate::AgentdIdentity;
use crate::CircuitTaskErrorV1;
use crate::CircuitTaskSourcePublicationV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::circuit_credit::circuit_learning_run_id_v1;

/// Original Generator/Observer messages, retained unchanged across retries.
/// The Observer supplies its authenticated measured value; a Circuit exit or
/// policy output is never converted into an outcome by this intake.
#[derive(Clone)]
pub struct OriginalCircuitExperienceRequestV1 {
    pub expected_predecessor: Digest32,
    pub decision: ProductionDecisionV2,
    pub decision_evidence: SignedLearningEvidenceV1,
    pub outcome: AuthenticatedOutcomeV1,
    pub outcome_evidence: SignedLearningEvidenceV1,
}

#[derive(Debug, Eq, PartialEq)]
pub struct OriginalCircuitExperienceReceiptV1 {
    pub decision: AppendReceipt,
    pub outcome: AppendReceipt,
}

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitExperienceErrorV1 {
    #[error("original experience binding: {0}")]
    Binding(&'static str),
    #[error("original experience source: {0}")]
    Source(#[from] CircuitTaskErrorV1),
    #[error("original experience authentication: {0}")]
    Authentication(#[from] SignedEvidenceError),
    #[error("original experience ledger: {0}")]
    Ledger(#[from] ProductionLedgerError),
}

type Error = OriginalCircuitExperienceErrorV1;

/// Re-read the original Source's sealed committed Cell result and both physical
/// ledger/witness handles. The ledger authenticates each append and preserves
/// its original idempotence, independence and partial-commit behavior.
pub fn append_original_circuit_experience_v1<W: AnchorWitnessStore>(
    source: &CircuitTaskSourceReadbackV1<W>,
    identity: &AgentdIdentity,
    ledger: &mut LedgerWriter,
    request: &OriginalCircuitExperienceRequestV1,
) -> Result<OriginalCircuitExperienceReceiptV1, Error> {
    append_with_clock(source, identity, ledger, request, now)
}

fn append_with_clock<W: AnchorWitnessStore>(
    source: &CircuitTaskSourceReadbackV1<W>,
    identity: &AgentdIdentity,
    ledger: &mut LedgerWriter,
    request: &OriginalCircuitExperienceRequestV1,
    mut clock: impl FnMut() -> Result<u64, Error>,
) -> Result<OriginalCircuitExperienceReceiptV1, Error> {
    let decision = &request.decision;
    let outcome = &request.outcome;
    let publication = source.read_run_publication(identity, &decision.record_id)?;
    let input = publication.input();
    let admitted_at = publication.original_record().admission.observed_at_unix_micros.div_ceil(1_000_000);
    let policy = CircuitTaskSourcePublicationV1::original_policy(&publication)?;
    let mut candidates = policy.entries().iter().map(|p| p.candidate_id.clone()).collect::<Vec<_>>();
    candidates.sort();
    if decision.record_id != circuit_learning_run_id_v1(ledger, &identity.agent_id, &decision.episode_id)
        .map_err(|_| Error::Binding("original ledger/agent/episode run"))?
        || decision.record_id != input.scope.run_id
        || decision.objective_digest != input.objective_digest
        || decision.objective_digest != ledger.verifier().objective_digest()
        || decision.run_snapshot_digest != input.ndu_snapshot_digest
        || decision.policy_digest != Digest32::of_bytes(publication.output())
        || decision.support_digest != publication.publication_digest()
        || decision.candidate_ids != candidates
        || decision.selected_candidate_id != *policy.selected()
        || decision.selected_propensity != ProbabilityQ32::ONE
        || outcome.episode_id != decision.episode_id
        || outcome.support_digest != publication.publication_digest()
        || outcome.watermark.terminality != OutcomeTerminalityV1::Terminal
        || outcome.watermark.correction_predecessor.is_some()
        || outcome.watermark.censoring_reason.is_some()
        || outcome.observed_at.is_none()
        || outcome.watermark.finalized_at.is_none()
        || outcome.value.is_none()
        || admitted_at == 0
        || outcome.observed_at.is_some_and(|at| at < admitted_at)
        || outcome.watermark.finalized_at.is_some_and(|at| at < outcome.watermark.latest_observable_at)
    {
        return Err(Error::Binding("original policy and measured terminal outcome"));
    }
    // Authenticate BOTH messages and their independent custody before the first
    // write. append_* repeats its own current production checks; this preflight
    // cannot grant a new signer or weaken the original ledger validation.
    let observed_at = clock()?;
    let generator = ledger.verifier().verify(
        LearningEvidenceRoleV1::Generator,
        &request.decision_evidence,
        &decision_signing_payload_v2(decision)?,
        observed_at,
    )?;
    let observer = ledger.verifier().verify(
        LearningEvidenceRoleV1::Observer,
        &request.outcome_evidence,
        &outcome_signing_payload_v2(outcome),
        observed_at,
    )?;
    verify_signed_independent_roles_v1(&generator, &observer, observed_at)?;
    if generator.principal().principal_id != decision.completeness.generator_id
        || observer.principal() != &outcome.observer
    {
        return Err(Error::Binding("original signed actors"));
    }
    validate_authenticated_outcome(generator.principal(), outcome, observed_at)
        .map_err(|_| Error::Binding("original terminal measurement"))?;
    let before = ledger.read_current_durable_snapshot()?;
    if before.records().iter().any(|record| matches!(&record.event,
        LedgerEvent::AuthenticatedOutcomeV2(value)
            if value.episode_id == request.outcome.episode_id
                && value.record_id != request.outcome.record_id))
    {
        return Err(Error::Binding("original terminal outcome was superseded"));
    }
    if source.read_run_publication(identity, &decision.record_id)? != publication {
        return Err(Error::Binding("original source changed before append"));
    }
    let before_decision = clock()?;
    if before_decision < observed_at {
        return Err(Error::Binding("system clock moved backwards"));
    }
    let decision = ledger.append_decision(
        request.expected_predecessor,
        decision.clone(),
        &request.decision_evidence,
        before_decision,
    )?;
    if source.read_run_publication(identity, &request.decision.record_id)? != publication {
        return Err(Error::Binding("original source changed after Decision"));
    }
    ledger.verify_active_decision_binding(&request.decision.record_id, &request.decision.episode_id)?;
    let before_outcome = clock()?;
    if before_outcome < before_decision {
        return Err(Error::Binding("system clock moved backwards"));
    }
    let outcome = ledger.append_outcome(
        decision.chain_digest,
        outcome.clone(),
        &request.outcome_evidence,
        before_outcome,
    )?;
    let after = ledger.read_current_durable_snapshot()?;
    ledger.verify_active_decision_binding(&request.decision.record_id, &request.decision.episode_id)?;
    let active = LearningLedger::from_snapshot(after)
        .map_err(|_| Error::Binding("original active episode"))?;
    if !active.active_records().iter().any(|record| matches!(&record.event,
        LedgerEvent::AuthenticatedOutcomeV2(value)
            if value.record_id == request.outcome.record_id
                && value.outcome_id == request.outcome.outcome_id
                && value.episode_id == request.outcome.episode_id))
    {
        return Err(Error::Binding("original terminal outcome is inactive"));
    }
    if source.read_run_publication(identity, &request.decision.record_id)? != publication {
        return Err(Error::Binding("original source changed after Outcome"));
    }
    let fresh_now = clock()?;
    if fresh_now < before_outcome {
        return Err(Error::Binding("system clock moved backwards"));
    }
    let generator = ledger.verifier().verify(
        LearningEvidenceRoleV1::Generator,
        &request.decision_evidence,
        &decision_signing_payload_v2(&request.decision)?,
        fresh_now,
    )?;
    let observer = ledger.verifier().verify(
        LearningEvidenceRoleV1::Observer,
        &request.outcome_evidence,
        &outcome_signing_payload_v2(&request.outcome),
        fresh_now,
    )?;
    verify_signed_independent_roles_v1(&generator, &observer, fresh_now)?;
    Ok(OriginalCircuitExperienceReceiptV1 { decision, outcome })
}

fn now() -> Result<u64, Error> {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|time| time.as_secs())
        .map_err(|_| Error::Binding("system clock before Unix epoch"))
}

#[cfg(test)]
#[path = "circuit_experience_intake_tests.rs"]
mod tests;
