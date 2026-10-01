//! Immutable V2 payload codec and the sole product LedgerWriter adapters.
//! Field names, enum representation and digest grammars retain the V2 format.

use codex_hepta_learning_ledger::AuthenticatedDecisionRecordV2;
use codex_hepta_learning_ledger::AuthenticatedOutcomeRecordV2;
use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::OutcomeTerminalityV1;
use codex_hepta_learning_ledger::OutcomeWatermarkV1;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_learning_ledger::outcome_signing_payload_v2;
use codex_hepta_learning_ledger::validate_candidate_set_completeness;
use codex_hepta_types::FixedQ32;
use serde::Deserialize;
use serde::Serialize;

use super::*;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PersistedLearningEnvelopeV1 {
    pub(super) schema_version: u32,
    pub(super) owner_generation: u64,
    pub(super) payload: LearningPayloadV1,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub(super) enum LearningPayloadV1 {
    Decision(DecisionPayloadV1),
    Outcome(OutcomePayloadV1),
}

impl LearningPayloadV1 {
    pub(super) fn run_id(&self) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
        parse_id(match self {
            Self::Decision(value) => &value.record_id,
            Self::Outcome(value) => &value.decision_record_id,
        })
    }
    pub(super) fn episode_id(&self) -> &str {
        match self {
            Self::Decision(value) => &value.episode_id,
            Self::Outcome(value) => &value.episode_id,
        }
    }
    pub(super) fn run_snapshot_digest(
        &self,
    ) -> Result<Digest32, AgentdIntelligenceLearningErrorV1> {
        parse_digest(match self {
            Self::Decision(value) => &value.run_snapshot_digest,
            Self::Outcome(value) => &value.expected_run_snapshot_digest,
        })
    }
    pub(super) fn operation_id(&self) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
        match self {
            Self::Decision(value) => decision_operation_id(
                &parse_id(&value.record_id)?,
                &value.episode_id,
                parse_digest(&value.run_snapshot_digest)?,
                parse_digest(&value.decision_digest)?,
            ),
            Self::Outcome(value) => outcome_operation_id(
                &parse_id(&value.decision_record_id)?,
                &value.outcome.outcome_id,
                parse_digest(&value.physical_binding_digest)?,
            ),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct DecisionPayloadV1 {
    expected_ledger_predecessor: String,
    record_id: String,
    episode_id: String,
    run_snapshot_digest: String,
    objective_digest: String,
    policy_digest: String,
    candidate_ids: Vec<String>,
    selected_candidate_id: String,
    selected_propensity_raw: u64,
    completeness: CompletenessPayloadV1,
    support_digest: String,
    decision_digest: String,
    evidence: EvidencePayloadV1,
    evidence_binding: VerifiedEvidenceBindingPayloadV1,
    now: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OutcomePayloadV1 {
    expected_ledger_predecessor: String,
    decision_record_id: String,
    episode_id: String,
    expected_run_snapshot_digest: String,
    selected_candidate_id: String,
    physical_binding_digest: String,
    outcome: OutcomePayloadRecordV1,
    evidence: EvidencePayloadV1,
    evidence_binding: VerifiedEvidenceBindingPayloadV1,
    now: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CompletenessPayloadV1 {
    set_id: String,
    state_digest: String,
    generator_id: String,
    generator_code_digest: String,
    grammar_digest: String,
    hard_filter_digest: String,
    truncation_digest: String,
    candidates_digest: String,
    candidate_count: u32,
    omitted_count_bound: u32,
    canonical_order_digest: String,
    complete_for_generator: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct EvidencePayloadV1 {
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
struct PrincipalPayloadV1 {
    principal_id: String,
    credential_chain_digest: String,
    signing_key_digest: String,
    scope_digest: String,
    authority_epoch: u64,
    authenticated_at: u64,
    expires_at: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct OutcomePayloadRecordV1 {
    record_id: String,
    outcome_id: String,
    episode_id: String,
    observer: PrincipalPayloadV1,
    observed_at: Option<u64>,
    value_raw: Option<i64>,
    unit_profile_digest: String,
    support_digest: String,
    latest_observable_at: u64,
    expected_delay_profile_digest: String,
    terminality: String,
    censoring_reason: Option<String>,
    correction_predecessor: Option<String>,
    finalized_at: Option<u64>,
}

pub(super) fn decision_payload(
    writer: &LedgerWriter,
    prepared: &PreparedAgentdIntelligenceRunV1,
    request: AgentdIntelligenceDecisionAppendV1,
) -> Result<DecisionPayloadV1, AgentdIntelligenceLearningErrorV1> {
    let (selected_candidate_id, selected_propensity) = selected_decision(prepared)?;
    let snapshot = prepared.run_snapshot();
    let production = ProductionDecisionV2 {
        record_id: parse_id(&snapshot.run_id)?,
        episode_id: request.episode_id.clone(),
        run_snapshot_digest: intelligence_run_snapshot_digest_v1(prepared)?,
        objective_digest: prepared.envelope.objective_digest,
        policy_digest: request.policy_digest,
        candidate_ids: crate::intelligence_learning_candidates::learning_candidate_ids_v1(
            prepared.candidate_ids(),
        )
        .map_err(|error| AgentdIntelligenceLearningErrorV1::InvalidValue(error.to_string()))?,
        selected_candidate_id: selected_candidate_id.clone(),
        selected_propensity,
        completeness: request.completeness.clone(),
        support_digest: prepared.dispatch_proposal_digest,
    };
    let evidence_binding = verify_decision_evidence_binding(
        writer,
        &production,
        &request.evidence,
        clock::verification_time(request.now)?,
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
}

pub(super) fn outcome_payload(
    writer: &LedgerWriter,
    prepared: &PreparedAgentdIntelligenceRunV1,
    request: AgentdIntelligenceOutcomeAppendV1,
) -> Result<OutcomePayloadV1, AgentdIntelligenceLearningErrorV1> {
    let (selected_candidate_id, _) = selected_decision(prepared)?;
    let run_id = parse_id(&prepared.run_snapshot().run_id)?;
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
    let evidence_binding = verify_outcome_evidence_binding(
        writer,
        &request.outcome,
        &request.evidence,
        clock::verification_time(request.now)?,
    )?;
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
}

pub(super) fn observe_applied_payload(
    writer: &mut LedgerWriter,
    envelope: &PersistedLearningEnvelopeV1,
) -> Result<Option<AppendReceipt>, ProductionLedgerError> {
    let expected = expected_persisted_event(&envelope.payload)?;
    let predecessor = match &envelope.payload {
        LearningPayloadV1::Decision(value) => &value.expected_ledger_predecessor,
        LearningPayloadV1::Outcome(value) => &value.expected_ledger_predecessor,
    };
    writer.reconcile_exact_event_v1(ledger_digest(predecessor)?, &expected)
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
                return Err(ProductionLedgerError::Binding("decision generator binding"));
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
                    expected_delay_profile_digest: outcome.watermark.expected_delay_profile_digest,
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
}

pub(super) fn apply_payload(
    writer: &mut LedgerWriter,
    envelope: &PersistedLearningEnvelopeV1,
) -> Result<AppendReceipt, ProductionLedgerError> {
    match &envelope.payload {
        LearningPayloadV1::Decision(value) => apply_decision(writer, value),
        LearningPayloadV1::Outcome(value) => apply_outcome(writer, value),
    }
}

pub(super) fn apply_decision(
    writer: &mut LedgerWriter,
    payload: &DecisionPayloadV1,
) -> Result<AppendReceipt, ProductionLedgerError> {
    let request = decision_request_from_payload(payload)?;
    let evidence = payload
        .evidence
        .to_typed(LearningEvidenceRoleV1::Generator)?;
    let validation_now = clock::verification_time(payload.now)?;
    let current_binding =
        verify_decision_evidence_binding(writer, &request, &evidence, validation_now)?;
    if current_binding != payload.evidence_binding {
        return Err(ProductionLedgerError::Binding(
            "decision verified evidence drift",
        ));
    }
    writer.append_decision(
        ledger_digest(&payload.expected_ledger_predecessor)?,
        request,
        &evidence,
        clock::verification_time(payload.now)?,
    )
}

pub(super) fn apply_outcome(
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
                if value.record_id == decision_record_id && value.episode_id == episode_id
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
    let validation_now = clock::verification_time(payload.now)?;
    let current_binding =
        verify_outcome_evidence_binding(writer, &outcome, &evidence, validation_now)?;
    if current_binding != payload.evidence_binding {
        return Err(ProductionLedgerError::Binding(
            "outcome verified evidence drift",
        ));
    }
    writer.append_outcome(
        ledger_digest(&payload.expected_ledger_predecessor)?,
        outcome,
        &evidence,
        clock::verification_time(payload.now)?,
    )
}

impl From<CandidateSetCompletenessReceiptV1> for CompletenessPayloadV1 {
    fn from(value: CandidateSetCompletenessReceiptV1) -> Self {
        Self {
            set_id: value.set_id.to_string(),
            state_digest: value.state_digest.to_string(),
            generator_id: value.generator_id.to_string(),
            generator_code_digest: value.generator_code_digest.to_string(),
            grammar_digest: value.grammar_digest.to_string(),
            hard_filter_digest: value.hard_filter_digest.to_string(),
            truncation_digest: value.truncation_digest.to_string(),
            candidates_digest: value.candidates_digest.to_string(),
            candidate_count: value.candidate_count,
            omitted_count_bound: value.omitted_count_bound,
            canonical_order_digest: value.canonical_order_digest.to_string(),
            complete_for_generator: value.complete_for_generator,
        }
    }
}
impl CompletenessPayloadV1 {
    fn to_typed(&self) -> Result<CandidateSetCompletenessReceiptV1, ProductionLedgerError> {
        Ok(CandidateSetCompletenessReceiptV1 {
            set_id: ledger_id(&self.set_id)?,
            state_digest: ledger_digest(&self.state_digest)?,
            generator_id: ledger_id(&self.generator_id)?,
            generator_code_digest: ledger_digest(&self.generator_code_digest)?,
            grammar_digest: ledger_digest(&self.grammar_digest)?,
            hard_filter_digest: ledger_digest(&self.hard_filter_digest)?,
            truncation_digest: ledger_digest(&self.truncation_digest)?,
            candidates_digest: ledger_digest(&self.candidates_digest)?,
            candidate_count: self.candidate_count,
            omitted_count_bound: self.omitted_count_bound,
            canonical_order_digest: ledger_digest(&self.canonical_order_digest)?,
            complete_for_generator: self.complete_for_generator,
        })
    }
}
impl EvidencePayloadV1 {
    fn from_typed(value: &SignedLearningEvidenceV1) -> Self {
        Self {
            evidence_id: value.evidence_id.to_string(),
            principal_id: value.principal_id.to_string(),
            role: role_name(value.role).to_string(),
            trust_digest: value.trust_digest.to_string(),
            scope_digest: value.scope_digest.to_string(),
            objective_digest: value.objective_digest.to_string(),
            authority_epoch: value.authority_epoch,
            issued_at: value.issued_at,
            expires_at: value.expires_at,
            payload_digest: value.payload_digest.to_string(),
            signature: value.signature.to_vec(),
        }
    }
    fn to_typed(
        &self,
        expected_role: LearningEvidenceRoleV1,
    ) -> Result<SignedLearningEvidenceV1, ProductionLedgerError> {
        if self.role != role_name(expected_role) || self.signature.len() != 64 {
            return Err(ProductionLedgerError::Binding(
                "learning evidence role/signature",
            ));
        }
        Ok(SignedLearningEvidenceV1 {
            evidence_id: ledger_id(&self.evidence_id)?,
            principal_id: ledger_id(&self.principal_id)?,
            role: expected_role,
            trust_digest: ledger_digest(&self.trust_digest)?,
            scope_digest: ledger_digest(&self.scope_digest)?,
            objective_digest: ledger_digest(&self.objective_digest)?,
            authority_epoch: self.authority_epoch,
            issued_at: self.issued_at,
            expires_at: self.expires_at,
            payload_digest: ledger_digest(&self.payload_digest)?,
            signature: self
                .signature
                .as_slice()
                .try_into()
                .map_err(|_| ProductionLedgerError::Binding("learning evidence signature"))?,
        })
    }
}
impl VerifiedEvidenceBindingPayloadV1 {
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
}
impl PrincipalPayloadV1 {
    fn from_typed(value: &AuthenticatedPrincipalV1) -> Self {
        Self {
            principal_id: value.principal_id.to_string(),
            credential_chain_digest: value.credential_chain_digest.to_string(),
            signing_key_digest: value.signing_key_digest.to_string(),
            scope_digest: value.scope_digest.to_string(),
            authority_epoch: value.authority_epoch,
            authenticated_at: value.authenticated_at,
            expires_at: value.expires_at,
        }
    }
    fn to_typed(&self) -> Result<AuthenticatedPrincipalV1, ProductionLedgerError> {
        Ok(AuthenticatedPrincipalV1 {
            principal_id: ledger_id(&self.principal_id)?,
            credential_chain_digest: ledger_digest(&self.credential_chain_digest)?,
            signing_key_digest: ledger_digest(&self.signing_key_digest)?,
            scope_digest: ledger_digest(&self.scope_digest)?,
            authority_epoch: self.authority_epoch,
            authenticated_at: self.authenticated_at,
            expires_at: self.expires_at,
        })
    }
}
impl OutcomePayloadRecordV1 {
    fn from_typed(value: &AuthenticatedOutcomeV1) -> Self {
        Self {
            record_id: value.record_id.to_string(),
            outcome_id: value.outcome_id.to_string(),
            episode_id: value.episode_id.to_string(),
            observer: PrincipalPayloadV1::from_typed(&value.observer),
            observed_at: value.observed_at,
            value_raw: value.value.map(FixedQ32::raw),
            unit_profile_digest: value.unit_profile_digest.to_string(),
            support_digest: value.support_digest.to_string(),
            latest_observable_at: value.watermark.latest_observable_at,
            expected_delay_profile_digest: value
                .watermark
                .expected_delay_profile_digest
                .to_string(),
            terminality: terminality_name(value.watermark.terminality).to_string(),
            censoring_reason: value
                .watermark
                .censoring_reason
                .as_ref()
                .map(ToString::to_string),
            correction_predecessor: value
                .watermark
                .correction_predecessor
                .as_ref()
                .map(ToString::to_string),
            finalized_at: value.watermark.finalized_at,
        }
    }
    fn to_typed(&self) -> Result<AuthenticatedOutcomeV1, ProductionLedgerError> {
        let terminality = match self.terminality.as_str() {
            "pending" => OutcomeTerminalityV1::Pending,
            "censored" => OutcomeTerminalityV1::Censored,
            "terminal" => OutcomeTerminalityV1::Terminal,
            _ => return Err(ProductionLedgerError::Binding("outcome terminality")),
        };
        Ok(AuthenticatedOutcomeV1 {
            record_id: ledger_id(&self.record_id)?,
            outcome_id: ledger_id(&self.outcome_id)?,
            episode_id: ledger_id(&self.episode_id)?,
            observer: self.observer.to_typed()?,
            observed_at: self.observed_at,
            value: self.value_raw.map(FixedQ32::from_raw),
            unit_profile_digest: ledger_digest(&self.unit_profile_digest)?,
            support_digest: ledger_digest(&self.support_digest)?,
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: self.latest_observable_at,
                expected_delay_profile_digest: ledger_digest(&self.expected_delay_profile_digest)?,
                terminality,
                censoring_reason: self
                    .censoring_reason
                    .as_deref()
                    .map(ledger_id)
                    .transpose()?,
                correction_predecessor: self
                    .correction_predecessor
                    .as_deref()
                    .map(ledger_id)
                    .transpose()?,
                finalized_at: self.finalized_at,
            },
        })
    }
}
fn role_name(value: LearningEvidenceRoleV1) -> &'static str {
    match value {
        LearningEvidenceRoleV1::Generator => "generator",
        LearningEvidenceRoleV1::Observer => "observer",
        LearningEvidenceRoleV1::Evaluator => "evaluator",
        LearningEvidenceRoleV1::CreditAllocator => "credit_allocator",
        LearningEvidenceRoleV1::UnlearningAuthority => "unlearning_authority",
        LearningEvidenceRoleV1::Selector => "selector",
    }
}
fn terminality_name(value: OutcomeTerminalityV1) -> &'static str {
    match value {
        OutcomeTerminalityV1::Pending => "pending",
        OutcomeTerminalityV1::Censored => "censored",
        OutcomeTerminalityV1::Terminal => "terminal",
    }
}

#[cfg(test)]
#[path = "intelligence_learning_payload_tests.rs"]
mod tests;
