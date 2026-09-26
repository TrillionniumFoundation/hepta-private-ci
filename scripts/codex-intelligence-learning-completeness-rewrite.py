#!/usr/bin/env python3
# Bind durable Decision/Outcome observation to exact authenticated V2 rows.

from pathlib import Path


PATH = Path("codex-rs/hepta-agentd/src/intelligence_learning.rs")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0 and new in text:
        return text
    if count != 1:
        raise SystemExit(f"{PATH}: expected one {label} anchor, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, new: str, label: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        if new in text:
            return text
        raise SystemExit(f"{PATH}: missing {label} start")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise SystemExit(f"{PATH}: missing {label} end")
    return text[:start_index] + new.rstrip() + "\n\n" + text[end_index:]


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;''',
        '''use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::AuthenticatedDecisionRecordV2;
use codex_hepta_learning_ledger::AuthenticatedOutcomeRecordV2;
use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;''',
        "authenticated record imports",
    )
    text = replace_once(
        text,
        '''use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::validate_candidate_set_completeness;''',
        '''use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_learning_ledger::outcome_signing_payload_v2;
use codex_hepta_learning_ledger::validate_candidate_set_completeness;''',
        "evidence verification imports",
    )
    text = replace_once(
        text,
        "const LEARNING_PAYLOAD_SCHEMA_VERSION: u32 = 1;",
        "const LEARNING_PAYLOAD_SCHEMA_VERSION: u32 = 2;",
        "payload schema version",
    )
    text = replace_once(
        text,
        '''    evidence: EvidencePayloadV1,
    now: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct OutcomePayloadV1 {''',
        '''    evidence: EvidencePayloadV1,
    evidence_binding: VerifiedEvidenceBindingPayloadV1,
    now: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct OutcomePayloadV1 {''',
        "decision evidence binding field",
    )
    text = replace_once(
        text,
        '''    outcome: OutcomePayloadRecordV1,
    evidence: EvidencePayloadV1,
    now: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CompletenessPayloadV1 {''',
        '''    outcome: OutcomePayloadRecordV1,
    evidence: EvidencePayloadV1,
    evidence_binding: VerifiedEvidenceBindingPayloadV1,
    now: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CompletenessPayloadV1 {''',
        "outcome evidence binding field",
    )
    text = replace_once(
        text,
        '''struct EvidencePayloadV1 {
    evidence_id: String,
    principal_id: String,
    role: String,
    trust_digest: String,
    scope_digest: String,
    objective_digest: String,
    authority_epoch: u64,
    issued_at: u64,
    expires_at: u64,
    payload_digest: String,
    signature: Vec<u8>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PrincipalPayloadV1 {''',
        '''struct EvidencePayloadV1 {
    evidence_id: String,
    principal_id: String,
    role: String,
    trust_digest: String,
    scope_digest: String,
    objective_digest: String,
    authority_epoch: u64,
    issued_at: u64,
    expires_at: u64,
    payload_digest: String,
    signature: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct VerifiedEvidenceBindingPayloadV1 {
    principal_id: String,
    controller_id: String,
    credential_chain_digest: String,
    signing_key_digest: String,
    scope_digest: String,
    authority_epoch: u64,
    authentication_digest: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PrincipalPayloadV1 {''',
        "verified evidence binding record",
    )

    decision_block = r'''fn decision_payload(
    writer: &LedgerWriter,
    prepared: &PreparedAgentdIntelligenceRunV1,
    request: AgentdIntelligenceDecisionAppendV1,
) -> Result<DecisionPayloadV1, AgentdIntelligenceLearningErrorV1> {
    if request.expected_ledger_predecessor.is_zero() && request.episode_id.as_str().is_empty() {
        return Err(AgentdIntelligenceLearningErrorV1::Invalid(
            "decision identity",
        ));
    }
    let (selected_candidate_id, selected_propensity) = selected_decision(prepared)?;
    let snapshot = prepared.run_snapshot();
    let run_snapshot_digest = intelligence_run_snapshot_digest_v1(prepared)?;
    let production = ProductionDecisionV2 {
        record_id: parse_id(&snapshot.run_id)?,
        episode_id: request.episode_id.clone(),
        run_snapshot_digest,
        objective_digest: prepared.envelope.objective_digest,
        policy_digest: request.policy_digest,
        candidate_ids: prepared.candidate_ids().to_vec(),
        selected_candidate_id: selected_candidate_id.clone(),
        selected_propensity,
        completeness: request.completeness.clone(),
        support_digest: prepared.dispatch_proposal_digest,
    };
    let evidence_binding = verify_decision_evidence_binding(
        writer,
        &production,
        &request.evidence,
        request.now,
    )?;
    Ok(DecisionPayloadV1 {
        expected_ledger_predecessor: request.expected_ledger_predecessor.to_string(),
        record_id: production.record_id.to_string(),
        episode_id: production.episode_id.to_string(),
        run_snapshot_digest: production.run_snapshot_digest.to_string(),
        objective_digest: production.objective_digest.to_string(),
        policy_digest: production.policy_digest.to_string(),
        candidate_ids: production
            .candidate_ids
            .iter()
            .map(ToString::to_string)
            .collect(),
        selected_candidate_id: production.selected_candidate_id.to_string(),
        selected_propensity_raw: production.selected_propensity.raw(),
        completeness: production.completeness.into(),
        support_digest: production.support_digest.to_string(),
        decision_digest: prepared.envelope.decision.decision_digest.to_string(),
        evidence: EvidencePayloadV1::from_typed(&request.evidence),
        evidence_binding,
        now: request.now,
    })
}'''
    text = replace_between(
        text,
        "fn decision_payload(",
        "fn outcome_payload(",
        decision_block,
        "decision payload",
    )

    outcome_block = r'''fn outcome_payload(
    writer: &LedgerWriter,
    prepared: &PreparedAgentdIntelligenceRunV1,
    request: AgentdIntelligenceOutcomeAppendV1,
) -> Result<OutcomePayloadV1, AgentdIntelligenceLearningErrorV1> {
    let (selected_candidate_id, _) = selected_decision(prepared)?;
    let snapshot = prepared.run_snapshot();
    let run_id = parse_id(&snapshot.run_id)?;
    if request.decision_record_id != run_id
        || request.outcome.episode_id != request.episode_id
        || request.outcome.watermark.terminality != OutcomeTerminalityV1::Terminal
    {
        return Err(AgentdIntelligenceLearningErrorV1::Invalid(
            "outcome decision/episode/terminality binding",
        ));
    }
    let run_snapshot_digest = intelligence_run_snapshot_digest_v1(prepared)?;
    let physical_binding_digest = intelligence_physical_terminal_binding_digest_v1(
        prepared,
        &request.run_receipt,
        request.provider_terminal_digest,
    )?;
    if request.outcome.support_digest != physical_binding_digest {
        return Err(AgentdIntelligenceLearningErrorV1::Invalid(
            "outcome physical support binding",
        ));
    }
    let evidence_binding =
        verify_outcome_evidence_binding(writer, &request.outcome, &request.evidence, request.now)?;
    Ok(OutcomePayloadV1 {
        expected_ledger_predecessor: request.expected_ledger_predecessor.to_string(),
        decision_record_id: request.decision_record_id.to_string(),
        episode_id: request.episode_id.to_string(),
        expected_run_snapshot_digest: run_snapshot_digest.to_string(),
        selected_candidate_id: selected_candidate_id.to_string(),
        physical_binding_digest: physical_binding_digest.to_string(),
        outcome: OutcomePayloadRecordV1::from_typed(&request.outcome),
        evidence: EvidencePayloadV1::from_typed(&request.evidence),
        evidence_binding,
        now: request.now,
    })
}'''
    text = replace_between(
        text,
        "fn outcome_payload(",
        "fn observe_applied_payload(",
        outcome_block,
        "outcome payload",
    )

    observation_block = r'''fn observe_applied_payload(
    writer: &LedgerWriter,
    envelope: &PersistedLearningEnvelopeV1,
) -> Result<Option<AppendReceipt>, ProductionLedgerError> {
    let expected = expected_persisted_event(&envelope.payload)?;
    let records = writer.records()?;
    let matched = records
        .iter()
        .rev()
        .find(|record| record.event == expected);
    Ok(matched.map(|record| AppendReceipt {
        disposition: AppendDisposition::IdempotentReplay,
        sequence: record.sequence,
        event_digest: record.event_digest,
        chain_digest: record.chain_digest,
    }))
}

fn expected_persisted_event(
    payload: &LearningPayloadV1,
) -> Result<LedgerEvent, ProductionLedgerError> {
    match payload {
        LearningPayloadV1::Decision(payload) => {
            let request = decision_request_from_payload(payload)?;
            let evidence = payload
                .evidence
                .to_typed(LearningEvidenceRoleV1::Generator)?;
            payload.evidence_binding.require_evidence(&evidence)?;
            let _ = decision_signing_payload_v2(&request)?;
            let completeness_digest = validate_candidate_set_completeness(&request.completeness)
                .map_err(ProductionLedgerError::Causal)?;
            let generator_id = payload.evidence_binding.principal_id()?;
            if request.completeness.generator_id != generator_id {
                return Err(ProductionLedgerError::Binding(
                    "decision generator binding",
                ));
            }
            Ok(LedgerEvent::AuthenticatedDecisionV2(
                AuthenticatedDecisionRecordV2 {
                    record_id: request.record_id,
                    episode_id: request.episode_id,
                    run_snapshot_digest: request.run_snapshot_digest,
                    objective_digest: request.objective_digest,
                    policy_digest: request.policy_digest,
                    generator_id,
                    generator_controller_id: payload.evidence_binding.controller_id()?,
                    generator_credential_chain_digest: payload
                        .evidence_binding
                        .credential_chain_digest()?,
                    generator_signing_key_digest: payload.evidence_binding.signing_key_digest()?,
                    generator_scope_digest: payload.evidence_binding.scope_digest()?,
                    generator_authority_epoch: payload.evidence_binding.authority_epoch,
                    candidate_ids: request.candidate_ids,
                    selected_candidate_id: request.selected_candidate_id,
                    selected_propensity: request.selected_propensity,
                    candidate_completeness_digest: completeness_digest,
                    support_digest: request.support_digest,
                    authentication_digest: payload.evidence_binding.authentication_digest()?,
                },
            ))
        }
        LearningPayloadV1::Outcome(payload) => {
            let outcome = outcome_from_payload(payload)?;
            let evidence = payload
                .evidence
                .to_typed(LearningEvidenceRoleV1::Observer)?;
            payload.evidence_binding.require_evidence(&evidence)?;
            payload
                .evidence_binding
                .require_principal(&outcome.observer)?;
            let terminality = match outcome.watermark.terminality {
                OutcomeTerminalityV1::Pending => AuthenticatedOutcomeTerminality::Pending,
                OutcomeTerminalityV1::Censored => AuthenticatedOutcomeTerminality::Censored,
                OutcomeTerminalityV1::Terminal => AuthenticatedOutcomeTerminality::Terminal,
            };
            Ok(LedgerEvent::AuthenticatedOutcomeV2(
                AuthenticatedOutcomeRecordV2 {
                    record_id: outcome.record_id,
                    outcome_id: outcome.outcome_id,
                    episode_id: outcome.episode_id,
                    observer_id: payload.evidence_binding.principal_id()?,
                    observer_controller_id: payload.evidence_binding.controller_id()?,
                    observer_credential_chain_digest: payload
                        .evidence_binding
                        .credential_chain_digest()?,
                    observer_signing_key_digest: payload.evidence_binding.signing_key_digest()?,
                    observer_scope_digest: payload.evidence_binding.scope_digest()?,
                    observer_authority_epoch: payload.evidence_binding.authority_epoch,
                    observed_at: outcome.observed_at,
                    value: outcome.value,
                    unit_profile_digest: outcome.unit_profile_digest,
                    support_digest: outcome.support_digest,
                    latest_observable_at: outcome.watermark.latest_observable_at,
                    expected_delay_profile_digest: outcome
                        .watermark
                        .expected_delay_profile_digest,
                    terminality,
                    censoring_reason: outcome.watermark.censoring_reason,
                    correction_predecessor: outcome.watermark.correction_predecessor,
                    finalized_at: outcome.watermark.finalized_at,
                    authentication_digest: payload.evidence_binding.authentication_digest()?,
                },
            ))
        }
    }
}

fn decision_request_from_payload(
    payload: &DecisionPayloadV1,
) -> Result<ProductionDecisionV2, ProductionLedgerError> {
    Ok(ProductionDecisionV2 {
        record_id: ledger_id(&payload.record_id)?,
        episode_id: ledger_id(&payload.episode_id)?,
        run_snapshot_digest: ledger_digest(&payload.run_snapshot_digest)?,
        objective_digest: ledger_digest(&payload.objective_digest)?,
        policy_digest: ledger_digest(&payload.policy_digest)?,
        candidate_ids: payload
            .candidate_ids
            .iter()
            .map(|value| ledger_id(value))
            .collect::<Result<Vec<_>, _>>()?,
        selected_candidate_id: ledger_id(&payload.selected_candidate_id)?,
        selected_propensity: ProbabilityQ32::from_raw(payload.selected_propensity_raw)
            .map_err(|_| ProductionLedgerError::Binding("decision propensity"))?,
        completeness: payload.completeness.to_typed()?,
        support_digest: ledger_digest(&payload.support_digest)?,
    })
}

fn outcome_from_payload(
    payload: &OutcomePayloadV1,
) -> Result<AuthenticatedOutcomeV1, ProductionLedgerError> {
    payload.outcome.to_typed()
}

fn verify_decision_evidence_binding(
    writer: &LedgerWriter,
    request: &ProductionDecisionV2,
    evidence: &SignedLearningEvidenceV1,
    now: u64,
) -> Result<VerifiedEvidenceBindingPayloadV1, ProductionLedgerError> {
    let signing_payload = decision_signing_payload_v2(request)?;
    let verified = writer
        .verifier()
        .verify(
            LearningEvidenceRoleV1::Generator,
            evidence,
            &signing_payload,
            now,
        )
        .map_err(ProductionLedgerError::Evidence)?;
    if request.objective_digest != writer.verifier().objective_digest()
        || request.completeness.generator_id != verified.principal().principal_id
    {
        return Err(ProductionLedgerError::Binding(
            "decision objective or generator",
        ));
    }
    Ok(VerifiedEvidenceBindingPayloadV1::from_verified(
        &verified, evidence,
    ))
}

fn verify_outcome_evidence_binding(
    writer: &LedgerWriter,
    outcome: &AuthenticatedOutcomeV1,
    evidence: &SignedLearningEvidenceV1,
    now: u64,
) -> Result<VerifiedEvidenceBindingPayloadV1, ProductionLedgerError> {
    let signing_payload = outcome_signing_payload_v2(outcome);
    let verified = writer
        .verifier()
        .verify(
            LearningEvidenceRoleV1::Observer,
            evidence,
            &signing_payload,
            now,
        )
        .map_err(ProductionLedgerError::Evidence)?;
    if verified.principal() != &outcome.observer {
        return Err(ProductionLedgerError::Binding("outcome observer"));
    }
    Ok(VerifiedEvidenceBindingPayloadV1::from_verified(
        &verified, evidence,
    ))
}'''
    text = replace_between(
        text,
        "fn observe_applied_payload(",
        "fn apply_payload(",
        observation_block,
        "destination observation",
    )

    apply_decision_block = r'''fn apply_decision(
    writer: &mut LedgerWriter,
    payload: &DecisionPayloadV1,
) -> Result<AppendReceipt, ProductionLedgerError> {
    let request = decision_request_from_payload(payload)?;
    let evidence = payload
        .evidence
        .to_typed(LearningEvidenceRoleV1::Generator)?;
    let current_binding =
        verify_decision_evidence_binding(writer, &request, &evidence, payload.now)?;
    if current_binding != payload.evidence_binding {
        return Err(ProductionLedgerError::Binding(
            "decision verified evidence drift",
        ));
    }
    writer.append_decision(
        ledger_digest(&payload.expected_ledger_predecessor)?,
        request,
        &evidence,
        payload.now,
    )
}'''
    text = replace_between(
        text,
        "fn apply_decision(",
        "fn apply_outcome(",
        apply_decision_block,
        "decision apply",
    )

    apply_outcome_block = r'''fn apply_outcome(
    writer: &mut LedgerWriter,
    payload: &OutcomePayloadV1,
) -> Result<AppendReceipt, ProductionLedgerError> {
    let decision_record_id = ledger_id(&payload.decision_record_id)?;
    let episode_id = ledger_id(&payload.episode_id)?;
    writer.verify_active_decision_binding(&decision_record_id, &episode_id)?;
    let expected_snapshot = ledger_digest(&payload.expected_run_snapshot_digest)?;
    let expected_candidate = ledger_id(&payload.selected_candidate_id)?;
    let records = writer.records()?;
    let decision_matches = records.iter().rev().any(|record| {
        matches!(
            &record.event,
            LedgerEvent::AuthenticatedDecisionV2(value)
                if value.record_id == decision_record_id
                    && value.episode_id == episode_id
                    && value.run_snapshot_digest == expected_snapshot
                    && value.selected_candidate_id == expected_candidate
        )
    });
    if !decision_matches {
        return Err(ProductionLedgerError::Binding(
            "outcome decision/candidate/snapshot",
        ));
    }
    let outcome = outcome_from_payload(payload)?;
    if outcome.episode_id != episode_id
        || outcome.support_digest != ledger_digest(&payload.physical_binding_digest)?
        || outcome.watermark.terminality != OutcomeTerminalityV1::Terminal
    {
        return Err(ProductionLedgerError::Binding(
            "outcome physical terminal binding",
        ));
    }
    let evidence = payload
        .evidence
        .to_typed(LearningEvidenceRoleV1::Observer)?;
    let current_binding =
        verify_outcome_evidence_binding(writer, &outcome, &evidence, payload.now)?;
    if current_binding != payload.evidence_binding {
        return Err(ProductionLedgerError::Binding(
            "outcome verified evidence drift",
        ));
    }
    writer.append_outcome(
        ledger_digest(&payload.expected_ledger_predecessor)?,
        outcome,
        &evidence,
        payload.now,
    )
}'''
    text = replace_between(
        text,
        "fn apply_outcome(",
        "fn classify_authority_error(",
        apply_outcome_block,
        "outcome apply",
    )

    text = replace_once(
        text,
        "    let payload = decision_payload(prepared, request)?;",
        "    let payload = decision_payload(writer, prepared, request)?;",
        "direct decision append",
    )
    text = replace_once(
        text,
        "    let payload = outcome_payload(prepared, request)?;",
        "    let payload = outcome_payload(writer, prepared, request)?;",
        "direct outcome append",
    )
    text = replace_once(
        text,
        '''        let payload = LearningPayloadV1::Decision(decision_payload(prepared, request)?);
        self.enqueue(prepared, payload, None).await''',
        '''        let payload = {
            let writer = self
                .writer
                .lock()
                .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?;
            LearningPayloadV1::Decision(decision_payload(&writer, prepared, request)?)
        };
        self.enqueue(prepared, payload, None).await''',
        "queued decision construction",
    )
    text = replace_once(
        text,
        '''        let payload = LearningPayloadV1::Outcome(outcome_payload(prepared, request)?);
        let predecessor = decision_operation_id(''',
        '''        let payload = {
            let writer = self
                .writer
                .lock()
                .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?;
            LearningPayloadV1::Outcome(outcome_payload(&writer, prepared, request)?)
        };
        let predecessor = decision_operation_id(''',
        "queued outcome construction",
    )

    binding_impl = r'''impl VerifiedEvidenceBindingPayloadV1 {
    fn from_verified(
        value: &VerifiedLearningEvidenceV1,
        evidence: &SignedLearningEvidenceV1,
    ) -> Self {
        let principal = value.principal();
        Self {
            principal_id: principal.principal_id.to_string(),
            controller_id: value.controller_id().to_string(),
            credential_chain_digest: principal.credential_chain_digest.to_string(),
            signing_key_digest: principal.signing_key_digest.to_string(),
            scope_digest: principal.scope_digest.to_string(),
            authority_epoch: principal.authority_epoch,
            authentication_digest: learning_evidence_digest_v1(evidence).to_string(),
        }
    }

    fn principal_id(&self) -> Result<StableId, ProductionLedgerError> {
        ledger_id(&self.principal_id)
    }

    fn controller_id(&self) -> Result<StableId, ProductionLedgerError> {
        ledger_id(&self.controller_id)
    }

    fn credential_chain_digest(&self) -> Result<Digest32, ProductionLedgerError> {
        ledger_digest(&self.credential_chain_digest)
    }

    fn signing_key_digest(&self) -> Result<Digest32, ProductionLedgerError> {
        ledger_digest(&self.signing_key_digest)
    }

    fn scope_digest(&self) -> Result<Digest32, ProductionLedgerError> {
        ledger_digest(&self.scope_digest)
    }

    fn authentication_digest(&self) -> Result<Digest32, ProductionLedgerError> {
        ledger_digest(&self.authentication_digest)
    }

    fn require_evidence(
        &self,
        evidence: &SignedLearningEvidenceV1,
    ) -> Result<(), ProductionLedgerError> {
        if self.principal_id()? != evidence.principal_id
            || self.scope_digest()? != evidence.scope_digest
            || self.authority_epoch != evidence.authority_epoch
            || self.authentication_digest()? != learning_evidence_digest_v1(evidence)
        {
            return Err(ProductionLedgerError::Binding(
                "persisted signed evidence binding",
            ));
        }
        Ok(())
    }

    fn require_principal(
        &self,
        principal: &AuthenticatedPrincipalV1,
    ) -> Result<(), ProductionLedgerError> {
        if self.principal_id()? != principal.principal_id
            || self.credential_chain_digest()? != principal.credential_chain_digest
            || self.signing_key_digest()? != principal.signing_key_digest
            || self.scope_digest()? != principal.scope_digest
            || self.authority_epoch != principal.authority_epoch
        {
            return Err(ProductionLedgerError::Binding(
                "persisted authenticated principal binding",
            ));
        }
        Ok(())
    }
}

fn learning_evidence_digest_v1(evidence: &SignedLearningEvidenceV1) -> Digest32 {
    let mut bytes = evidence.signing_bytes();
    bytes.extend_from_slice(&evidence.signature);
    Digest32::of_bytes(&bytes)
}'''
    text = replace_once(
        text,
        "impl PrincipalPayloadV1 {",
        binding_impl + "\n\nimpl PrincipalPayloadV1 {",
        "verified evidence binding implementation",
    )

    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
