// Product Decision/Outcome publication for canonical intelligence.
//
// This file is textually included by `intelligence_product_runner.rs`, so these
// implementations retain access to the runner's private currentness state while
// all public receipt types remain named at the crate boundary.

use codex_hepta_intelligence::AdvisoryDecisionV1 as ProductAdvisoryDecisionV1;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1 as ProductOutcomeV1;
use codex_hepta_learning_ledger::DurableLedgerError as ProductDurableLedgerError;
use codex_hepta_learning_ledger::LedgerWriter as ProductLedgerWriter;
use codex_hepta_learning_ledger::ProductionDecisionV2 as ProductDecisionV2;
use codex_hepta_learning_ledger::ProductionLedgerError as ProductLedgerError;
use codex_hepta_learning_ledger::SignedEvidenceError as ProductSignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1 as ProductSignedEvidenceV1;
use codex_hepta_learning_ledger::candidate_ids_digest_v2 as product_candidate_ids_digest_v2;
use codex_hepta_learning_ledger::candidate_order_digest_v2 as product_candidate_order_digest_v2;

use crate::AgentdIntelligenceLearningAppendReceiptV1;
use crate::AgentdIntelligenceLearningErrorV1;
use crate::AgentdIntelligenceTerminalBindingV1;
use crate::DurableIntelligenceLearningOutboxV1;
use crate::IntelligenceLearningAppendKindV1;
use crate::IntelligenceLearningAppendStateV1;
use crate::IntelligenceLearningIntentV1;
use crate::RunPhase;
use crate::RunReceipt;
use crate::intelligence_learning_outbox::production_decision_semantic_digest;
use crate::intelligence_learning_outbox::production_outcome_semantic_digest;
use crate::intelligence_learning_outbox::signed_learning_evidence_digest;

impl PreparedAgentdIntelligenceRunV1 {
    /// Digest the exact Agentd admission identity consumed by the physical
    /// caller and production Decision. This is not the canonical snapshot
    /// digest: it additionally binds the daemon run/body/fence/deadline tuple.
    #[must_use]
    pub fn product_run_snapshot_digest(&self) -> Digest32 {
        product_agentd_run_snapshot_digest(&self.run_snapshot)
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
        product_validate_run_binding(self, receipt, /*terminal_required*/ true)?;
        if physical_terminal_digest.is_zero() {
            return Err(AgentdIntelligenceLearningErrorV1::Binding(
                "physical terminal digest",
            ));
        }
        let (selected_candidate_id, _) = product_selected_decision(self)?;
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
        ledger: &mut ProductLedgerWriter,
        outbox: &mut DurableIntelligenceLearningOutboxV1,
        expected_predecessor: Digest32,
        prepared: &PreparedAgentdIntelligenceRunV1,
        run_receipt: &RunReceipt,
        decision: ProductDecisionV2,
        evidence: &ProductSignedEvidenceV1,
        now: u64,
    ) -> Result<AgentdIntelligenceLearningAppendReceiptV1, AgentdIntelligenceLearningErrorV1> {
        product_validate_run_binding(prepared, run_receipt, /*terminal_required*/ false)?;
        product_validate_decision_binding(prepared, &decision)?;
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
        product_require_retryable_intent(&intent)?;
        self.product_require_current_learning_snapshot(
            prepared,
            outbox,
            &intent.operation_id,
        )?;
        match ledger.append_decision(expected_predecessor, decision, evidence, now) {
            Ok(receipt) => product_acknowledge(outbox, intent.operation_id, receipt),
            Err(error) => {
                product_classify_append_error(outbox, intent.operation_id, error)
            }
        }
    }

    /// Publish an independently authenticated physical Outcome only after the
    /// same Agentd run has terminal evidence and the ledger still has the active
    /// Decision for the supplied episode.
    #[allow(clippy::too_many_arguments)]
    pub fn append_production_outcome(
        &self,
        ledger: &mut ProductLedgerWriter,
        outbox: &mut DurableIntelligenceLearningOutboxV1,
        expected_predecessor: Digest32,
        prepared: &PreparedAgentdIntelligenceRunV1,
        terminal: &AgentdIntelligenceTerminalBindingV1,
        outcome: ProductOutcomeV1,
        evidence: &ProductSignedEvidenceV1,
        now: u64,
    ) -> Result<AgentdIntelligenceLearningAppendReceiptV1, AgentdIntelligenceLearningErrorV1> {
        product_validate_terminal_binding(prepared, terminal, &outcome)?;
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
        product_require_retryable_intent(&intent)?;
        self.product_require_current_learning_snapshot(
            prepared,
            outbox,
            &intent.operation_id,
        )?;
        match ledger.append_outcome(expected_predecessor, outcome, evidence, now) {
            Ok(receipt) => product_acknowledge(outbox, intent.operation_id, receipt),
            Err(error) => {
                product_classify_append_error(outbox, intent.operation_id, error)
            }
        }
    }

    fn product_require_current_learning_snapshot(
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
            product_mark_revoked_if_open(
                outbox,
                operation_id,
                "canonical owner currentness changed",
            )?;
            return Err(AgentdIntelligenceLearningErrorV1::Currentness(error));
        }
        Ok(())
    }
}

fn product_validate_run_binding(
    prepared: &PreparedAgentdIntelligenceRunV1,
    receipt: &RunReceipt,
    terminal_required: bool,
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    let snapshot = &prepared.run_snapshot;
    let expected_context = prepared.context_attachment.context_digest.as_str();
    let expected_compilation = prepared.envelope.envelope_digest.to_string();
    if receipt.run_id != snapshot.run_id
        || receipt.authority_epoch != snapshot.authority_epoch
        || receipt.generation != snapshot.generation
        || receipt.fence_digest != snapshot.fence_digest
        || receipt.deadline_ms != snapshot.deadline_ms
        || receipt.context_digest.as_deref() != Some(expected_context)
        || receipt.compilation_receipt_digest.as_deref()
            != Some(expected_compilation.as_str())
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

fn product_validate_decision_binding(
    prepared: &PreparedAgentdIntelligenceRunV1,
    decision: &ProductDecisionV2,
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    let (selected_candidate_id, selected_propensity_raw) = product_selected_decision(prepared)?;
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
            != product_candidate_ids_digest_v2(&expected_candidates)
        || decision.completeness.canonical_order_digest
            != product_candidate_order_digest_v2(&expected_candidates)
    {
        return Err(AgentdIntelligenceLearningErrorV1::Binding(
            "Decision/run/candidate identity",
        ));
    }
    Ok(())
}

fn product_validate_terminal_binding(
    prepared: &PreparedAgentdIntelligenceRunV1,
    terminal: &AgentdIntelligenceTerminalBindingV1,
    outcome: &ProductOutcomeV1,
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    let (selected_candidate_id, _) = product_selected_decision(prepared)?;
    if terminal.run_id != prepared.envelope.run_id
        || terminal.selected_candidate_id != selected_candidate_id
        || terminal.run_snapshot_digest != prepared.product_run_snapshot_digest()
        || terminal.context_digest != prepared.envelope.context_receipt_digest
        || terminal.envelope_digest != prepared.envelope.envelope_digest
        || !matches!(
            terminal.phase,
            RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed
        )
        || terminal.physical_terminal_digest.is_zero()
        || outcome.support_digest != terminal.physical_terminal_digest
    {
        return Err(AgentdIntelligenceLearningErrorV1::Binding(
            "Outcome/physical terminal identity",
        ));
    }
    Ok(())
}

fn product_selected_decision(
    prepared: &PreparedAgentdIntelligenceRunV1,
) -> Result<(StableId, u64), AgentdIntelligenceLearningErrorV1> {
    let ProductAdvisoryDecisionV1::Selected {
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

fn product_agentd_run_snapshot_digest(snapshot: &crate::AgentRunSnapshot) -> Digest32 {
    let mut bytes = b"hepta.agentd.intelligence-product-run-snapshot.v1\0".to_vec();
    product_push_string(&mut bytes, &snapshot.run_id);
    for value in [
        snapshot.request_digest.as_str(),
        snapshot.objective_digest.as_str(),
        snapshot.body_digest.as_str(),
        snapshot.artifact_set_digest.as_str(),
    ] {
        product_push_digest_string(&mut bytes, value);
    }
    bytes.extend_from_slice(&snapshot.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&snapshot.generation.to_be_bytes());
    product_push_digest_string(&mut bytes, &snapshot.fence_digest);
    bytes.extend_from_slice(&snapshot.deadline_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn product_acknowledge(
    outbox: &mut DurableIntelligenceLearningOutboxV1,
    operation_id: String,
    receipt: codex_hepta_learning_ledger::AppendReceipt,
) -> Result<AgentdIntelligenceLearningAppendReceiptV1, AgentdIntelligenceLearningErrorV1> {
    let state = outbox.acknowledge(&operation_id, &receipt)?;
    Ok(AgentdIntelligenceLearningAppendReceiptV1 {
        operation_id,
        outbox_revision: state.revision,
        state: state.state,
        append: receipt,
    })
}

fn product_require_retryable_intent(
    intent: &IntelligenceLearningIntentV1,
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    if matches!(
        intent.state,
        IntelligenceLearningAppendStateV1::Rejected
            | IntelligenceLearningAppendStateV1::Revoked
    ) {
        return Err(AgentdIntelligenceLearningErrorV1::Binding(
            "learning operation already has a terminal rejection",
        ));
    }
    Ok(())
}

fn product_classify_append_error<T>(
    outbox: &mut DurableIntelligenceLearningOutboxV1,
    operation_id: String,
    error: ProductLedgerError,
) -> Result<T, AgentdIntelligenceLearningErrorV1> {
    match error {
        ProductLedgerError::IndeterminateAfterLedgerCommit {
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
        ProductLedgerError::Durable(
            ProductDurableLedgerError::Indeterminate | ProductDurableLedgerError::Io(_),
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
        ProductLedgerError::Evidence(ProductSignedEvidenceError::Revoked) => {
            product_mark_revoked_if_open(
                outbox,
                &operation_id,
                "learning evidence signer is revoked",
            )?;
            Err(AgentdIntelligenceLearningErrorV1::Ledger(
                ProductLedgerError::Evidence(ProductSignedEvidenceError::Revoked),
            ))
        }
        other => {
            product_mark_rejected_if_open(
                outbox,
                &operation_id,
                "learning ledger rejected append",
            )?;
            Err(AgentdIntelligenceLearningErrorV1::Ledger(other))
        }
    }
}

fn product_mark_revoked_if_open(
    outbox: &mut DurableIntelligenceLearningOutboxV1,
    operation_id: &str,
    reason: &str,
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    if outbox
        .record(operation_id)
        .is_some_and(|record| !record.state.terminal())
    {
        outbox.mark_revoked(operation_id, reason)?;
    }
    Ok(())
}

fn product_mark_rejected_if_open(
    outbox: &mut DurableIntelligenceLearningOutboxV1,
    operation_id: &str,
    reason: &str,
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    if outbox
        .record(operation_id)
        .is_some_and(|record| !record.state.terminal())
    {
        outbox.mark_rejected(operation_id, reason)?;
    }
    Ok(())
}

fn product_push_string(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn product_push_digest_string(bytes: &mut Vec<u8>, value: &str) {
    match Digest32::from_str(value) {
        Ok(digest) => bytes.extend_from_slice(digest.as_array()),
        // AgentRunSnapshot construction validates these fields. Keep this
        // digest helper total while separating any invalid fallback identity.
        Err(_) => bytes.extend_from_slice(Digest32::of_bytes(value.as_bytes()).as_array()),
    }
}
