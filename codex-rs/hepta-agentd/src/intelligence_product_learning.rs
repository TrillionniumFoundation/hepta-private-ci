//! Product Decision/Outcome publication for canonical intelligence.
//!
//! The daemon owns only orchestration and durable ambiguity state. The learning
//! ledger remains the sole fact owner and verifies signed generator/observer
//! evidence. Every append is prepared in the durable outbox, currentness is
//! checked immediately before mutation, and ambiguous commits remain
//! reconciliation-only. Physical execution is never replayed from this API.

use std::str::FromStr;

use codex_hepta_intelligence::AdvisoryDecisionV1;
use codex_hepta_intelligence::CanonicalIntelligenceError;
use codex_hepta_intelligence::validate_current_snapshot;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::DurableLedgerError;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::candidate_ids_digest_v2;
use codex_hepta_learning_ledger::candidate_order_digest_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::DurableIntelligenceLearningOutboxV1;
use crate::IntelligenceLearningAppendKindV1;
use crate::IntelligenceLearningAppendStateV1;
use crate::IntelligenceLearningIntentV1;
use crate::IntelligenceLearningOutboxErrorV1;
use crate::RunPhase;
use crate::RunReceipt;
use crate::intelligence_learning_outbox::production_decision_semantic_digest;
use crate::intelligence_learning_outbox::production_outcome_semantic_digest;
use crate::intelligence_learning_outbox::signed_learning_evidence_digest;

use super::AgentdIntelligenceProductRunnerV1;
use super::FileBackedFreshnessOracleV1;
use super::PreparedAgentdIntelligenceRunV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceLearningAppendReceiptV1 {
    pub operation_id: String,
    pub outbox_revision: u64,
    pub state: IntelligenceLearningAppendStateV1,
    pub append: AppendReceipt,
}

/// Exact terminal observation binding produced only after the Agentd run owner
/// has observed a physical terminal state. The signed Outcome must use the same
/// physical-terminal digest as its support evidence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceTerminalBindingV1 {
    run_id: StableId,
    run_revision: u64,
    phase: RunPhase,
    selected_candidate_id: StableId,
    run_snapshot_digest: Digest32,
    context_digest: Digest32,
    envelope_digest: Digest32,
    physical_terminal_digest: Digest32,
}

impl AgentdIntelligenceTerminalBindingV1 {
    #[must_use]
    pub fn run_id(&self) -> &StableId {
        &self.run_id
    }

    #[must_use]
    pub const fn run_revision(&self) -> u64 {
        self.run_revision
    }

    #[must_use]
    pub const fn phase(&self) -> RunPhase {
        self.phase
    }

    #[must_use]
    pub fn selected_candidate_id(&self) -> &StableId {
        &self.selected_candidate_id
    }

    #[must_use]
    pub const fn run_snapshot_digest(&self) -> Digest32 {
        self.run_snapshot_digest
    }

    #[must_use]
    pub const fn physical_terminal_digest(&self) -> Digest32 {
        self.physical_terminal_digest
    }
}

#[derive(Debug, thiserror::Error)]
pub enum AgentdIntelligenceLearningErrorV1 {
    #[error("canonical intelligence learning binding: {0}")]
    Binding(&'static str),
    #[error("canonical intelligence currentness: {0}")]
    Currentness(#[source] CanonicalIntelligenceError),
    #[error("canonical intelligence learning outbox: {0}")]
    Outbox(#[from] IntelligenceLearningOutboxErrorV1),
    #[error("canonical intelligence learning ledger: {0}")]
    Ledger(#[source] ProductionLedgerError),
    #[error("canonical intelligence learning append is indeterminate: {operation_id}")]
    Indeterminate {
        operation_id: String,
        receipt: Option<AppendReceipt>,
    },
}

impl PreparedAgentdIntelligenceRunV1 {
    /// Digest the exact Agentd admission identity consumed by the physical
    /// caller and production Decision. This is not the canonical snapshot
    /// digest: it additionally binds the daemon run/body/fence/deadline tuple.
    #[must_use]
    pub fn product_run_snapshot_digest(&self) -> Digest32 {
        agentd_run_snapshot_digest(&self.run_snapshot)
    }

    #[must_use]
    pub fn canonical_candidate_ids(&self) -> &[StableId] {
        &self.candidate_ids
    }

    /// Freeze independently observed physical terminal evidence onto the exact
    /// prepared run. Indeterminate or merely cancelling states are rejected.
    pub fn bind_terminal_observation(
        &self,
        receipt: &RunReceipt,
        physical_terminal_digest: Digest32,
    ) -> Result<AgentdIntelligenceTerminalBindingV1, AgentdIntelligenceLearningErrorV1> {
        validate_run_binding(self, receipt, /*terminal_required*/ true)?;
        if physical_terminal_digest.is_zero() {
            return Err(AgentdIntelligenceLearningErrorV1::Binding(
                "physical terminal digest",
            ));
        }
        let (selected_candidate_id, _) = selected_decision(self)?;
        Ok(AgentdIntelligenceTerminalBindingV1 {
            run_id: self.envelope.run_id.clone(),
            run_revision: receipt.revision,
            phase: receipt.phase,
            selected_candidate_id,
            run_snapshot_digest: self.product_run_snapshot_digest(),
            context_digest: self.envelope.context_receipt_digest,
            envelope_digest: self.envelope.envelope_digest,
            physical_terminal_digest,
        })
    }
}

impl AgentdIntelligenceProductRunnerV1 {
    /// Publish the authenticated V2 Decision for this exact canonical run.
    /// The durable outbox is prepared before final currentness and ledger use.
    #[allow(clippy::too_many_arguments)]
    pub fn append_production_decision(
        &self,
        ledger: &mut LedgerWriter,
        outbox: &mut DurableIntelligenceLearningOutboxV1,
        expected_predecessor: Digest32,
        prepared: &PreparedAgentdIntelligenceRunV1,
        run_receipt: &RunReceipt,
        decision: ProductionDecisionV2,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<AgentdIntelligenceLearningAppendReceiptV1, AgentdIntelligenceLearningErrorV1> {
        validate_run_binding(prepared, run_receipt, /*terminal_required*/ false)?;
        validate_decision_binding(prepared, &decision)?;
        let authentication_digest = signed_learning_evidence_digest(evidence);
        let semantic_digest = production_decision_semantic_digest(
            &decision,
            authentication_digest,
        )
        .map_err(AgentdIntelligenceLearningErrorV1::Ledger)?;
        let intent = IntelligenceLearningIntentV1::new(
            IntelligenceLearningAppendKindV1::Decision,
            &decision.record_id,
            &prepared.envelope.run_id,
            &decision.episode_id,
            expected_predecessor,
            decision.run_snapshot_digest,
            decision.objective_digest,
            decision.support_digest,
            semantic_digest,
            authentication_digest,
            prepared.snapshot.authority_epoch(),
            run_receipt.generation,
            &run_receipt.fence_digest,
        )?;
        let intent = outbox.prepare(intent)?;
        if intent.state == IntelligenceLearningAppendStateV1::Acknowledged {
            return Err(AgentdIntelligenceLearningErrorV1::Binding(
                "acknowledged operation requires ledger idempotent replay receipt",
            ));
        }
        self.require_current_learning_snapshot(prepared, outbox, &intent.operation_id)?;
        match ledger.append_decision(expected_predecessor, decision, evidence, now) {
            Ok(receipt) => acknowledge(outbox, intent.operation_id, receipt),
            Err(error) => classify_append_error(outbox, intent.operation_id, error),
        }
    }

    /// Publish an independently authenticated physical Outcome only after the
    /// same Agentd run has terminal evidence and the ledger still has the active
    /// Decision for the supplied episode.
    #[allow(clippy::too_many_arguments)]
    pub fn append_production_outcome(
        &self,
        ledger: &mut LedgerWriter,
        outbox: &mut DurableIntelligenceLearningOutboxV1,
        expected_predecessor: Digest32,
        prepared: &PreparedAgentdIntelligenceRunV1,
        terminal: &AgentdIntelligenceTerminalBindingV1,
        outcome: AuthenticatedOutcomeV1,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<AgentdIntelligenceLearningAppendReceiptV1, AgentdIntelligenceLearningErrorV1> {
        validate_terminal_binding(prepared, terminal, &outcome)?;
        ledger
            .verify_active_decision_binding(&prepared.envelope.run_id, &outcome.episode_id)
            .map_err(AgentdIntelligenceLearningErrorV1::Ledger)?;
        let authentication_digest = signed_learning_evidence_digest(evidence);
        let semantic_digest = production_outcome_semantic_digest(&outcome, authentication_digest);
        let intent = IntelligenceLearningIntentV1::new(
            IntelligenceLearningAppendKindV1::Outcome,
            &outcome.record_id,
            &prepared.envelope.run_id,
            &outcome.episode_id,
            expected_predecessor,
            terminal.run_snapshot_digest,
            prepared.envelope.objective_digest,
            outcome.support_digest,
            semantic_digest,
            authentication_digest,
            prepared.snapshot.authority_epoch(),
            prepared.run_snapshot.generation,
            &prepared.run_snapshot.fence_digest,
        )?;
        let intent = outbox.prepare(intent)?;
        if intent.state == IntelligenceLearningAppendStateV1::Acknowledged {
            return Err(AgentdIntelligenceLearningErrorV1::Binding(
                "acknowledged operation requires ledger idempotent replay receipt",
            ));
        }
        self.require_current_learning_snapshot(prepared, outbox, &intent.operation_id)?;
        match ledger.append_outcome(expected_predecessor, outcome, evidence, now) {
            Ok(receipt) => acknowledge(outbox, intent.operation_id, receipt),
            Err(error) => classify_append_error(outbox, intent.operation_id, error),
        }
    }

    fn require_current_learning_snapshot(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        outbox: &mut DurableIntelligenceLearningOutboxV1,
        operation_id: &str,
    ) -> Result<(), AgentdIntelligenceLearningErrorV1> {
        let mut oracle = FileBackedFreshnessOracleV1::new(
            self.authority_file.clone(),
            self.authority_verifier.clone(),
        );
        if let Err(error) = validate_current_snapshot(&prepared.snapshot, &mut oracle) {
            outbox.mark_revoked(operation_id, "canonical owner currentness changed")?;
            return Err(AgentdIntelligenceLearningErrorV1::Currentness(error));
        }
        Ok(())
    }
}

fn validate_run_binding(
    prepared: &PreparedAgentdIntelligenceRunV1,
    receipt: &RunReceipt,
    terminal_required: bool,
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    let snapshot = &prepared.run_snapshot;
    if receipt.run_id != snapshot.run_id
        || receipt.authority_epoch != snapshot.authority_epoch
        || receipt.generation != snapshot.generation
        || receipt.fence_digest != snapshot.fence_digest
        || receipt.deadline_ms != snapshot.deadline_ms
        || receipt.context_digest.as_deref()
            != Some(prepared.context_attachment.context_digest.as_str())
        || receipt.compilation_receipt_digest.as_deref()
            != Some(prepared.envelope.envelope_digest.to_string().as_str())
    {
        return Err(AgentdIntelligenceLearningErrorV1::Binding(
            "Agentd run/context identity",
        ));
    }
    if terminal_required {
        if !receipt.terminal_observed
            || !matches!(
                receipt.phase,
                RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed
            )
        {
            return Err(AgentdIntelligenceLearningErrorV1::Binding(
                "physical terminal observation",
            ));
        }
    } else if receipt.phase == RunPhase::Admitted {
        return Err(AgentdIntelligenceLearningErrorV1::Binding(
            "context not attached",
        ));
    }
    Ok(())
}

fn validate_decision_binding(
    prepared: &PreparedAgentdIntelligenceRunV1,
    decision: &ProductionDecisionV2,
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    let (selected_candidate_id, selected_propensity_raw) = selected_decision(prepared)?;
    let mut expected_candidates = prepared.candidate_ids.clone();
    let mut observed_candidates = decision.candidate_ids.clone();
    expected_candidates.sort();
    observed_candidates.sort();
    let expected_count = u32::try_from(expected_candidates.len())
        .map_err(|_| AgentdIntelligenceLearningErrorV1::Binding("candidate count"))?;
    if decision.record_id != prepared.envelope.run_id
        || decision.run_snapshot_digest != prepared.product_run_snapshot_digest()
        || decision.objective_digest != prepared.envelope.objective_digest
        || decision.support_digest != prepared.dispatch_proposal_digest
        || observed_candidates != expected_candidates
        || decision.selected_candidate_id != selected_candidate_id
        || decision.selected_propensity.raw() != selected_propensity_raw
        || decision.completeness.state_digest != prepared.envelope.objective_digest
        || decision.completeness.candidate_count != expected_count
        || decision.completeness.omitted_count_bound != 0
        || !decision.completeness.complete_for_generator
        || decision.completeness.candidates_digest
            != candidate_ids_digest_v2(&expected_candidates)
        || decision.completeness.canonical_order_digest
            != candidate_order_digest_v2(&expected_candidates)
    {
        return Err(AgentdIntelligenceLearningErrorV1::Binding(
            "Decision/run/candidate identity",
        ));
    }
    Ok(())
}

fn validate_terminal_binding(
    prepared: &PreparedAgentdIntelligenceRunV1,
    terminal: &AgentdIntelligenceTerminalBindingV1,
    outcome: &AuthenticatedOutcomeV1,
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    let (selected_candidate_id, _) = selected_decision(prepared)?;
    if terminal.run_id != prepared.envelope.run_id
        || terminal.selected_candidate_id != selected_candidate_id
        || terminal.run_snapshot_digest != prepared.product_run_snapshot_digest()
        || terminal.context_digest != prepared.envelope.context_receipt_digest
        || terminal.envelope_digest != prepared.envelope.envelope_digest
        || terminal.physical_terminal_digest.is_zero()
        || outcome.support_digest != terminal.physical_terminal_digest
    {
        return Err(AgentdIntelligenceLearningErrorV1::Binding(
            "Outcome/physical terminal identity",
        ));
    }
    Ok(())
}

fn selected_decision(
    prepared: &PreparedAgentdIntelligenceRunV1,
) -> Result<(StableId, u64), AgentdIntelligenceLearningErrorV1> {
    let AdvisoryDecisionV1::Selected {
        candidate_id,
        propensity,
    } = &prepared.envelope.decision.decision
    else {
        return Err(AgentdIntelligenceLearningErrorV1::Binding(
            "selected Decision required",
        ));
    };
    if !prepared.candidate_ids.contains(candidate_id) || propensity.raw() == 0 {
        return Err(AgentdIntelligenceLearningErrorV1::Binding(
            "selected candidate or propensity",
        ));
    }
    Ok((candidate_id.clone(), propensity.raw()))
}

fn agentd_run_snapshot_digest(snapshot: &crate::AgentRunSnapshot) -> Digest32 {
    let mut bytes = b"hepta.agentd.intelligence-product-run-snapshot.v1\0".to_vec();
    push_string(&mut bytes, &snapshot.run_id);
    for value in [
        snapshot.request_digest.as_str(),
        snapshot.objective_digest.as_str(),
        snapshot.body_digest.as_str(),
        snapshot.artifact_set_digest.as_str(),
    ] {
        push_digest_string(&mut bytes, value);
    }
    bytes.extend_from_slice(&snapshot.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&snapshot.generation.to_be_bytes());
    push_digest_string(&mut bytes, &snapshot.fence_digest);
    bytes.extend_from_slice(&snapshot.deadline_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn acknowledge(
    outbox: &mut DurableIntelligenceLearningOutboxV1,
    operation_id: String,
    receipt: AppendReceipt,
) -> Result<AgentdIntelligenceLearningAppendReceiptV1, AgentdIntelligenceLearningErrorV1> {
    let state = outbox.acknowledge(&operation_id, &receipt)?;
    Ok(AgentdIntelligenceLearningAppendReceiptV1 {
        operation_id,
        outbox_revision: state.revision,
        state: state.state,
        append: receipt,
    })
}

fn classify_append_error<T>(
    outbox: &mut DurableIntelligenceLearningOutboxV1,
    operation_id: String,
    error: ProductionLedgerError,
) -> Result<T, AgentdIntelligenceLearningErrorV1> {
    match error {
        ProductionLedgerError::IndeterminateAfterLedgerCommit {
            receipt,
            witness_error: _,
        } => {
            outbox.mark_indeterminate(
                &operation_id,
                Some(&receipt),
                "ledger committed but witness acknowledgement is indeterminate",
            )?;
            Err(AgentdIntelligenceLearningErrorV1::Indeterminate {
                operation_id,
                receipt: Some(receipt),
            })
        }
        ProductionLedgerError::Durable(
            DurableLedgerError::Indeterminate | DurableLedgerError::Io(_),
        ) => {
            outbox.mark_indeterminate(
                &operation_id,
                None,
                "durable ledger append result is indeterminate",
            )?;
            Err(AgentdIntelligenceLearningErrorV1::Indeterminate {
                operation_id,
                receipt: None,
            })
        }
        ProductionLedgerError::Evidence(SignedEvidenceError::Revoked) => {
            outbox.mark_revoked(&operation_id, "learning evidence signer is revoked")?;
            Err(AgentdIntelligenceLearningErrorV1::Ledger(
                ProductionLedgerError::Evidence(SignedEvidenceError::Revoked),
            ))
        }
        other => {
            outbox.mark_rejected(&operation_id, "learning ledger rejected append")?;
            Err(AgentdIntelligenceLearningErrorV1::Ledger(other))
        }
    }
}

fn push_string(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn push_digest_string(bytes: &mut Vec<u8>, value: &str) {
    match Digest32::from_str(value) {
        Ok(digest) => bytes.extend_from_slice(digest.as_array()),
        // Construction of AgentRunSnapshot already validates these fields. Keep
        // this digest function total while preserving invalid input separation.
        Err(_) => {
            bytes.extend_from_slice(Digest32::of_bytes(value.as_bytes()).as_array());
        }
    }
}
