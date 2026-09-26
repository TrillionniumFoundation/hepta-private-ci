//! Product Decision/Outcome closure for canonical intelligence runs.
//!
//! Every append is first persisted as an exact replay intent. The host then
//! delegates to the production `LedgerWriter`, never the qualification-only
//! legacy writer. Restart reconciliation decodes and retries only the identical
//! signed request and predecessor. Ambiguous commit acknowledgement remains
//! `Indeterminate`; current trust rejection becomes `Revoked`; deterministic
//! binding rejection becomes `Rejected`.

use std::str::FromStr;
use std::sync::Mutex;

use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::OutcomeTerminalityV1;
use codex_hepta_learning_ledger::OutcomeWatermarkV1;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdIntelligenceObservabilityV1;
use crate::IntelligenceLearningIntentKindV1;
use crate::IntelligenceLearningIntentV1;
use crate::IntelligenceLearningOutboxError;
use crate::IntelligenceLearningOutboxStateV1;
use crate::IntelligenceLearningOutboxV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceDecisionAppendV1 {
    pub expected_predecessor: Digest32,
    pub run_id: StableId,
    pub run_snapshot_digest: Digest32,
    pub decision_digest: Digest32,
    pub decision: ProductionDecisionV2,
    pub evidence: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceOutcomeAppendV1 {
    pub expected_predecessor: Digest32,
    pub run_id: StableId,
    pub run_snapshot_digest: Digest32,
    pub decision_digest: Digest32,
    pub selected_candidate_id: StableId,
    pub outcome: AuthenticatedOutcomeV1,
    pub evidence: SignedLearningEvidenceV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AgentdIntelligenceLearningDispositionV1 {
    Acknowledged,
    Indeterminate,
    Rejected,
    Revoked,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceLearningReceiptV1 {
    pub intent_id: StableId,
    pub disposition: AgentdIntelligenceLearningDispositionV1,
    pub append: Option<AppendReceipt>,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct AgentdIntelligenceReconciliationSummaryV1 {
    pub acknowledged: u64,
    pub indeterminate: u64,
    pub rejected: u64,
    pub revoked: u64,
}

#[derive(Debug, thiserror::Error)]
pub enum AgentdIntelligenceLearningErrorV1 {
    #[error("intelligence learning request binding is invalid")]
    Binding,
    #[error("intelligence learning request encoding failed: {0}")]
    Encoding(#[from] serde_json::Error),
    #[error("intelligence learning outbox failed: {0}")]
    Outbox(#[from] IntelligenceLearningOutboxError),
    #[error("intelligence learning ledger failed: {0}")]
    Ledger(ProductionLedgerError),
    #[error("intelligence learning host mutex is poisoned")]
    Poisoned,
}

pub struct AgentdIntelligenceLearningHostV1 {
    writer: Mutex<LedgerWriter>,
    outbox: Mutex<IntelligenceLearningOutboxV1>,
    observability: std::sync::Arc<AgentdIntelligenceObservabilityV1>,
}

impl AgentdIntelligenceLearningHostV1 {
    pub fn new(
        writer: LedgerWriter,
        outbox: IntelligenceLearningOutboxV1,
        observability: std::sync::Arc<AgentdIntelligenceObservabilityV1>,
    ) -> Self {
        observability.set_learning_outbox_backlog(outbox.backlog());
        Self {
            writer: Mutex::new(writer),
            outbox: Mutex::new(outbox),
            observability,
        }
    }

    pub fn backlog(&self) -> Result<usize, AgentdIntelligenceLearningErrorV1> {
        Ok(self
            .outbox
            .lock()
            .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?
            .backlog())
    }

    pub fn append_decision(
        &self,
        request: AgentdIntelligenceDecisionAppendV1,
        now: u64,
    ) -> Result<AgentdIntelligenceLearningReceiptV1, AgentdIntelligenceLearningErrorV1> {
        validate_decision_binding(&request)?;
        let command = LearningCommandWireV1::Decision {
            expected_predecessor: request.expected_predecessor.to_string(),
            run_id: request.run_id.to_string(),
            run_snapshot_digest: request.run_snapshot_digest.to_string(),
            decision_digest: request.decision_digest.to_string(),
            decision: DecisionWireV1::from(&request.decision),
            evidence: EvidenceWireV1::from(&request.evidence),
        };
        let payload = serde_json::to_vec(&command)?;
        let selected_candidate_id = request.decision.selected_candidate_id.clone();
        self.execute(
            IntelligenceLearningIntentKindV1::Decision,
            request.run_id,
            request.expected_predecessor,
            request.run_snapshot_digest,
            request.decision_digest,
            selected_candidate_id,
            payload,
            now,
        )
    }

    pub fn append_outcome(
        &self,
        request: AgentdIntelligenceOutcomeAppendV1,
        now: u64,
    ) -> Result<AgentdIntelligenceLearningReceiptV1, AgentdIntelligenceLearningErrorV1> {
        validate_outcome_binding(&request)?;
        let command = LearningCommandWireV1::Outcome {
            expected_predecessor: request.expected_predecessor.to_string(),
            run_id: request.run_id.to_string(),
            run_snapshot_digest: request.run_snapshot_digest.to_string(),
            decision_digest: request.decision_digest.to_string(),
            selected_candidate_id: request.selected_candidate_id.to_string(),
            outcome: OutcomeWireV1::from(&request.outcome),
            evidence: EvidenceWireV1::from(&request.evidence),
        };
        let payload = serde_json::to_vec(&command)?;
        self.execute(
            IntelligenceLearningIntentKindV1::Outcome,
            request.run_id,
            request.expected_predecessor,
            request.run_snapshot_digest,
            request.decision_digest,
            request.selected_candidate_id,
            payload,
            now,
        )
    }

    pub fn reconcile(
        &self,
        now: u64,
    ) -> Result<AgentdIntelligenceReconciliationSummaryV1, AgentdIntelligenceLearningErrorV1> {
        let pending = self
            .outbox
            .lock()
            .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?
            .reconcileable();
        let mut summary = AgentdIntelligenceReconciliationSummaryV1::default();
        for record in pending {
            let result = self.execute_existing(record.intent, record.revision, now)?;
            match result.disposition {
                AgentdIntelligenceLearningDispositionV1::Acknowledged => {
                    summary.acknowledged = summary.acknowledged.saturating_add(1)
                }
                AgentdIntelligenceLearningDispositionV1::Indeterminate => {
                    summary.indeterminate = summary.indeterminate.saturating_add(1)
                }
                AgentdIntelligenceLearningDispositionV1::Rejected => {
                    summary.rejected = summary.rejected.saturating_add(1)
                }
                AgentdIntelligenceLearningDispositionV1::Revoked => {
                    summary.revoked = summary.revoked.saturating_add(1)
                }
            }
        }
        self.refresh_backlog()?;
        Ok(summary)
    }

    #[allow(clippy::too_many_arguments)]
    fn execute(
        &self,
        kind: IntelligenceLearningIntentKindV1,
        run_id: StableId,
        expected_predecessor: Digest32,
        run_snapshot_digest: Digest32,
        decision_digest: Digest32,
        selected_candidate_id: StableId,
        payload: Vec<u8>,
        now: u64,
    ) -> Result<AgentdIntelligenceLearningReceiptV1, AgentdIntelligenceLearningErrorV1> {
        let payload_digest = Digest32::of_bytes(&payload);
        let intent_id = StableId::new(format!(
            "intelligence-learning:{}:{payload_digest}",
            match kind {
                IntelligenceLearningIntentKindV1::Decision => "decision",
                IntelligenceLearningIntentKindV1::Outcome => "outcome",
            }
        ))
        .map_err(|_| AgentdIntelligenceLearningErrorV1::Binding)?;
        let intent = IntelligenceLearningIntentV1 {
            intent_id,
            run_id,
            kind,
            expected_predecessor,
            run_snapshot_digest,
            decision_digest,
            selected_candidate_id,
            payload_digest,
            payload,
        };
        let prepared = self
            .outbox
            .lock()
            .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?
            .prepare(intent.clone())?;
        let result = self.execute_existing(intent, prepared.revision, now);
        self.refresh_backlog()?;
        result
    }

    fn execute_existing(
        &self,
        intent: IntelligenceLearningIntentV1,
        revision: u64,
        now: u64,
    ) -> Result<AgentdIntelligenceLearningReceiptV1, AgentdIntelligenceLearningErrorV1> {
        let command: LearningCommandWireV1 = serde_json::from_slice(&intent.payload)?;
        let result = {
            let mut writer = self
                .writer
                .lock()
                .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?;
            match command {
                LearningCommandWireV1::Decision {
                    expected_predecessor,
                    run_id,
                    run_snapshot_digest,
                    decision_digest,
                    decision,
                    evidence,
                } => {
                    require_wire_binding(
                        &intent,
                        IntelligenceLearningIntentKindV1::Decision,
                        &expected_predecessor,
                        &run_id,
                        &run_snapshot_digest,
                        &decision_digest,
                        &decision.selected_candidate_id,
                    )?;
                    writer.append_decision(
                        parse_digest(&expected_predecessor)?,
                        decision.try_into()?,
                        &evidence.try_into()?,
                        now,
                    )
                }
                LearningCommandWireV1::Outcome {
                    expected_predecessor,
                    run_id,
                    run_snapshot_digest,
                    decision_digest,
                    selected_candidate_id,
                    outcome,
                    evidence,
                } => {
                    require_wire_binding(
                        &intent,
                        IntelligenceLearningIntentKindV1::Outcome,
                        &expected_predecessor,
                        &run_id,
                        &run_snapshot_digest,
                        &decision_digest,
                        &selected_candidate_id,
                    )?;
                    let run_id = parse_id(&run_id)?;
                    let run_snapshot_digest = parse_digest(&run_snapshot_digest)?;
                    let decision_digest = parse_digest(&decision_digest)?;
                    let selected_candidate_id = parse_id(&selected_candidate_id)?;
                    let outcome: AuthenticatedOutcomeV1 = outcome.try_into()?;
                    writer.verify_active_intelligence_decision_binding(
                        &run_id,
                        &outcome.episode_id,
                        run_snapshot_digest,
                        &selected_candidate_id,
                        decision_digest,
                    )?;
                    writer.append_outcome(
                        parse_digest(&expected_predecessor)?,
                        outcome,
                        &evidence.try_into()?,
                        now,
                    )
                }
            }
        };
        self.finish(intent.intent_id, revision, result)
    }

    fn finish(
        &self,
        intent_id: StableId,
        revision: u64,
        result: Result<AppendReceipt, ProductionLedgerError>,
    ) -> Result<AgentdIntelligenceLearningReceiptV1, AgentdIntelligenceLearningErrorV1> {
        match result {
            Ok(receipt) => {
                self.transition(
                    &intent_id,
                    revision,
                    IntelligenceLearningOutboxStateV1::Acknowledged,
                    receipt.chain_digest,
                )?;
                Ok(AgentdIntelligenceLearningReceiptV1 {
                    intent_id,
                    disposition: AgentdIntelligenceLearningDispositionV1::Acknowledged,
                    append: Some(receipt),
                })
            }
            Err(ProductionLedgerError::IndeterminateAfterLedgerCommit { receipt, .. }) => {
                self.transition(
                    &intent_id,
                    revision,
                    IntelligenceLearningOutboxStateV1::Indeterminate,
                    receipt.chain_digest,
                )?;
                Ok(AgentdIntelligenceLearningReceiptV1 {
                    intent_id,
                    disposition: AgentdIntelligenceLearningDispositionV1::Indeterminate,
                    append: Some(receipt),
                })
            }
            Err(error) if is_revocation(&error) => {
                self.transition(
                    &intent_id,
                    revision,
                    IntelligenceLearningOutboxStateV1::Revoked,
                    error_digest(&error),
                )?;
                Ok(AgentdIntelligenceLearningReceiptV1 {
                    intent_id,
                    disposition: AgentdIntelligenceLearningDispositionV1::Revoked,
                    append: None,
                })
            }
            Err(error) => {
                self.transition(
                    &intent_id,
                    revision,
                    IntelligenceLearningOutboxStateV1::Rejected,
                    error_digest(&error),
                )?;
                Ok(AgentdIntelligenceLearningReceiptV1 {
                    intent_id,
                    disposition: AgentdIntelligenceLearningDispositionV1::Rejected,
                    append: None,
                })
            }
        }
    }

    fn transition(
        &self,
        intent_id: &StableId,
        revision: u64,
        state: IntelligenceLearningOutboxStateV1,
        evidence: Digest32,
    ) -> Result<(), AgentdIntelligenceLearningErrorV1> {
        self.outbox
            .lock()
            .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?
            .transition(intent_id, revision, state, evidence)?;
        Ok(())
    }

    fn refresh_backlog(&self) -> Result<(), AgentdIntelligenceLearningErrorV1> {
        let backlog = self
            .outbox
            .lock()
            .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?
            .backlog();
        self.observability.set_learning_outbox_backlog(backlog);
        Ok(())
    }
}

fn validate_decision_binding(
    request: &AgentdIntelligenceDecisionAppendV1,
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    if request.expected_predecessor.is_zero()
        || request.run_snapshot_digest.is_zero()
        || request.decision_digest.is_zero()
        || request.decision.record_id != request.run_id
        || request.decision.run_snapshot_digest != request.run_snapshot_digest
        || request.decision.support_digest != request.decision_digest
    {
        return Err(AgentdIntelligenceLearningErrorV1::Binding);
    }
    Ok(())
}

fn validate_outcome_binding(
    request: &AgentdIntelligenceOutcomeAppendV1,
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    if request.expected_predecessor.is_zero()
        || request.run_snapshot_digest.is_zero()
        || request.decision_digest.is_zero()
        || request.outcome.record_id != request.run_id
    {
        return Err(AgentdIntelligenceLearningErrorV1::Binding);
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn require_wire_binding(
    intent: &IntelligenceLearningIntentV1,
    kind: IntelligenceLearningIntentKindV1,
    predecessor: &str,
    run_id: &str,
    snapshot: &str,
    decision: &str,
    selected: &str,
) -> Result<(), AgentdIntelligenceLearningErrorV1> {
    if intent.kind != kind
        || intent.expected_predecessor != parse_digest(predecessor)?
        || intent.run_id != parse_id(run_id)?
        || intent.run_snapshot_digest != parse_digest(snapshot)?
        || intent.decision_digest != parse_digest(decision)?
        || intent.selected_candidate_id != parse_id(selected)?
        || Digest32::of_bytes(&intent.payload) != intent.payload_digest
    {
        return Err(AgentdIntelligenceLearningErrorV1::Binding);
    }
    Ok(())
}

fn is_revocation(error: &ProductionLedgerError) -> bool {
    matches!(
        error,
        ProductionLedgerError::Evidence(
            SignedEvidenceError::UnknownSigner
                | SignedEvidenceError::ContextMismatch
                | SignedEvidenceError::ValidityWindow
                | SignedEvidenceError::Revoked
        )
    )
}

fn error_digest(error: &ProductionLedgerError) -> Digest32 {
    Digest32::of_bytes(format!("hepta.agentd.intelligence-learning-error.v1:{error:?}").as_bytes())
}

fn parse_id(value: &str) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
    StableId::new(value.to_string()).map_err(|_| AgentdIntelligenceLearningErrorV1::Binding)
}

fn parse_digest(value: &str) -> Result<Digest32, AgentdIntelligenceLearningErrorV1> {
    let value = Digest32::from_str(value).map_err(|_| AgentdIntelligenceLearningErrorV1::Binding)?;
    if value.is_zero() {
        return Err(AgentdIntelligenceLearningErrorV1::Binding);
    }
    Ok(value)
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum LearningCommandWireV1 {
    Decision {
        expected_predecessor: String,
        run_id: String,
        run_snapshot_digest: String,
        decision_digest: String,
        decision: DecisionWireV1,
        evidence: EvidenceWireV1,
    },
    Outcome {
        expected_predecessor: String,
        run_id: String,
        run_snapshot_digest: String,
        decision_digest: String,
        selected_candidate_id: String,
        outcome: OutcomeWireV1,
        evidence: EvidenceWireV1,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct DecisionWireV1 {
    record_id: String,
    episode_id: String,
    run_snapshot_digest: String,
    objective_digest: String,
    policy_digest: String,
    candidate_ids: Vec<String>,
    selected_candidate_id: String,
    selected_propensity: u64,
    completeness: CompletenessWireV1,
    support_digest: String,
}

impl From<&ProductionDecisionV2> for DecisionWireV1 {
    fn from(value: &ProductionDecisionV2) -> Self {
        Self {
            record_id: value.record_id.to_string(),
            episode_id: value.episode_id.to_string(),
            run_snapshot_digest: value.run_snapshot_digest.to_string(),
            objective_digest: value.objective_digest.to_string(),
            policy_digest: value.policy_digest.to_string(),
            candidate_ids: value.candidate_ids.iter().map(ToString::to_string).collect(),
            selected_candidate_id: value.selected_candidate_id.to_string(),
            selected_propensity: value.selected_propensity.raw(),
            completeness: CompletenessWireV1::from(&value.completeness),
            support_digest: value.support_digest.to_string(),
        }
    }
}

impl TryFrom<DecisionWireV1> for ProductionDecisionV2 {
    type Error = AgentdIntelligenceLearningErrorV1;

    fn try_from(value: DecisionWireV1) -> Result<Self, Self::Error> {
        Ok(Self {
            record_id: parse_id(&value.record_id)?,
            episode_id: parse_id(&value.episode_id)?,
            run_snapshot_digest: parse_digest(&value.run_snapshot_digest)?,
            objective_digest: parse_digest(&value.objective_digest)?,
            policy_digest: parse_digest(&value.policy_digest)?,
            candidate_ids: value
                .candidate_ids
                .iter()
                .map(|value| parse_id(value))
                .collect::<Result<Vec<_>, _>>()?,
            selected_candidate_id: parse_id(&value.selected_candidate_id)?,
            selected_propensity: ProbabilityQ32::from_raw(value.selected_propensity)
                .map_err(|_| AgentdIntelligenceLearningErrorV1::Binding)?,
            completeness: value.completeness.try_into()?,
            support_digest: parse_digest(&value.support_digest)?,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct CompletenessWireV1 {
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

impl From<&CandidateSetCompletenessReceiptV1> for CompletenessWireV1 {
    fn from(value: &CandidateSetCompletenessReceiptV1) -> Self {
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

impl TryFrom<CompletenessWireV1> for CandidateSetCompletenessReceiptV1 {
    type Error = AgentdIntelligenceLearningErrorV1;

    fn try_from(value: CompletenessWireV1) -> Result<Self, Self::Error> {
        Ok(Self {
            set_id: parse_id(&value.set_id)?,
            state_digest: parse_digest(&value.state_digest)?,
            generator_id: parse_id(&value.generator_id)?,
            generator_code_digest: parse_digest(&value.generator_code_digest)?,
            grammar_digest: parse_digest(&value.grammar_digest)?,
            hard_filter_digest: parse_digest(&value.hard_filter_digest)?,
            truncation_digest: parse_digest(&value.truncation_digest)?,
            candidates_digest: parse_digest(&value.candidates_digest)?,
            candidate_count: value.candidate_count,
            omitted_count_bound: value.omitted_count_bound,
            canonical_order_digest: parse_digest(&value.canonical_order_digest)?,
            complete_for_generator: value.complete_for_generator,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct EvidenceWireV1 {
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

impl From<&SignedLearningEvidenceV1> for EvidenceWireV1 {
    fn from(value: &SignedLearningEvidenceV1) -> Self {
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
}

impl TryFrom<EvidenceWireV1> for SignedLearningEvidenceV1 {
    type Error = AgentdIntelligenceLearningErrorV1;

    fn try_from(value: EvidenceWireV1) -> Result<Self, Self::Error> {
        let signature: [u8; 64] = value
            .signature
            .try_into()
            .map_err(|_| AgentdIntelligenceLearningErrorV1::Binding)?;
        Ok(Self {
            evidence_id: parse_id(&value.evidence_id)?,
            principal_id: parse_id(&value.principal_id)?,
            role: parse_role(&value.role)?,
            trust_digest: parse_digest(&value.trust_digest)?,
            scope_digest: parse_digest(&value.scope_digest)?,
            objective_digest: parse_digest(&value.objective_digest)?,
            authority_epoch: value.authority_epoch,
            issued_at: value.issued_at,
            expires_at: value.expires_at,
            payload_digest: parse_digest(&value.payload_digest)?,
            signature,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct PrincipalWireV1 {
    principal_id: String,
    credential_chain_digest: String,
    signing_key_digest: String,
    scope_digest: String,
    authority_epoch: u64,
    authenticated_at: u64,
    expires_at: u64,
}

impl From<&AuthenticatedPrincipalV1> for PrincipalWireV1 {
    fn from(value: &AuthenticatedPrincipalV1) -> Self {
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
}

impl TryFrom<PrincipalWireV1> for AuthenticatedPrincipalV1 {
    type Error = AgentdIntelligenceLearningErrorV1;

    fn try_from(value: PrincipalWireV1) -> Result<Self, Self::Error> {
        Ok(Self {
            principal_id: parse_id(&value.principal_id)?,
            credential_chain_digest: parse_digest(&value.credential_chain_digest)?,
            signing_key_digest: parse_digest(&value.signing_key_digest)?,
            scope_digest: parse_digest(&value.scope_digest)?,
            authority_epoch: value.authority_epoch,
            authenticated_at: value.authenticated_at,
            expires_at: value.expires_at,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct OutcomeWireV1 {
    record_id: String,
    outcome_id: String,
    episode_id: String,
    observer: PrincipalWireV1,
    observed_at: Option<u64>,
    value: Option<i64>,
    unit_profile_digest: String,
    support_digest: String,
    latest_observable_at: u64,
    expected_delay_profile_digest: String,
    terminality: String,
    censoring_reason: Option<String>,
    correction_predecessor: Option<String>,
    finalized_at: Option<u64>,
}

impl From<&AuthenticatedOutcomeV1> for OutcomeWireV1 {
    fn from(value: &AuthenticatedOutcomeV1) -> Self {
        Self {
            record_id: value.record_id.to_string(),
            outcome_id: value.outcome_id.to_string(),
            episode_id: value.episode_id.to_string(),
            observer: PrincipalWireV1::from(&value.observer),
            observed_at: value.observed_at,
            value: value.value.map(FixedQ32::raw),
            unit_profile_digest: value.unit_profile_digest.to_string(),
            support_digest: value.support_digest.to_string(),
            latest_observable_at: value.watermark.latest_observable_at,
            expected_delay_profile_digest: value
                .watermark
                .expected_delay_profile_digest
                .to_string(),
            terminality: match value.watermark.terminality {
                OutcomeTerminalityV1::Pending => "pending",
                OutcomeTerminalityV1::Censored => "censored",
                OutcomeTerminalityV1::Terminal => "terminal",
            }
            .to_string(),
            censoring_reason: value.watermark.censoring_reason.map(|value| value.to_string()),
            correction_predecessor: value
                .watermark
                .correction_predecessor
                .map(|value| value.to_string()),
            finalized_at: value.watermark.finalized_at,
        }
    }
}

impl TryFrom<OutcomeWireV1> for AuthenticatedOutcomeV1 {
    type Error = AgentdIntelligenceLearningErrorV1;

    fn try_from(value: OutcomeWireV1) -> Result<Self, Self::Error> {
        Ok(Self {
            record_id: parse_id(&value.record_id)?,
            outcome_id: parse_id(&value.outcome_id)?,
            episode_id: parse_id(&value.episode_id)?,
            observer: value.observer.try_into()?,
            observed_at: value.observed_at,
            value: value.value.map(FixedQ32::from_raw),
            unit_profile_digest: parse_digest(&value.unit_profile_digest)?,
            support_digest: parse_digest(&value.support_digest)?,
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: value.latest_observable_at,
                expected_delay_profile_digest: parse_digest(
                    &value.expected_delay_profile_digest,
                )?,
                terminality: match value.terminality.as_str() {
                    "pending" => OutcomeTerminalityV1::Pending,
                    "censored" => OutcomeTerminalityV1::Censored,
                    "terminal" => OutcomeTerminalityV1::Terminal,
                    _ => return Err(AgentdIntelligenceLearningErrorV1::Binding),
                },
                censoring_reason: value
                    .censoring_reason
                    .as_deref()
                    .map(parse_digest)
                    .transpose()?,
                correction_predecessor: value
                    .correction_predecessor
                    .as_deref()
                    .map(parse_digest)
                    .transpose()?,
                finalized_at: value.finalized_at,
            },
        })
    }
}

fn role_name(role: LearningEvidenceRoleV1) -> &'static str {
    match role {
        LearningEvidenceRoleV1::Generator => "generator",
        LearningEvidenceRoleV1::Observer => "observer",
        LearningEvidenceRoleV1::Evaluator => "evaluator",
        LearningEvidenceRoleV1::CreditAllocator => "credit_allocator",
        LearningEvidenceRoleV1::UnlearningAuthority => "unlearning_authority",
        LearningEvidenceRoleV1::Selector => "selector",
    }
}

fn parse_role(value: &str) -> Result<LearningEvidenceRoleV1, AgentdIntelligenceLearningErrorV1> {
    match value {
        "generator" => Ok(LearningEvidenceRoleV1::Generator),
        "observer" => Ok(LearningEvidenceRoleV1::Observer),
        "evaluator" => Ok(LearningEvidenceRoleV1::Evaluator),
        "credit_allocator" => Ok(LearningEvidenceRoleV1::CreditAllocator),
        "unlearning_authority" => Ok(LearningEvidenceRoleV1::UnlearningAuthority),
        "selector" => Ok(LearningEvidenceRoleV1::Selector),
        _ => Err(AgentdIntelligenceLearningErrorV1::Binding),
    }
}
